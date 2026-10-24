import os
import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Any
from urllib.parse import urlparse
import requests
from requests.adapters import HTTPAdapter
import vk_api
import vk_api.exceptions

from src.config import VK_MUSIC_USER_AGENT
from src.utils.helpers import sanitize_filename, DownloadCancelledError
from src.utils.logger import get_logger

log = get_logger("vk")

# Проверка наличия vkpymusic
try:
    from vkpymusic import Service as VkMusicService
    from vkpymusic.service import download_m3u8_as_mp3_pyav
    VKPYMUSIC_AVAILABLE = True
except ImportError:
    VkMusicService = None
    download_m3u8_as_mp3_pyav = None
    VKPYMUSIC_AVAILABLE = False

# Приоритет типов размеров фото ВКонтакте (от наибольшего к наименьшему)
TYPE_ORDER = ['w', 'z', 'y', 'x', 'r', 'q', 'p', 'm', 's']
TYPE_PRIORITY = {t: len(TYPE_ORDER) - i for i, t in enumerate(TYPE_ORDER)}

PHOTO_WORKERS = 8
PHOTO_RETRIES = 3
PHOTO_EXTENSIONS = ("jpg", "jpeg", "png", "webp", "gif")
FAILED_REPORT_NAME = "_failed.txt"


def extract_token(s: str) -> str:
    """Извлекает access_token из OAuth-redirect URL или возвращает очищенную строку."""
    m = re.search(r"access_token=([^&#]+)", s, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return s.strip()


def extract_album_ids(url: str) -> tuple[str | None, str | None]:
    """Разбирает ссылку на альбом VK -> (owner_id, album_id) или (None, None)."""
    m = re.search(r"album(-?\d+)_([a-zA-Z0-9]+)", url)
    if m:
        oid = m.group(1)
        aid = m.group(2)
        aid = {"0": "profile", "00": "wall", "000": "saved"}.get(aid, aid)
        return oid, aid
    return None, None


def extract_music_target(url: str) -> dict[str, Any] | None:
    """
    Разбирает ссылку для музыкального режима.
    Возвращает dict с параметрами для запроса или None.
    """
    m = re.search(r"playlist/(-?\d+)_(\d+)(?:_([a-zA-Z0-9]+))?", url)
    if m:
        return {
            "type": "playlist",
            "owner_id": int(m.group(1)),
            "playlist_id": int(m.group(2)),
            "access_key": m.group(3) or "",
        }
    # Одна песня: vk.com/audio-123_456 или ...?z=audio-123_456_ключ
    m = re.search(r"audio(-?\d+)_(\d+)(?:_([a-zA-Z0-9]+))?", url)
    if m:
        return {"type": "track", "owner_id": int(m.group(1)), "audio_id": int(m.group(2)),
                "access_key": m.group(3) or ""}
    m = re.search(r"vk\.(?:com|ru)/(?:id|audios)(\d+)", url)
    if m:
        return {"type": "user", "user_id": int(m.group(1))}
    m = re.match(r"^-?\d+$", url.strip())
    if m:
        return {"type": "user", "user_id": int(url.strip())}
    return None


def get_best_photo_size(sizes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """
    Выбирает объект из массива sizes с максимальным разрешением:
    1. Сортирует по (width * height), если есть ненулевые размеры.
    2. Если width/height равны 0 (бывает в старых фото ВК), использует приоритет типов:
       ['w', 'z', 'y', 'x', 'r', 'q', 'p', 'm', 's'].
    """
    if not sizes:
        return None

    max_area = max((s.get("width", 0) * s.get("height", 0)) for s in sizes)
    if max_area > 0:
        return max(sizes, key=lambda s: (s.get("width", 0) * s.get("height", 0)))

    return max(sizes, key=lambda s: TYPE_PRIORITY.get(s.get("type", ""), 0))


def photo_extension(url: str) -> str:
    """Берёт расширение файла из URL фото; по умолчанию jpg."""
    ext = os.path.splitext(urlparse(url).path)[1].lstrip(".").lower()
    return ext if ext in PHOTO_EXTENSIONS else "jpg"


def existing_photo_ids(folder: str) -> set[str]:
    """Id уже скачанных фото в папке (имена вида photo_0001_<id>.<ext>) — для докачки."""
    ids: set[str] = set()
    for name in os.listdir(folder):
        m = re.fullmatch(r"photo_\d+_(\d+)\.\w+", name)
        if m and os.path.getsize(os.path.join(folder, name)) > 0:
            ids.add(m.group(1))
    return ids


def download_photo_file(
    session: requests.Session,
    url: str,
    out_path: str,
    cancel_event: threading.Event | None = None
) -> None:
    """
    Скачивает один файл во временный .part и атомарно переименовывает по завершении.
    Делает до PHOTO_RETRIES попыток с нарастающей паузой, проверяет полноту по Content-Length.
    """
    part_path = out_path + ".part"
    last_error: Exception | None = None
    for attempt in range(PHOTO_RETRIES):
        if cancel_event and cancel_event.is_set():
            raise DownloadCancelledError("Загрузка отменена пользователем")
        try:
            with session.get(url, stream=True, timeout=(10, 30)) as r:
                r.raise_for_status()
                expected = int(r.headers.get("Content-Length") or 0)
                written = 0
                with open(part_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=64 * 1024):
                        if cancel_event and cancel_event.is_set():
                            raise DownloadCancelledError("Загрузка отменена пользователем")
                        f.write(chunk)
                        written += len(chunk)
            if written == 0 or (expected and written != expected):
                raise IOError(f"Файл скачан не полностью ({written} из {expected} байт)")
            os.replace(part_path, out_path)
            return
        except DownloadCancelledError:
            raise
        except Exception as e:
            last_error = e
            if attempt < PHOTO_RETRIES - 1:
                time.sleep(1.5 * (attempt + 1))
        finally:
            if os.path.exists(part_path):
                try:
                    os.remove(part_path)
                except OSError:
                    pass
    raise last_error if last_error else RuntimeError("Неизвестная ошибка загрузки")


def download_vk_photos(
    token_raw: str,
    url: str,
    download_path: str,
    progress_callback: Callable[[str, str, float | None, str], None],
    cancel_event: threading.Event | None = None
) -> str:
    """
    Скачивает фотографии из альбома VK в максимальном доступном качестве.
    Поддерживает отмену через cancel_event.
    Возвращает путь к папке с сохранёнными фото.
    """
    token = extract_token(token_raw)
    if not token:
        raise ValueError("Для фотографий необходим токен доступа")

    owner_id, album_id = extract_album_ids(url)
    if not owner_id:
        raise ValueError("Неверный формат ссылки на альбом VK")

    progress_callback("Подключение к ВКонтакте...", "working", None, "")

    try:
        vk = vk_api.VkApi(token=token).get_api()

        album_title = f"VK_Album_{owner_id}_{album_id}"
        try:
            if album_id not in ("profile", "wall", "saved"):
                info = vk.photos.getAlbums(owner_id=owner_id, album_ids=[album_id])
                if info.get("items"):
                    name = sanitize_filename(info["items"][0]["title"])
                    if name:
                        album_title = f"VK_{name}_{album_id}"
        except Exception:
            pass

        target_folder = os.path.join(download_path, album_title)
        os.makedirs(target_folder, exist_ok=True)

        all_items = []
        offset = 0
        per_page = 1000
        while True:
            if cancel_event and cancel_event.is_set():
                progress_callback("Загрузка отменена", "warning", None, "")
                raise DownloadCancelledError("Загрузка отменена пользователем")

            resp = vk.photos.get(
                owner_id=owner_id,
                album_id=album_id,
                count=per_page,
                offset=offset
            )
            chunk = resp.get("items", [])
            all_items.extend(chunk)
            if len(chunk) < per_page:
                break
            offset += per_page

        if not all_items:
            raise RuntimeError("Альбом пуст или закрыт настройками приватности")

        total = len(all_items)
        progress_callback(f"Найдено фото: {total}. Скачивание...", "working", 0.0, "0%")

        # Докачка: фото, уже лежащие в папке (по id), пропускаем
        already = existing_photo_ids(target_folder)

        jobs: list[tuple[int, str, str, str]] = []  # (номер, id, url, путь)
        failed: list[tuple[int, str, str]] = []     # (номер, url, причина)
        skipped = 0
        for i, photo in enumerate(all_items):
            photo_id = str(photo.get("id", i))
            best_size = get_best_photo_size(photo.get("sizes", []))
            if not best_size or "url" not in best_size:
                failed.append((i + 1, "", "нет ссылки на файл"))
            elif photo_id in already:
                skipped += 1
            else:
                url_i = best_size["url"]
                out_path = os.path.join(
                    target_folder, f"photo_{i + 1:04d}_{photo_id}.{photo_extension(url_i)}"
                )
                jobs.append((i + 1, photo_id, url_i, out_path))

        downloaded = 0
        done = skipped + len(failed)
        session = requests.Session()
        adapter = HTTPAdapter(pool_connections=PHOTO_WORKERS, pool_maxsize=PHOTO_WORKERS)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        def report() -> None:
            p = done / total
            progress_callback(f"Фото {done} из {total}", "working", p, f"{int(p * 100)}%")

        report()
        executor = ThreadPoolExecutor(max_workers=PHOTO_WORKERS)
        try:
            futures = {
                executor.submit(download_photo_file, session, url_i, out_path, cancel_event): (num, url_i)
                for num, _pid, url_i, out_path in jobs
            }
            for fut in as_completed(futures):
                num, url_i = futures[fut]
                try:
                    fut.result()
                    downloaded += 1
                except DownloadCancelledError:
                    pass
                except Exception as e:
                    failed.append((num, url_i, str(e)[:120]))
                    log.warning("VK фото #%s не скачано: %s", num, e)
                done += 1

                if cancel_event and cancel_event.is_set():
                    break
                report()
        finally:
            executor.shutdown(wait=True, cancel_futures=True)
            session.close()

        if cancel_event and cancel_event.is_set():
            progress_callback(
                f"Загрузка отменена (скачано {downloaded} из {total})", "warning", None, ""
            )
            raise DownloadCancelledError("Загрузка отменена пользователем")

        report_path = os.path.join(target_folder, FAILED_REPORT_NAME)
        if failed:
            failed.sort()
            with open(report_path, "w", encoding="utf-8") as f:
                f.write("Не удалось скачать (запустите ту же ссылку ещё раз — докачается только это):\n")
                for num, url_i, reason in failed:
                    f.write(f"#{num}: {reason}\n    {url_i}\n")
        elif os.path.exists(report_path):
            os.remove(report_path)

        if downloaded == 0 and skipped == 0:
            raise RuntimeError("Не удалось скачать ни одного фото. Проверьте интернет и повторите")

        parts = [f"скачано {downloaded}"]
        if skipped:
            parts.append(f"уже было {skipped}")
        if failed:
            parts.append(f"ошибок {len(failed)}, см. {FAILED_REPORT_NAME}")
        progress_callback(
            f"Готово: {total} фото ({', '.join(parts)})",
            "warning" if failed else "success",
            1.0,
            "100%"
        )
        return target_folder

    except DownloadCancelledError:
        raise
    except vk_api.exceptions.ApiError as e:
        codes = {
            5: "Недействительный или истекший токен VK.",
            15: "Альбом закрыт настройками приватности.",
            30: "Альбом закрыт настройками приватности.",
        }
        msg = codes.get(e.code, e.error.get("error_msg", str(e)))
        raise RuntimeError(f"Ошибка API: {msg}") from e
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError("Сетевая ошибка. Проверьте подключение к интернету") from e


def save_song_safely(song: Any, out_folder: str, overwrite: bool = False) -> str | None:
    """
    Сохраняет трек vkpymusic напрямую в целевую папку без изменения текущей рабочей директории (os.chdir).
    """
    song.to_safe()
    file_name = sanitize_filename(f"{song}.mp3")
    file_path = os.path.join(out_folder, file_name)

    if os.path.exists(file_path) and not overwrite:
        return file_path

    url = getattr(song, "url", None)
    if not url:
        return None

    if "index.m3u8" in url:
        if download_m3u8_as_mp3_pyav is not None:
            download_m3u8_as_mp3_pyav(url, file_path)
            return file_path
        else:
            raise RuntimeError("Модуль download_m3u8_as_mp3_pyav недоступен")
    else:
        r = requests.get(url, stream=True, timeout=30)
        r.raise_for_status()
        with open(file_path, "wb") as f:
            shutil.copyfileobj(r.raw, f)
        return file_path


def download_vk_music(
    token_raw: str,
    url: str,
    download_path: str,
    progress_callback: Callable[[str, str, float | None, str], None],
    cancel_event: threading.Event | None = None
) -> str:
    """
    Скачивает музыку из плейлиста или профиля VK с поддержкой до 1000 треков и отменой загрузки.
    Возвращает путь к папке с сохранёнными треками.
    """
    if not VKPYMUSIC_AVAILABLE or VkMusicService is None:
        raise RuntimeError("Установите vkpymusic: pip install vkpymusic")

    token = extract_token(token_raw)
    if not token:
        raise ValueError("Для скачивания музыки необходим токен (scope=audio)")

    target = extract_music_target(url)
    if target is None:
        raise ValueError("Не удалось распознать ссылку. Нужна ссылка на плейлист, песню (vk.com/audio…) "
                         "или профиль (vk.com/id…)")

    progress_callback("Подключение к VK Music API...", "working", None, "")

    try:
        service = VkMusicService(user_agent=VK_MUSIC_USER_AGENT, token=token)

        if target["type"] == "playlist":
            songs = service.get_songs_by_playlist_id(
                user_id=target["owner_id"],
                playlist_id=target["playlist_id"],
                access_key=target["access_key"],
                count=1000
            )
            folder_name = f"VK_Music_playlist_{target['playlist_id']}"
        elif target["type"] == "track":
            audio_id = f"{target['owner_id']}_{target['audio_id']}"
            if target["access_key"]:
                audio_id += f"_{target['access_key']}"
            songs = service.get_songs_by_id([audio_id])
            folder_name = "VK_Music_tracks"
        else:
            songs = service.get_songs_by_userid(
                user_id=target["user_id"],
                count=1000
            )
            folder_name = f"VK_Music_id{target['user_id']}"

        if not songs:
            raise RuntimeError("Плейлист пуст или недоступен для этого токена")

        total = len(songs)
        progress_callback(f"Найдено треков: {total}. Скачивание...", "working", 0.0, "0%")

        out_folder = os.path.join(download_path, folder_name)
        os.makedirs(out_folder, exist_ok=True)

        downloaded = 0
        errors = 0

        for i, song in enumerate(songs):
            if cancel_event and cancel_event.is_set():
                progress_callback(f"Загрузка отменена (скачано {downloaded} из {total})", "warning", None, "")
                raise DownloadCancelledError("Загрузка отменена пользователем")

            try:
                res = save_song_safely(song, out_folder)
                if res and os.path.exists(res):
                    downloaded += 1
                else:
                    errors += 1
            except Exception as e:
                errors += 1
                log.warning("VK трек %s не скачан: %s", getattr(song, "title", "?"), e)

            p = (i + 1) / total
            song_title = getattr(song, "title", "...") or "..."
            progress_callback(
                f"Трек {i + 1} из {total}: {song_title[:30]}",
                "working",
                p,
                f"{int(p * 100)}%"
            )

        if downloaded == 0 and total > 0:
            raise RuntimeError("Не удалось скачать ни одного трека. Возможно, токен не имеет прав audio.")

        status_text = f"Готово: {downloaded} из {total} треков"
        if errors > 0:
            status_text += f" ({errors} ошибок)"

        progress_callback(status_text, "success", 1.0, "100%")
        return out_folder

    except DownloadCancelledError:
        raise
    except Exception as e:
        err = str(e)
        if "token" in err.lower() or "auth" in err.lower():
            raise RuntimeError("Ошибка авторизации: получите новый токен с правами audio") from e
        raise
