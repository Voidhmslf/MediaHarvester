"""
Загрузка одного файла по HTTP: временный .part, проверка полноты, повторы при сбоях сети
и запасные адреса (например, меньший размер фото, если крупный отвечает 404).
Используется загрузчиками VK и Instagram.
"""
import os
import threading
import time

import requests

from src.utils.helpers import DownloadCancelledError
from src.utils.logger import get_logger

log = get_logger("http_download")

PHOTO_RETRIES = 3
PERMANENT_HTTP_STATUSES = (403, 404, 410)  # повторять тот же адрес бессмысленно: сразу следующий вариант


def _download_one_url(
    session: requests.Session,
    url: str,
    out_path: str,
    cancel_event: threading.Event | None,
) -> None:
    """
    Скачивает один адрес во временный .part и атомарно переименовывает по завершении.
    Временные сбои повторяет до PHOTO_RETRIES раз с нарастающей паузой; ответы 403/404/410
    считает окончательными (повтор не поможет) и сразу бросает ошибку. Проверяет полноту по Content-Length.
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
        except requests.exceptions.HTTPError as e:
            last_error = e
            status = e.response.status_code if e.response is not None else None
            if status in PERMANENT_HTTP_STATUSES:
                raise
            if attempt < PHOTO_RETRIES - 1:
                time.sleep(1.5 * (attempt + 1))
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


def download_photo_file(
    session: requests.Session,
    url: str | list[str],
    out_path: str,
    cancel_event: threading.Event | None = None
) -> None:
    """
    Скачивает фото по одному адресу или по списку вариантов (от крупного к мелкому): если крупный вариант
    недоступен (например, 404), пробует следующий. Ошибка бросается, только когда не сработал ни один.
    """
    candidates = [url] if isinstance(url, str) else list(url)
    last_error: Exception | None = None
    for index, candidate in enumerate(candidates):
        try:
            _download_one_url(session, candidate, out_path, cancel_event)
            if index:
                log.info("Фото %s: крупный вариант недоступен, скачан вариант №%s", os.path.basename(out_path), index + 1)
            return
        except DownloadCancelledError:
            raise
        except Exception as e:
            last_error = e
    raise last_error if last_error else RuntimeError("Нет адресов для скачивания")
