import re
import threading
from dataclasses import dataclass
from typing import Callable

from src.utils.errors import explain_error
from src.utils.helpers import DownloadCancelledError
from src.utils.logger import get_logger, redact

log = get_logger("queue")

# Статусы элемента очереди
PENDING = "pending"
WORKING = "working"
DONE = "done"
ERROR = "error"
CANCELLED = "cancelled"

# Что запускается при старте (завершённые пропускаются, ошибочные и отменённые — повторяются)
RUNNABLE = (PENDING, ERROR, CANCELLED)

_URL_TOKEN = re.compile(r"^(?:https?://|www\.|[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}/)\S+$", re.IGNORECASE)


@dataclass
class QueueItem:
    url: str
    label: str = ""
    status: str = PENDING
    message: str = ""    # коротко, что пошло не так (для списка и статуса)
    hint: str = ""       # что делать
    technical: str = ""  # исходная ошибка для отчёта
    folder: str = ""


def parse_urls(text: str) -> list[str]:
    """Достаёт ссылки из произвольного текста (по одной в строке, через пробелы или запятые), без дублей."""
    urls: list[str] = []
    for token in re.split(r"[\s,;]+", text):
        token = token.strip().rstrip(".)>\"'")
        if token and _URL_TOKEN.match(token) and token not in urls:
            urls.append(token)
    return urls


def run_queue(
    items: list[QueueItem],
    run_one: Callable[[QueueItem, int, int], str],
    cancel_event: threading.Event,
    on_change: Callable[[], None],
) -> dict[str, int]:
    """
    Последовательно выполняет элементы очереди. Ошибка одного элемента не останавливает остальные;
    отмена останавливает всю очередь (необработанные элементы остаются в статусе PENDING).
    run_one(item, номер, всего) -> путь к папке; исключение = ошибка элемента.
    """
    todo = [it for it in items if it.status in RUNNABLE]
    total = len(todo)
    for number, item in enumerate(todo, 1):
        if cancel_event.is_set():
            break
        item.status = WORKING
        item.message = item.hint = item.technical = ""
        log.info("[%s/%s] старт: %s", number, total, redact(item.url))
        on_change()
        try:
            item.folder = run_one(item, number, total)
            item.status = DONE
            log.info("[%s/%s] готово: %s", number, total, item.folder)
        except DownloadCancelledError:
            item.status = CANCELLED
            log.info("[%s/%s] отменено", number, total)
            on_change()
            break
        except Exception as e:
            info = explain_error(e)
            item.status = ERROR
            item.message, item.hint, item.technical = info.message, info.hint, info.technical
            log.error("[%s/%s] ошибка (%s): %s | %s", number, total, info.kind,
                      info.message, info.technical, exc_info=True)
        on_change()

    return {
        "total": total,
        "done": sum(1 for it in todo if it.status == DONE),
        "failed": sum(1 for it in todo if it.status == ERROR),
        "cancelled": sum(1 for it in todo if it.status == CANCELLED),
    }
