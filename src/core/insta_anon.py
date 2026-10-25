"""
Посты и карусели Instagram без входа в аккаунт.

Instagram отдаёт данные публичного поста анонимному посетителю (так же работают сайты-загрузчики): yt-dlp
умеет получить их, но оставляет только видео. Здесь тот же анонимный запрос используется повторно:
перехватывается разобранный ответ (product_info), из него берутся фото и видео максимального размера
и скачиваются напрямую с CDN. Если Instagram отказал (закрытый аккаунт, лимит анонимных запросов), вызывающий
код переходит на gallery-dl с cookies.
"""
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

import requests
import yt_dlp
from yt_dlp.extractor.instagram import InstagramIE
from yt_dlp.utils import ExtractorError

from src.core.http_download import download_photo_file
from src.utils.helpers import DownloadCancelledError
from src.utils.logger import get_logger

log = get_logger("insta_anon")

FOLDER_NAME = "Instagram_Downloads"
WORKERS = 4
_POST_URL = re.compile(r"instagram\.com/(?:[^/]+/)?p/([A-Za-z0-9_-]+)", re.IGNORECASE)


class AnonymousAccessError(RuntimeError):
    """Instagram не отдал пост без входа (закрытый аккаунт, лимит запросов, изменился формат)."""


@dataclass
class MediaItem:
    url: str
    is_video: bool
    fallbacks: tuple[str, ...] = ()

    @property
    def extension(self) -> str:
        ext = os.path.splitext(urlparse(self.url).path)[1].lstrip(".").lower()
        if ext in ("jpg", "jpeg", "png", "webp", "mp4", "mov", "webm"):
            return ext
        return "mp4" if self.is_video else "jpg"


def is_post_url(url: str) -> bool:
    """Ссылка на пост или карусель (/p/<код>/), а не на Reel, Stories или профиль."""
    return bool(_POST_URL.search(url or ""))


def shortcode(url: str) -> str:
    match = _POST_URL.search(url or "")
    return match.group(1) if match else "post"


class _CapturingInstagramIE(InstagramIE):
    """Экстрактор yt-dlp, запоминающий данные поста до того, как из них отбросят фото."""
    product: dict[str, Any] | None = None

    def _extract_product(self, product_info, *args, **kwargs):
        if self.product is None:
            self.product = product_info
        return super()._extract_product(product_info, *args, **kwargs)


def fetch_product(url: str, extractor_cls=_CapturingInstagramIE) -> dict[str, Any]:
    """Анонимно получает данные поста у Instagram через логику yt-dlp (может бросить AnonymousAccessError)."""
    ydl = yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True})
    extractor = extractor_cls()
    extractor.set_downloader(ydl)
    try:
        extractor.extract(url)
    except ExtractorError as e:
        # «There is no video in this post» — ожидаемо для фото: данные уже перехвачены
        if getattr(extractor, "product", None) is None:
            raise AnonymousAccessError(str(e).split("] ", 1)[-1][:160]) from e
    except Exception as e:
        raise AnonymousAccessError(f"{type(e).__name__}: {str(e)[:120]}") from e
    product = getattr(extractor, "product", None)
    if not product:
        raise AnonymousAccessError("Instagram не вернул данные поста")
    return product


def _area(candidate: dict[str, Any]) -> int:
    return (candidate.get("width") or 0) * (candidate.get("height") or 0)


def _ranked(candidates: list[dict[str, Any]]) -> list[str]:
    """Адреса от лучшего к худшему: по площади; если размеров нет — в порядке выдачи."""
    urls = [c["url"] for c in sorted(candidates, key=_area, reverse=True) if c.get("url")]
    return list(dict.fromkeys(urls))


def extract_media(product: dict[str, Any]) -> list[MediaItem]:
    """Фото и видео поста (для карусели — всех слайдов) в максимальном размере."""
    items: list[MediaItem] = []
    for node in product.get("carousel_media") or [product]:
        videos = _ranked(node.get("video_versions") or [])
        if videos:
            items.append(MediaItem(videos[0], True, tuple(videos[1:])))
            continue
        images = _ranked(((node.get("image_versions2") or {}).get("candidates")) or [])
        if not images and node.get("display_uri"):
            images = [node["display_uri"]]
        if images:
            items.append(MediaItem(images[0], False, tuple(images[1:4])))
    return items


def download_post_anonymously(
    url: str,
    download_path: str,
    status_callback: Callable[[str, str, float | None, str], None] | None = None,
    cancel_event: threading.Event | None = None,
    fetch: Callable[[str], dict[str, Any]] = fetch_product,
) -> str:
    """
    Скачивает фото и видео публичного поста без входа. Возвращает папку Instagram_Downloads.
    Бросает AnonymousAccessError, если пост анонимно недоступен, чтобы вызывающий код попробовал другой путь.
    """
    def notify(text: str, state: str = "working", progress: float | None = None, percent: str = "") -> None:
        if status_callback:
            status_callback(text, state, progress, percent)

    notify("Instagram: получаю данные поста без входа...")
    product = fetch(url)
    media = extract_media(product)
    if not media:
        raise AnonymousAccessError("В посте не нашлось фото или видео")

    code = product.get("code") or shortcode(url)
    folder = os.path.join(download_path, FOLDER_NAME)
    os.makedirs(folder, exist_ok=True)
    total = len(media)
    log.info("Пост %s: найдено файлов %s (анонимно)", code, total)
    notify(f"Найдено файлов: {total}. Скачивание...", "working", 0.0, "0%")

    session = requests.Session()
    failed = 0
    done = 0
    executor = ThreadPoolExecutor(max_workers=min(WORKERS, total))
    try:
        futures = {}
        for index, item in enumerate(media, 1):
            out_path = os.path.join(folder, f"instagram_{code}_{index:02d}.{item.extension}")
            if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                done += 1
                continue
            futures[executor.submit(download_photo_file, session, [item.url, *item.fallbacks], out_path,
                                    cancel_event)] = index
        for future in as_completed(futures):
            try:
                future.result()
            except DownloadCancelledError:
                pass
            except Exception as e:
                failed += 1
                log.warning("Instagram %s: файл #%s не скачан: %s", code, futures[future], e)
            done += 1
            if cancel_event and cancel_event.is_set():
                break
            progress = done / total
            notify(f"Файл {done} из {total}", "working", progress, f"{int(progress * 100)}%")
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
        session.close()

    if cancel_event and cancel_event.is_set():
        notify("Загрузка из Instagram отменена", "warning")
        raise DownloadCancelledError("Загрузка отменена пользователем")
    if failed == total:
        raise AnonymousAccessError("Файлы поста не скачались")

    if failed:
        notify(f"Готово: скачано {total - failed} из {total} (ошибок {failed})", "warning", 1.0, "100%")
    else:
        notify(f"Готово: скачано файлов: {total}", "success", 1.0, "100%")
    return folder
