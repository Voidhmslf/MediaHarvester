import os
import threading
from typing import Callable
from src.core.gallery_engine import download_gallery
from src.core.insta_anon import AnonymousAccessError, download_post_anonymously, is_post_url
from src.utils import browser_cookies
from src.utils.logger import get_logger

log = get_logger("insta")


def download_instagram(
    url: str,
    download_path: str,
    cookies_path: str = "",
    cookies_browser: str = "",
    status_callback: Callable[[str, str, float | None, str], None] | None = None,
    cancel_event: threading.Event | None = None
) -> str:
    """
    Скачивает посты, карусели, фото, Reels и Stories из Instagram.
    Публичные посты и карусели сначала пробуются без входа (анонимный запрос, как у сайтов-загрузчиков),
    если cookies не заданы; всё остальное и запасной путь — gallery-dl с автоматическим fallback на yt-dlp для Reels / IGTV.
    Возвращает путь к папке с сохранёнными медиа.
    """
    has_login = bool(cookies_path and os.path.isfile(cookies_path)) or bool(browser_cookies.resolve(cookies_browser))
    if is_post_url(url) and not has_login:
        try:
            return download_post_anonymously(url, download_path, status_callback, cancel_event)
        except AnonymousAccessError as e:
            log.info("Анонимно не вышло (%s), пробуем gallery-dl", e)
            if status_callback:
                status_callback("Без входа не получилось, пробую другой способ...", "working", None, "")
    is_reel_or_video = any(p in url.lower() for p in ("/reel/", "/reels/", "/tv/"))
    return download_gallery(
        url=url,
        download_path=download_path,
        platform_name="Instagram",
        cookies_path=cookies_path,
        cookies_browser=cookies_browser,
        status_callback=status_callback,
        cancel_event=cancel_event,
        ytdlp_fallback=is_reel_or_video,
    )
