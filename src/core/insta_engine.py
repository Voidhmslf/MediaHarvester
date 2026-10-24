import threading
from typing import Callable
from src.core.gallery_engine import download_gallery


def download_instagram(
    url: str,
    download_path: str,
    cookies_path: str = "",
    status_callback: Callable[[str, str, float | None, str], None] | None = None,
    cancel_event: threading.Event | None = None
) -> str:
    """
    Скачивает посты, карусели, фото, Reels и Stories из Instagram через gallery-dl
    с автоматическим fallback на yt-dlp для Reels / IGTV.
    Возвращает путь к папке с сохранёнными медиа.
    """
    is_reel_or_video = any(p in url.lower() for p in ("/reel/", "/reels/", "/tv/"))
    return download_gallery(
        url=url,
        download_path=download_path,
        platform_name="Instagram",
        cookies_path=cookies_path,
        status_callback=status_callback,
        cancel_event=cancel_event,
        ytdlp_fallback=is_reel_or_video,
    )
