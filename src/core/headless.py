"""
Загрузка без окна: общий код для командной строки (src/cli.py) и MCP-сервера (src/mcp_server.py).
Выбирает движок так же, как окно программы, и возвращает список скачанных файлов.
"""
import hashlib
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from src.config import QUALITY_PRESETS, VK_ANDROID_USER_AGENT, VK_MUSIC_USER_AGENT, SettingsManager
from src.core.router import detect_url_type, gallery_platform_name
from src.utils.errors import explain_error
from src.utils.helpers import DownloadCancelledError, get_app_data_dir
from src.utils.logger import get_logger, redact

log = get_logger("headless")

# Короткие названия качества для командной строки -> пункты списка в окне программы
QUALITY_ALIASES = {
    "best": QUALITY_PRESETS[0],
    "2160": "4K (2160p)",
    "1440": "2K (1440p)",
    "1080": "Full HD (1080p)",
    "720": "HD (720p)",
    "480": "SD (480p)",
    "360": "360p",
    "audio": "Только аудио (MP3)",
}

# Движки, которые можно выбрать вручную вместо автоопределения
ENGINES = ("auto", "video", "insta", "gallery", "vk_photos", "vk_music")
_ENGINE_ALIASES = {"video": "ytdlp"}

# Служебные файлы, которые движки оставляют во время работы
_TEMP_SUFFIXES = (".part", ".ytdl", ".temp", ".tmp")

StatusCallback = Callable[[str, str, float | None, str], None]


def explain(exc: BaseException) -> tuple[str, str]:
    """(сообщение, подсказка) для терминала и агента: вместо кнопки «Подробнее» окна — путь к журналу."""
    info = explain_error(exc)
    hint = info.hint
    if "«Подробнее»" in hint:
        from src.utils.logger import get_log_path
        hint = f"подробности в журнале {get_log_path()}"
    return info.message, hint


def quality_choice(quality: str) -> str:
    """'720', '720p', 'audio' -> пункт QUALITY_PRESETS. Неизвестное значение — ValueError."""
    key = (quality or "best").strip().lower().removesuffix("p")
    key = {"4k": "2160", "2k": "1440", "max": "best", "mp3": "audio"}.get(key, key)
    if key not in QUALITY_ALIASES:
        raise ValueError(f"Неизвестное качество «{quality}». Можно: {', '.join(QUALITY_ALIASES)}")
    return QUALITY_ALIASES[key]


@dataclass
class DownloadOptions:
    output_dir: str
    quality: str = "best"
    audio_format: str = "mp3"
    embed_cover: bool = False
    playlist: bool | None = None   # None — как решит автоопределение (плейлист SoundCloud, профиль TikTok)
    playlist_limit: int = 0
    subtitles: list[str] = field(default_factory=list)
    cookies_path: str = ""
    cookies_browser: str = ""
    engine: str = "auto"


@dataclass
class ItemResult:
    url: str
    ok: bool = False
    platform: str = ""
    title: str = ""
    files: list[str] = field(default_factory=list)
    error: str = ""
    hint: str = ""
    cancelled: bool = False

    def as_dict(self) -> dict:
        data = {"url": self.url, "ok": self.ok, "platform": self.platform, "files": self.files}
        if self.title:
            data["title"] = self.title
        if self.error:
            data["error"] = self.error
        if self.hint:
            data["hint"] = self.hint
        if self.cancelled:
            data["cancelled"] = True
        return data


def options_from_settings(settings: SettingsManager, output_dir: str = "") -> DownloadOptions:
    """Папка, cookies.txt и браузер для cookies — те же, что выбраны в окне программы."""
    return DownloadOptions(
        output_dir=output_dir or settings.download_path,
        cookies_path=settings.cookies_path,
        cookies_browser=settings.get("cookies_browser", "") or "",
    )


def _snapshot(folder: str) -> dict[str, int]:
    files: dict[str, int] = {}
    for base, _dirs, names in os.walk(folder):
        for name in names:
            path = os.path.join(base, name)
            try:
                files[path] = os.stat(path).st_mtime_ns
            except OSError:
                pass
    return files


def _changed_files(folder: str, before: dict[str, int]) -> list[str]:
    after = _snapshot(folder)
    return sorted(p for p, mtime in after.items()
                  if before.get(p) != mtime and not p.lower().endswith(_TEMP_SUFFIXES))


def download_url(
    url: str,
    opts: DownloadOptions,
    settings: SettingsManager,
    status: StatusCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> ItemResult:
    """Скачивает одну ссылку. Ошибки не бросает (кроме отмены), а возвращает в ItemResult с подсказкой."""
    from src.core.gallery_engine import download_gallery
    from src.core.insta_engine import download_instagram
    from src.core.vk_engine import download_vk_music, download_vk_photos
    from src.core.ytdlp_engine import download_video

    cb: StatusCallback = status or (lambda *_args: None)
    cancel_event = cancel_event or threading.Event()
    detected = detect_url_type(url)
    result = ItemResult(url=url, platform=detected["platform"])
    engine = detected["engine"] if opts.engine == "auto" else _ENGINE_ALIASES.get(opts.engine, opts.engine)
    folder = os.path.abspath(opts.output_dir)
    os.makedirs(folder, exist_ok=True)

    reported: list[str] = []
    before = _snapshot(folder)
    started = time.time()
    log.info("headless: %s (%s), движок %s, папка %s", redact(url), detected["label"], engine, folder)
    try:
        if engine == "insta":
            download_instagram(url=url, download_path=folder, cookies_path=opts.cookies_path,
                               cookies_browser=opts.cookies_browser, status_callback=cb,
                               cancel_event=cancel_event)
        elif engine == "gallery":
            download_gallery(url=url, download_path=folder,
                             platform_name=gallery_platform_name(url) or "Gallery",
                             cookies_path=opts.cookies_path, cookies_browser=opts.cookies_browser,
                             status_callback=cb, cancel_event=cancel_event,
                             listing=bool(detected.get("listing")))
        elif engine == "vk_photos":
            token = settings.get_vk_token("photos")
            if not token:
                raise RuntimeError("Для фото ВКонтакте нужен вход: войдите в окне программы (блок «ВКонтакте»)")
            download_vk_photos(token_raw=token, url=url, download_path=folder,
                               progress_callback=cb, cancel_event=cancel_event)
        elif engine == "vk_music":
            android = settings.get("music_client", "kate") == "android"
            token = settings.get_vk_token("music_android" if android else "music")
            if not token:
                raise RuntimeError("Для музыки ВКонтакте нужен вход: войдите в окне программы (режим «Музыка ВК»)")
            download_vk_music(token_raw=token, url=url, download_path=folder,
                              progress_callback=cb, cancel_event=cancel_event,
                              user_agent=VK_ANDROID_USER_AGENT if android else VK_MUSIC_USER_AGENT)
        else:
            playlist = bool(detected.get("playlist")) if opts.playlist is None else opts.playlist
            result.title = download_video(
                url=url, download_path=folder, quality_choice=quality_choice(opts.quality),
                progress_callback=cb, cookies_path=opts.cookies_path,
                cookies_browser=opts.cookies_browser, cancel_event=cancel_event,
                allow_playlist=playlist, playlist_limit=opts.playlist_limit if playlist else 0,
                audio_codec=opts.audio_format, embed_cover=opts.embed_cover,
                subtitle_langs=opts.subtitles or None, on_file=reported.append)
        result.ok = True
    except DownloadCancelledError:
        result.cancelled = True
        result.error = "Загрузка отменена"
    except Exception as e:
        result.error, result.hint = explain(e)
        log.error("headless: ошибка %s: %s", redact(url), result.error, exc_info=True)

    # yt-dlp сообщает готовые файлы сам (и те, что уже были скачаны); остальные движки — по изменениям в папке
    # (если yt-dlp файлы назвал, из изменений берём только их спутники — субтитры, обложки — а не чужие файлы)
    files = list(dict.fromkeys(os.path.abspath(p) for p in reported if os.path.isfile(p)))
    stems = tuple(os.path.splitext(p)[0] + "." for p in files)
    for path in _changed_files(folder, before):
        if path not in files and (not stems or path.startswith(stems)):
            files.append(path)
    result.files = files
    log.info("headless: %s, файлов %s за %.1f с", "готово" if result.ok else "не вышло",
             len(files), time.time() - started)
    return result


def cache_dir_for(url: str) -> str:
    digest = hashlib.sha1(url.strip().encode("utf-8")).hexdigest()[:16]
    return os.path.join(get_app_data_dir(), "cache", digest)


def local_media(
    source: str,
    settings: SettingsManager,
    status: StatusCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> str:
    """
    Путь к файлу для кадров. Ссылка скачивается в 480p в кэш программы (повторно не качается),
    чтобы кадры можно было брать, не засоряя папку загрузок.
    """
    from src.core.media_tools import is_url, pick_media_file

    if not is_url(source):
        if not os.path.isfile(source):
            raise RuntimeError(f"Файл не найден: {source}")
        return os.path.abspath(source)
    folder = cache_dir_for(source)
    cached = pick_media_file(sorted(p for p, _ in _snapshot(folder).items())) if os.path.isdir(folder) else None
    if cached:
        return cached
    opts = options_from_settings(settings, folder)
    opts.quality, opts.playlist = "480", False
    result = download_url(source, opts, settings, status, cancel_event)
    if result.cancelled:
        raise DownloadCancelledError(result.error)
    media = pick_media_file(result.files)
    if not media:
        raise RuntimeError(result.error or "По ссылке не нашлось ни видео, ни картинки")
    return media
