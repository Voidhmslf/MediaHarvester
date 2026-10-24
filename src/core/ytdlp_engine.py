import os
import threading
from typing import Callable, Any
import yt_dlp
from src.utils.helpers import FFMPEG_PATH, DownloadCancelledError
from src.core.router import gallery_platform_name


def get_video_format_spec(choice: str) -> tuple[str, list[dict[str, Any]]]:
    """Формирует спецификацию формата yt-dlp и пост-процессоры по выбранному качеству."""
    postprocessors: list[dict[str, Any]] = []
    if "Только аудио" in choice:
        fmt = "bestaudio/best"
        if FFMPEG_PATH:
            postprocessors.append({
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",  # Максимальное качество MP3 (320 kbps)
            })
            postprocessors.append({
                "key": "FFmpegMetadata",
                "add_metadata": True,       # Запись тегов исполнителя, трека и альбома
            })
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
    return fmt, postprocessors


def probe_video_quality(url: str, cookies_path: str = "") -> tuple[list[int], str]:
    """
    Получает список доступных разрешений по высоте и заголовок видео без его скачивания.
    Возвращает (список_высот, заголовок).
    """
    opts: dict[str, Any] = {
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    if FFMPEG_PATH:
        opts["ffmpeg_location"] = FFMPEG_PATH

    if cookies_path and os.path.isfile(cookies_path):
        opts["cookiefile"] = cookies_path

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
    title = info.get("title", "") if info else ""
    return heights, title


def download_video(
    url: str,
    download_path: str,
    quality_choice: str,
    progress_callback: Callable[[str, str, float | None, str], None],
    cookies_path: str = "",
    cancel_event: threading.Event | None = None,
    allow_playlist: bool = False,
    allow_gallery_fallback: bool = True
) -> str:
    """
    Скачивает видео или аудио с помощью yt-dlp.
    Поддерживает отмену через cancel_event, плейлисты и cookies.txt.
    """
    def hook(d: dict[str, Any]) -> None:
        if cancel_event and cancel_event.is_set():
            raise DownloadCancelledError("Загрузка отменена пользователем")

        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            dl = d.get("downloaded_bytes", 0)
            if total > 0:
                p = dl / total
                progress_callback(
                    f"Загрузка: {int(p * 100)}%",
                    "working",
                    p,
                    f"{int(p * 100)}%"
                )
            else:
                progress_callback("Загрузка медиапотока...", "working", None, "")
        elif d.get("status") == "finished":
            progress_callback("Обработка и объединение дорожек...", "working", 0.98, "98%")

    fmt, postprocessors = get_video_format_spec(quality_choice)

    if allow_playlist:
        outtmpl = os.path.join(download_path, "%(playlist_title,title)s", "%(title)s.%(ext)s")
        noplaylist = False
    else:
        outtmpl = os.path.join(download_path, "%(title)s.%(ext)s")
        noplaylist = True

    opts: dict[str, Any] = {
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": noplaylist,
        "progress_hooks": [hook],
        "format": fmt,
        "windowsfilenames": True,
    }
    if FFMPEG_PATH:
        opts["ffmpeg_location"] = FFMPEG_PATH
    if postprocessors:
        opts["postprocessors"] = postprocessors
    if cookies_path and os.path.isfile(cookies_path):
        opts["cookiefile"] = cookies_path

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
            from src.core.gallery_engine import download_gallery
            download_gallery(
                url=url,
                download_path=download_path,
                platform_name=platform,
                cookies_path=cookies_path,
                status_callback=progress_callback,
                cancel_event=cancel_event,
                ytdlp_fallback=False,  # иначе gallery-dl вернёт нас сюда же
            )
            return f"{platform} Photo / Gallery"

        if "Video unavailable" in raw_msg or "This video is unavailable" in raw_msg:
            err_text = "Видео недоступно или удалено"
        elif "Sign in to confirm your age" in raw_msg or "confirm you're not a bot" in raw_msg.lower():
            err_text = "Требуется авторизация (18+ / бот-чек): укажите cookies.txt в настройках"
        elif "Private" in raw_msg or "Sign in" in raw_msg or "login" in raw_msg.lower():
            err_text = "Видео приватное или требует авторизации (укажите cookies.txt)"
        elif "Requested format is not available" in raw_msg:
            err_text = "Выбранное качество недоступно для этого видео"
        else:
            err_text = f"Ошибка: {clean_msg[:50]}"
        raise RuntimeError(err_text) from e
