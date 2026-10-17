import os
import re
import shutil
import subprocess
import sys


class DownloadCancelledError(Exception):
    """Исключение, возникающее при отмене загрузки пользователем."""
    pass


# Определение пути к FFmpeg для объединения потоков и конвертации
FFMPEG_PATH: str | None = None
try:
    import imageio_ffmpeg
    FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_PATH = shutil.which("ffmpeg")


def get_resource_path(relative_path: str) -> str:
    """
    Возвращает абсолютный путь к ресурсу.
    Поддерживает как нормальный запуск, так и упаковку в один бинарник через PyInstaller (_MEIPASS).
    """
    try:
        base_path = sys._MEIPASS  # type: ignore[attr-defined]
    except AttributeError:
        # Корень проекта на 2 уровня выше src/utils/helpers.py
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.normpath(os.path.join(base_path, relative_path))


def sanitize_filename(name: str) -> str:
    """Убирает из строки символы, недопустимые в именах файлов."""
    cleaned = re.sub(r'[\\/*?:"<>|]', "_", name).strip(". ")
    return cleaned if cleaned else "media_file"


def open_folder(path: str) -> bool:
    """
    Кроссплатформенное открытие папки в системном проводнике.
    Использует os.startfile на Windows, open на macOS и xdg-open на Linux.
    """
    if not path or not os.path.exists(path):
        return False

    try:
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.run(["open", path], check=True)
        else:
            subprocess.run(["xdg-open", path], check=True)
        return True
    except Exception:
        return False
