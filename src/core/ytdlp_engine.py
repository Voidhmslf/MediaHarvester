import os
import re
import shutil
import tempfile
import threading
from typing import Callable, Any
import yt_dlp
from src.utils.helpers import FFMPEG_PATH, DownloadCancelledError
from src.core.router import gallery_platform_name
from src.utils import browser_cookies
from src.utils.logger import get_logger

log = get_logger("ytdlp")


AUDIO_CODECS = ("mp3", "m4a", "opus")


def get_video_format_spec(choice: str, audio_codec: str = "mp3",
                          embed_cover: bool = False) -> tuple[str, list[dict[str, Any]]]:
    """
    Формирует спецификацию формата yt-dlp и пост-процессоры по выбранному качеству.
    Для «Только аудио»: audio_codec — mp3 (320 кбит/с), m4a или opus (без лишней перекодировки),
    embed_cover — вшить обложку в файл.
    """
    postprocessors: list[dict[str, Any]] = []
    if "Только аудио" in choice:
        fmt = "bestaudio/best"
        if FFMPEG_PATH:
            codec = audio_codec if audio_codec in AUDIO_CODECS else "mp3"
            extract: dict[str, Any] = {"key": "FFmpegExtractAudio", "preferredcodec": codec}
            if codec == "mp3":
                extract["preferredquality"] = "320"  # Максимальное качество MP3 (320 kbps)
            if embed_cover:
                # Обложка скачивается и переводится в jpg до обработки звука, вшивается в самом конце
                postprocessors.append({"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"})
            postprocessors.append(extract)
            postprocessors.append({
                "key": "FFmpegMetadata",
                "add_metadata": True,       # Запись тегов исполнителя, трека и альбома
            })
            if embed_cover:
                postprocessors.append({"key": "EmbedThumbnail", "already_have_thumbnail": False})
    elif "2160p" in choice or "4K" in choice:
        fmt = "bestvideo[height<=2160]+bestaudio/best[height<=2160]/best"
    elif "1440p" in choice or "2K" in choice:
        fmt = "bestvideo[height<=1440]+bestaudio/best[height<=1440]/best"
    elif "1080p" in choice:
        fmt = "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"
    elif "720p" in choice:
        fmt = "bestvideo[height<=720]+bestaudio/best[height<=720]/best"
    elif "480p" in choice:
        fmt = "bestvideo[height<=480]+bestaudio/best[height<=480]/best"
    elif "360p" in choice:
        fmt = "bestvideo[height<=360]+bestaudio/best[height<=360]/best"
    else:
        fmt = "bestvideo+bestaudio/best"
    if not FFMPEG_PATH and "+" in fmt:
        # Без FFmpeg раздельные дорожки не склеить: берём готовые файлы (видео со звуком) нужной высоты
        limit = re.search(r"height<=(\d+)", fmt)
        fmt = f"best[height<={limit.group(1)}]/best" if limit else "best"
    return fmt, postprocessors


def _android_opts(opts: dict[str, Any]) -> None:
    """
    Без FFmpeg (Android) нужны готовые файлы со звуком, а YouTube по умолчанию отдаёт только раздельные дорожки.
    Клиент android_vr даёт обычный mp4 (format 18) без JavaScript-рантайма.
    """
    if not FFMPEG_PATH:
        opts["extractor_args"] = {"youtube": {"player_client": ["android_vr", "default"]}}


def needs_thumbnail(postprocessors: list[dict[str, Any]]) -> bool:
    """Нужно ли скачивать обложку (есть шаг вшивания)."""
    return any(p.get("key") == "EmbedThumbnail" for p in postprocessors)


def _format_speed(speed: float | None) -> str:
    if not speed or speed <= 0:
        return ""
    if speed >= 1024 * 1024:
        return f"{speed / 1024 / 1024:.1f} МБ/с".replace(".", ",")
    return f"{speed / 1024:.0f} КБ/с"


def _format_eta(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return ""
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def progress_details(d: dict[str, Any]) -> str:
    """« · 3,1 МБ/с · осталось 1:20» для строки состояния (пусто, если yt-dlp ещё не знает скорости)."""
    parts = []
    speed = _format_speed(d.get("speed"))
    if speed:
        parts.append(speed)
    eta = _format_eta(d.get("eta"))
    if eta:
        parts.append(f"осталось {eta}")
    return "".join(f" · {p}" for p in parts)


def _apply_cookies(opts: dict[str, Any], cookies_path: str, cookies_browser: str) -> None:
    """Файл cookies.txt в приоритете; иначе cookies читаются из выбранного браузера."""
    if cookies_path and os.path.isfile(cookies_path):
        opts["cookiefile"] = cookies_path
    else:
        from_browser = browser_cookies.ytdlp_option(cookies_browser)
        if from_browser:
            opts["cookiesfrombrowser"] = from_browser


def probe_media(url: str, cookies_path: str = "", cookies_browser: str = "") -> dict[str, Any]:
    """
    Сведения о ссылке без скачивания: заголовок, обложка, автор, длительность и доступные высоты видео.
    Для плейлистов и каналов берётся только их заголовок (без разбора каждого ролика).
    """
    opts: dict[str, Any] = {
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "socket_timeout": 20,
    }
    if FFMPEG_PATH:
        opts["ffmpeg_location"] = FFMPEG_PATH

    _apply_cookies(opts, cookies_path, cookies_browser)
    _android_opts(opts)

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    formats = info.get("formats", []) if info else []
    # Фильтруем только полноценные видеодорожки (исключаем раскадровки-storyboard и аудиодорожки)
    video_formats = [
        f for f in formats
        if f.get("height")
        and f.get("vcodec") != "none"
        and not f.get("format_id", "").startswith(("sb", "storyboard"))
    ]
    heights = sorted(list(set(f.get("height") for f in video_formats if f.get("height"))), reverse=True)
    info = info or {}
    thumbnail = info.get("thumbnail") or ""
    if not thumbnail and info.get("thumbnails"):
        thumbnail = (info["thumbnails"][-1] or {}).get("url", "")
    return {
        "title": info.get("title", "") or "",
        "thumbnail": thumbnail,
        "uploader": info.get("uploader") or info.get("channel") or "",
        "duration": info.get("duration") or 0,
        "heights": heights,
        "playlist": info.get("_type") == "playlist",
        "playlist_count": info.get("playlist_count") or len(info.get("entries") or []),
    }


def probe_video_quality(url: str, cookies_path: str = "", cookies_browser: str = "") -> tuple[list[int], str]:
    """
    Получает список доступных разрешений по высоте и заголовок видео без его скачивания.
    Возвращает (список_высот, заголовок).
    """
    info = probe_media(url, cookies_path, cookies_browser)
    return info["heights"], info["title"]


def download_video(
    url: str,
    download_path: str,
    quality_choice: str,
    progress_callback: Callable[[str, str, float | None, str], None],
    cookies_path: str = "",
    cancel_event: threading.Event | None = None,
    allow_playlist: bool = False,
    allow_gallery_fallback: bool = True,
    cookies_browser: str = "",
    playlist_limit: int = 0,
    audio_codec: str = "mp3",
    embed_cover: bool = False,
    subtitle_langs: list[str] | None = None,
    on_file: Callable[[str], None] | None = None,
) -> str:
    """
    Скачивает видео или аудио с помощью yt-dlp.
    Поддерживает отмену через cancel_event, плейлисты (playlist_limit > 0 — только первые N видео) и cookies.txt.
    on_file получает путь к каждому готовому файлу (после склейки и конвертации), в том числе уже скачанному раньше.
    """
    def hook(d: dict[str, Any]) -> None:
        if cancel_event and cancel_event.is_set():
            raise DownloadCancelledError("Загрузка отменена пользователем")

        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            dl = d.get("downloaded_bytes", 0)
            entry = d.get("info_dict") or {}
            number, count = entry.get("playlist_index"), entry.get("n_entries")
            which = f"Видео {number} из {count}: " if number and count and count > 1 else ""
            if total > 0:
                p = dl / total
                progress_callback(
                    f"{which}Загрузка: {int(p * 100)}%{progress_details(d)}",
                    "working",
                    p,
                    f"{int(p * 100)}%"
                )
            else:
                progress_callback(f"{which}Загрузка медиапотока...", "working", None, "")
        elif d.get("status") == "finished":
            progress_callback("Обработка и объединение дорожек...", "working", 0.98, "98%")

    fmt, postprocessors = get_video_format_spec(quality_choice, audio_codec, embed_cover)

    # Звук качается в свою временную папку, а готовый файл сразу переносится на место. Иначе yt-dlp
    # принимает лежащее рядом видео с тем же названием («Ролик.webm») за уже скачанную звуковую дорожку,
    # делает из него mp3 и удаляет само видео.
    audio_only = "Только аудио" in quality_choice
    work_dir = download_path
    if audio_only:
        os.makedirs(download_path, exist_ok=True)
        work_dir = tempfile.mkdtemp(prefix=".mediaharvester-", dir=download_path)

    def finished(path: str) -> None:
        if audio_only and os.path.isfile(path):
            dest = os.path.join(download_path, os.path.relpath(path, work_dir))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            os.replace(path, dest)
            path = dest
        if on_file:
            on_file(path)

    if allow_playlist:
        outtmpl = os.path.join(work_dir, "%(playlist_title,title)s", "%(title)s.%(ext)s")
        noplaylist = False
    else:
        outtmpl = os.path.join(work_dir, "%(title)s.%(ext)s")
        noplaylist = True

    opts: dict[str, Any] = {
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": noplaylist,
        "progress_hooks": [hook],
        "noprogress": True,  # ход загрузки показывает hook; иначе yt-dlp печатает его в консоль
        "format": fmt,
        "windowsfilenames": True,
    }
    if allow_playlist and playlist_limit > 0:
        opts["playlistend"] = playlist_limit
    if needs_thumbnail(postprocessors):
        opts["writethumbnail"] = True
    if subtitle_langs and "Только аудио" not in quality_choice:
        # Субтитры отдельными .srt рядом с видео: сначала настоящие, при их отсутствии — автоматические
        opts["writesubtitles"] = True
        opts["writeautomaticsub"] = True
        opts["subtitleslangs"] = subtitle_langs
        opts["subtitlesformat"] = "srt/best"
        if FFMPEG_PATH:
            postprocessors = [*postprocessors, {"key": "FFmpegSubtitlesConvertor", "format": "srt"}]
    if FFMPEG_PATH:
        opts["ffmpeg_location"] = FFMPEG_PATH
    if postprocessors:
        opts["postprocessors"] = postprocessors
    opts["post_hooks"] = [finished]
    _apply_cookies(opts, cookies_path, cookies_browser)
    _android_opts(opts)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
        title = info.get("title", "медиа") if info else "медиа"
        return title
    except DownloadCancelledError:
        progress_callback("Загрузка отменена", "warning", None, "")
        raise
    except Exception as e:
        raw_msg = str(e)
        clean_msg = raw_msg
        if "ERROR:" in clean_msg:
            clean_msg = clean_msg.split("ERROR:")[-1].strip()

        # Автоматический перехват фото/каруселей, попавших в yt-dlp (Instagram, X, TikTok, Reddit...)
        platform = gallery_platform_name(url) if allow_gallery_fallback else None
        no_video = any(phrase in raw_msg.lower() for phrase in (
            "no video formats found",
            "there is no video in this post",
            "no video",
            "is not a video"
        ))
        auth_error = any(phrase in raw_msg.lower() for phrase in (
            "private", "sign in", "login", "confirm your age", "not available in your country",
        ))
        # Instagram переключаем только при явном «нет видео»; для остальных — при любой не-авторизационной ошибке
        if platform and (no_video if platform == "Instagram" else not auth_error):
            progress_callback(f"Это не видео {platform}. Переключение на движок галереи...", "working", None, "")
            if platform == "Instagram":
                from src.core.insta_engine import download_instagram
                download_instagram(
                    url=url,
                    download_path=download_path,
                    cookies_path=cookies_path,
                    cookies_browser=cookies_browser,
                    status_callback=progress_callback,
                    cancel_event=cancel_event,
                )
            else:
                from src.core.gallery_engine import download_gallery
                download_gallery(
                    url=url,
                    download_path=download_path,
                    platform_name=platform,
                    cookies_path=cookies_path,
                    cookies_browser=cookies_browser,
                    status_callback=progress_callback,
                    cancel_event=cancel_event,
                    ytdlp_fallback=False,  # иначе gallery-dl вернёт нас сюда же
                )
            return f"{platform} Photo / Gallery"

        # Человекочитаемое объяснение строится выше по стеку (utils.errors.explain_error)
        log.warning("yt-dlp: ошибка загрузки %s: %s", url, raw_msg)
        raise RuntimeError(clean_msg) from e
    finally:
        # Готовые файлы уже перенесены; остались только недокачанные части
        if audio_only:
            shutil.rmtree(work_dir, ignore_errors=True)
