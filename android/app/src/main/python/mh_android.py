"""Мост между Android-приложением (Kotlin) и Python-ядром MediaHarvester.

Kotlin вызывает функции модуля через Chaquopy и опрашивает snapshot() (JSON): так не нужны
обратные вызовы из потоков Python в Java. Все функции потокобезопасны.
"""
import json
import os
import threading
import time

_lock = threading.RLock()
_inited = False
_items: list[dict] = []
_next_id = 1
_cancel = threading.Event()
_thread: threading.Thread | None = None
_staging = ""
_vk_token = ""


def init(data_dir: str, staging_dir: str, ffmpeg_dir: str = "", ffmpeg_libs: str = "") -> None:
    """Вызывается один раз при запуске: пути приложения и (необязательно) папка с ffmpeg и его библиотеками."""
    global _inited, _staging
    with _lock:
        if _inited:
            return
        os.environ["MH_ANDROID"] = "1"
        os.environ["MH_DATA_DIR"] = data_dir
        os.environ["MH_FFMPEG"] = ffmpeg_dir or ""
        if ffmpeg_libs:  # ffmpeg запускается подпроцессом и ищет свои .so здесь
            os.environ["LD_LIBRARY_PATH"] = ffmpeg_libs + os.pathsep + os.environ.get("LD_LIBRARY_PATH", "")
        os.makedirs(staging_dir, exist_ok=True)
        _staging = staging_dir
        from src.utils.logger import setup_logging
        setup_logging()
        _inited = True


def vk_auth_url() -> str:
    """Адрес входа VK для фотографий (токен вернётся в адресе blank.html#access_token=...)."""
    from src.config import AUTH_URL_PHOTOS
    return AUTH_URL_PHOTOS


def vk_login(text: str, validate: bool = True) -> str:
    """
    Принимает адрес после входа (или голый токен), проверяет его и запоминает для скачивания фото.
    Возвращает JSON {"ok", "token", "name", "error"}.
    """
    global _vk_token
    import re
    from src.core.vk_auth import fetch_user_name
    from src.core.vk_engine import extract_token
    from src.utils.logger import register_secret

    raw = (text or "").strip()
    if "access_token=" in raw:
        token = extract_token(re.search(r"\S*access_token=\S+", raw).group(0))
    elif re.fullmatch(r"[A-Za-z0-9_.\-]{20,}", raw):
        token = raw
    else:
        return json.dumps({"ok": False, "error": "В тексте нет токена VK"}, ensure_ascii=False)

    name = ""
    if validate:
        try:
            name = fetch_user_name(token) or ""
        except Exception:
            return json.dumps({"ok": False, "error": "VK не принял токен: войдите заново"}, ensure_ascii=False)
    register_secret(token)
    with _lock:
        _vk_token = token
    return json.dumps({"ok": True, "token": token, "name": name}, ensure_ascii=False)


def vk_logout() -> None:
    global _vk_token
    with _lock:
        _vk_token = ""


def version() -> str:
    from src.version import __version__
    return __version__


def qualities() -> str:
    from src.config import QUALITY_PRESETS
    return json.dumps(QUALITY_PRESETS, ensure_ascii=False)


def _list_files() -> set[str]:
    found = set()
    for root, _, names in os.walk(_staging):
        for name in names:
            if not name.endswith((".part", ".ytdl", ".temp")):
                found.add(os.path.join(root, name))
    return found


def add_links(text: str) -> int:
    """Достаёт ссылки из текста и добавляет новые в очередь. Возвращает, сколько добавлено."""
    global _next_id
    from src.core.download_queue import parse_urls
    from src.core.router import detect_url_type
    added = 0
    with _lock:
        known = {it["url"] for it in _items}
        for url in parse_urls(text):
            if url in known:
                continue
            _items.append({
                "id": _next_id, "url": url, "label": detect_url_type(url)["label"],
                "status": "pending", "text": "", "progress": None, "message": "", "hint": "",
                "technical": "", "files": [], "kind": "link",
            })
            _next_id += 1
            added += 1
    return added


def add_tracks(text: str) -> int:
    """Список «Исполнитель — Название» -> один элемент очереди. Возвращает число треков (0 — список пуст)."""
    global _next_id
    from src.core.track_search import parse_track_list
    count = len(parse_track_list(text))
    if not count:
        return 0
    with _lock:
        known = {it.get("payload") for it in _items if it["kind"] == "tracks"}
        if text in known:
            return 0
        _items.append({
            "id": _next_id, "url": f"Треков в списке: {count}", "label": "Треки по списку (YouTube → MP3)",
            "status": "pending", "text": "", "progress": None, "message": "", "hint": "",
            "technical": "", "files": [], "kind": "tracks", "payload": text,
        })
        _next_id += 1
    return count


def remove(item_id: int) -> None:
    with _lock:
        if _thread and _thread.is_alive():
            return
        _items[:] = [it for it in _items if it["id"] != item_id]


def clear_finished() -> None:
    with _lock:
        if _thread and _thread.is_alive():
            return
        _items[:] = [it for it in _items if it["status"] != "done"]


def is_running() -> bool:
    return bool(_thread and _thread.is_alive())


def start(quality: str) -> bool:
    """Запускает очередь в фоновом потоке. False — уже идёт или нечего скачивать."""
    global _thread
    from src.core.download_queue import RUNNABLE
    with _lock:
        if is_running() or not any(it["status"] in RUNNABLE for it in _items):
            return False
        _cancel.clear()
        _thread = threading.Thread(target=_work, args=(quality,), name="mh-queue", daemon=True)
        _thread.start()
    return True


def cancel() -> None:
    _cancel.set()


def _work(quality: str) -> None:
    from src.core.download_queue import QueueItem, run_queue
    # run_queue работает с QueueItem; связываем их с записями очереди по порядку
    pairs = [(QueueItem(url=it["url"], label=it["label"], status=it["status"]), it) for it in _items]

    def sync() -> None:
        with _lock:
            for qi, it in pairs:
                it["status"], it["message"], it["hint"], it["technical"] = qi.status, qi.message, qi.hint, qi.technical

    qi_to_dict = {id(qi): it for qi, it in pairs}

    def run_one(qi: QueueItem, number: int, total: int) -> str:
        it = qi_to_dict[id(qi)]

        def cb(text, state="idle", progress=None, percent_str=""):
            with _lock:
                it["text"], it["progress"] = text, progress

        try:
            if it["kind"] == "tracks":
                folder = _download_tracks(it["payload"], cb)
            else:
                folder = _download_one(qi.url, quality, cb)
        finally:
            # Всё, что лежит во временной папке: сюда попадают и файлы, оставшиеся от отменённых или упавших
            # запусков (трек, скачанный до отмены, должен дойти до «Загрузок» при повторе). Очередь идёт
            # по одному элементу, а экспорт удаляет уже сохранённое, так что чужого здесь нет.
            with _lock:
                it["files"] = sorted(_list_files())
        return folder

    try:
        run_queue([qi for qi, _ in pairs], run_one, _cancel, sync)
    finally:
        sync()


def _download_tracks(text: str, cb) -> str:
    from src.core.track_search import download_track_list
    return download_track_list(text=text, download_path=_staging, progress_callback=cb, cancel_event=_cancel)


def _download_one(url: str, quality: str, cb) -> str:
    from src.core.gallery_engine import download_gallery
    from src.core.insta_engine import download_instagram
    from src.core.router import detect_url_type, gallery_platform_name
    from src.core.ytdlp_engine import download_video

    detected = detect_url_type(url)
    engine = detected["engine"]
    if engine == "vk_music":
        raise RuntimeError("Музыка ВКонтакте на телефоне недоступна. Используйте «Треки по списку»")
    if engine == "vk_photos":
        from src.core.vk_engine import download_vk_photos
        if not _vk_token:
            raise RuntimeError("Для фото ВКонтакте нужно войти: нажмите «Войти» в блоке «ВКонтакте · фото» на вкладке «Ссылки»")
        return download_vk_photos(token_raw=_vk_token, url=url, download_path=_staging,
                                  progress_callback=cb, cancel_event=_cancel)

    if engine == "insta":
        return download_instagram(url=url, download_path=_staging, status_callback=cb, cancel_event=_cancel)
    if engine == "gallery":
        return download_gallery(
            url=url, download_path=_staging, platform_name=gallery_platform_name(url) or "Gallery",
            status_callback=cb, cancel_event=_cancel, listing=bool(detected.get("listing")))
    title = download_video(
        url=url, download_path=_staging, quality_choice=quality, progress_callback=cb,
        cancel_event=_cancel, allow_playlist=bool(detected.get("playlist")))
    cb(f"Готово: {title[:40]}", "success", 1.0, "100%")
    return _staging


def snapshot() -> str:
    with _lock:
        return json.dumps({
            "running": is_running(),
            "cancelling": _cancel.is_set() and is_running(),
            "items": [{k: v for k, v in it.items() if k != "payload"} for it in _items],
            "ts": time.time(),
        }, ensure_ascii=False)
