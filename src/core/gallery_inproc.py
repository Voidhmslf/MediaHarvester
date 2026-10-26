"""gallery-dl внутри процесса приложения (Android: подпроцессов с Python там нет)."""
import io
import os
import sys
import threading
from typing import Callable

from src.utils.helpers import DownloadCancelledError

_lock = threading.Lock()  # gallery-dl хранит настройки и вывод в глобальном состоянии


class _Sink(io.TextIOBase):
    """Построчно принимает вывод gallery-dl; при отмене прерывает его исключением."""

    def __init__(self, lines: list[str], cancel_event: threading.Event | None):
        self._lines = lines
        self._cancel = cancel_event
        self._buf = ""

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        if self._cancel and self._cancel.is_set():
            raise DownloadCancelledError("Загрузка отменена пользователем")
        self._buf += text
        *done, self._buf = self._buf.split("\n")
        self._lines.extend(line.strip() for line in done if line.strip())
        return len(text)


def run_gallery_dl(args: list[str], stdout_lines: list[str], stderr_lines: list[str],
                   cancel_event: threading.Event | None = None) -> int:
    """Запускает `gallery-dl <args>` в этом процессе. Возвращает код возврата."""
    import gallery_dl

    out, err = _Sink(stdout_lines, cancel_event), _Sink(stderr_lines, cancel_event)
    with _lock:
        saved = sys.argv, sys.stdout, sys.stderr
        sys.argv, sys.stdout, sys.stderr = ["gallery-dl", *args], out, err
        try:
            return int(gallery_dl.main() or 0)
        except SystemExit as e:
            return e.code if isinstance(e.code, int) else (0 if e.code in (None, "") else 1)
        finally:
            sys.argv, sys.stdout, sys.stderr = saved
            # хвост без перевода строки (например, путь последнего файла)
            for sink, lines in ((out, stdout_lines), (err, stderr_lines)):
                if sink._buf.strip():
                    lines.append(sink._buf.strip())
