"""
Файловый лог приложения: %LOCALAPPDATA%\\MediaHarvester\\logs\\mediaharvester.log (ротация 1 МБ x 3).
Токены, ключи в ссылках и зарегистрированные секреты (токен VK) маскируются перед записью.
"""
import logging
import os
import platform
import re
import sys
import threading
from logging.handlers import RotatingFileHandler

from src.utils.helpers import get_app_data_dir

LOGGER_NAME = "mediaharvester"
LOG_FILE_NAME = "mediaharvester.log"

_SECRET_PARAM = re.compile(
    r"(?i)\b(access_token|token|api_key|apikey|password|passwd|secret|sig|signature|key)=([^&\s\"']+)"
)
_secrets: set[str] = set()
_configured = False


def get_log_dir() -> str:
    path = os.path.join(get_app_data_dir(), "logs")
    os.makedirs(path, exist_ok=True)
    return path


def get_log_path() -> str:
    return os.path.join(get_log_dir(), LOG_FILE_NAME)


def register_secret(value: str) -> None:
    """Добавляет значение (например, токен VK), которое нельзя писать в лог и отчёты."""
    value = (value or "").strip()
    if len(value) >= 8:
        _secrets.add(value)


def redact(text: str) -> str:
    """Маскирует секреты в произвольном тексте."""
    if not text:
        return text
    for secret in _secrets:
        text = text.replace(secret, "***")
    return _SECRET_PARAM.sub(lambda m: f"{m.group(1)}=***", text)


class _RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def get_logger(name: str = "") -> logging.Logger:
    """Логгер приложения (дочерний, если указано имя: get_logger('ytdlp'))."""
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)


def setup_logging() -> logging.Logger:
    """Настраивает файловый лог и перехват необработанных исключений. Безопасно вызывать повторно."""
    global _configured
    logger = logging.getLogger(LOGGER_NAME)
    if _configured:
        return logger

    logger.setLevel(logging.DEBUG)
    try:
        handler = RotatingFileHandler(
            get_log_path(), maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(_RedactingFormatter(
            "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"))
        logger.addHandler(handler)
    except OSError:
        logger.addHandler(logging.NullHandler())  # лог не должен мешать работе программы
    logger.propagate = False

    def _excepthook(exc_type, exc, tb):
        logger.critical("Необработанное исключение", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    def _thread_hook(args):
        logger.critical("Необработанное исключение в потоке %s",
                        getattr(args.thread, "name", "?"),
                        exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = _excepthook
    threading.excepthook = _thread_hook

    _configured = True
    from src.version import __version__
    logger.info("=== Запуск MediaHarvester %s | Python %s | %s | frozen=%s ===",
                __version__, platform.python_version(), platform.platform(),
                getattr(sys, "frozen", False))
    return logger


def read_log_tail(max_lines: int = 60) -> str:
    """Последние строки лога (с маскировкой) для отчёта об ошибке."""
    try:
        with open(get_log_path(), "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-max_lines:]
    except OSError:
        return ""
    return redact("".join(lines))
