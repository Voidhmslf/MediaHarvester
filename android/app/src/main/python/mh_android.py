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
_cookies_path = ""
_probe_enabled = True  # тесты отключают сетевой разбор ссылок
_probe_pool = None  # поток-пул для разбора ссылок (название, обложка, качества)


def init(data_dir: str, staging_dir: str, ffmpeg_dir: str = "", ffmpeg_libs: str = "", auto_update: bool = True) -> None:
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
        # Загруженный раньше yt-dlp подключается ДО первого импорта yt_dlp (иначе останется версия из APK)
        try:
            from src.utils.ytdlp_updater import activate_override
            activate_override()
        except Exception:
            pass
        _inited = True
        if auto_update:
            threading.Thread(target=_background_update, name="mh-update", daemon=True).start()


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


def set_cookies(path: str) -> None:
    """Файл cookies.txt (Netscape) с входами пользователя; пустая строка — без входа."""
    global _cookies_path
    with _lock:
        _cookies_path = path if path and os.path.isfile(path) else ""


_COOKIE_ADVICE = "Войдите в этот сервис в блоке «Аккаунты» на вкладке «Ссылки»."


def _android_text(message: str, hint: str) -> tuple[str, str]:
    """Подсказки ядра про cookies.txt/браузер написаны для компьютера: на телефоне ведём в блок «Аккаунты»."""
    import re
    if re.search(r"cookies|браузер", message, re.IGNORECASE):
        message = re.split(r"[:.]?\s*(?:[Уу]кажите|[Зз]акройте|[Вв]ыберите)", message, maxsplit=1)[0].strip() or message
        hint = _COOKIE_ADVICE
    elif re.search(r"cookies", hint, re.IGNORECASE):
        hint = _COOKIE_ADVICE
    return message, hint


def vk_logout() -> None:
    global _vk_token
    with _lock:
        _vk_token = ""


def _background_update() -> None:
    """Раз в 12 часов проверяет новый yt-dlp (как на компьютере); вступает в силу после перезапуска."""
    try:
        from src.utils.ytdlp_updater import check_for_update
        check_for_update()
    except Exception:
        pass


def engine_versions() -> str:
    """Версии движков: yt-dlp (в работе и скачанная, если новее), gallery-dl."""
    from src.utils.ytdlp_updater import current_version, override_path, read_zip_version, version_key
    ytdlp = current_version()
    pending = ""
    try:
        zipped = read_zip_version(override_path())
        if zipped and version_key(zipped) > version_key(ytdlp):
            pending = zipped
    except Exception:
        pass
    try:
        import gallery_dl.version
        gallery = gallery_dl.version.__version__
    except Exception:
        gallery = ""
    return json.dumps({"ytdlp": ytdlp, "pending": pending, "gallery_dl": gallery}, ensure_ascii=False)


def update_ytdlp() -> str:
    """Принудительная проверка yt-dlp. Возвращает JSON {status, current, latest, message}."""
    from src.utils.ytdlp_updater import check_for_update
    r = check_for_update(force=True)
    return json.dumps({"status": r.status, "current": r.current, "latest": r.latest, "message": r.message},
                      ensure_ascii=False)


def log_tail() -> str:
    """Хвост журнала (секреты замаскированы) — чтобы поделиться им при ошибке."""
    from src.utils.logger import read_log_tail
    return read_log_tail(200)


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
    probe_ids: list[tuple[int, str]] = []
    with _lock:
        known = {it["url"] for it in _items}
        for url in parse_urls(text):
            if url in known:
                continue
            _items.append({
                "id": _next_id, "url": url, "label": detect_url_type(url)["label"],
                "status": "pending", "text": "", "progress": None, "message": "", "hint": "",
                "technical": "", "files": [], "kind": "link",
                "title": "", "thumbnail": "", "uploader": "", "duration": 0,
                "quality": "", "quality_options": [], "probing": False,
            })
            probe_ids.append((_next_id, url))
            _next_id += 1
            added += 1
    for item_id, url in probe_ids:
        _start_probe(item_id, url)
    return added


_PRESET_HEIGHTS = (("4K (2160p)", 2160), ("2K (1440p)", 1440), ("Full HD (1080p)", 1080),
                   ("HD (720p)", 720), ("SD (480p)", 480), ("360p", 360))
AUTO_QUALITY = "Максимальное (Авто)"
AUDIO_QUALITY = "Только аудио (MP3)"


def quality_options(heights: list[int]) -> list[str]:
    """Какие качества имеет смысл предлагать для ссылки: максимальное, доступные разрешения, звук."""
    top = max(heights) if heights else 0
    options = [AUTO_QUALITY]
    options += [name for name, h in _PRESET_HEIGHTS if not top or top >= h * 0.9]
    return options + [AUDIO_QUALITY]


def _find(item_id: int) -> dict | None:
    return next((it for it in _items if it["id"] == item_id), None)


def _start_probe(item_id: int, url: str) -> None:
    """Название, обложка и доступные качества ссылки — в фоне, не мешая ни вводу, ни загрузке."""
    global _probe_pool
    from concurrent.futures import ThreadPoolExecutor
    from src.core.router import detect_url_type
    if not _probe_enabled or detect_url_type(url)["engine"] != "ytdlp":
        return
    with _lock:
        it = _find(item_id)
        if it is not None:
            it["probing"] = True
        if _probe_pool is None:
            _probe_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mh-probe")
    _probe_pool.submit(_probe, item_id, url)


def _probe(item_id: int, url: str) -> None:
    try:
        from src.core.ytdlp_engine import probe_media
        info = probe_media(url, cookies_path=_cookies_path)
    except Exception:
        info = None
    with _lock:
        it = _find(item_id)
        if it is None:
            return
        it["probing"] = False
        if info:
            it["title"], it["thumbnail"] = info["title"], info["thumbnail"]
            it["uploader"], it["duration"] = info["uploader"], int(info["duration"] or 0)
            it["quality_options"] = quality_options(info["heights"])
        else:
            it["quality_options"] = quality_options([])


def set_item_quality(item_id: int, quality: str) -> None:
    """Качество для одной ссылки; пустая строка — как выбрано для всей очереди."""
    with _lock:
        it = _find(item_id)
        if it is not None and it["status"] not in ("working", "done"):
            it["quality"] = quality


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
                message, hint = _android_text(qi.message, qi.hint)
                it["status"], it["message"], it["hint"], it["technical"] = qi.status, message, hint, qi.technical

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
                folder = _download_one(qi.url, it.get("quality") or quality, cb)
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
    return download_track_list(text=text, download_path=_staging, progress_callback=cb,
                               cookies_path=_cookies_path, cancel_event=_cancel)


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
        return download_instagram(url=url, download_path=_staging, cookies_path=_cookies_path,
                                  status_callback=cb, cancel_event=_cancel, anonymous_first=True)
    if engine == "gallery":
        return download_gallery(
            url=url, download_path=_staging, platform_name=gallery_platform_name(url) or "Gallery",
            cookies_path=_cookies_path, status_callback=cb, cancel_event=_cancel,
            listing=bool(detected.get("listing")))
    title = download_video(
        url=url, download_path=_staging, quality_choice=quality, progress_callback=cb,
        cookies_path=_cookies_path, cancel_event=_cancel, allow_playlist=bool(detected.get("playlist")))
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
