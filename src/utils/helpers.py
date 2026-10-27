import os
import re
import shutil
import subprocess
import sys


class DownloadCancelledError(Exception):
    """Исключение, возникающее при отмене загрузки пользователем."""
    pass


def is_android() -> bool:
    """Запуск внутри Android-приложения (Chaquopy): Kotlin-часть выставляет MH_ANDROID=1."""
    return os.environ.get("MH_ANDROID") == "1"


def is_linux() -> bool:
    """Настольный Linux (Android тоже отдаёт sys.platform == "linux", но это другое приложение)."""
    return sys.platform.startswith("linux") and not is_android()


def restore_system_env() -> None:
    """
    В сборке PyInstaller загрузчик подменяет LD_LIBRARY_PATH на папку с собственными библиотеками,
    и программы, которые мы запускаем (xdg-open, браузер), пытаются загрузить именно их и падают.
    Сам процесс библиотеки уже загрузил, поэтому возвращаем значение, которое было до запуска.
    """
    if not (is_linux() and getattr(sys, "frozen", False)):
        return
    original = os.environ.pop("LD_LIBRARY_PATH_ORIG", None)
    if original is None:
        os.environ.pop("LD_LIBRARY_PATH", None)
    else:
        os.environ["LD_LIBRARY_PATH"] = original


# Определение пути к FFmpeg для объединения потоков и конвертации.
# На Android путь к бинарнику задаёт приложение через MH_FFMPEG (может быть пустым — тогда без склейки).
FFMPEG_PATH: str | None = None
if is_android():
    FFMPEG_PATH = os.environ.get("MH_FFMPEG") or None
else:
    try:
        import imageio_ffmpeg
        FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        FFMPEG_PATH = shutil.which("ffmpeg")


def get_app_data_dir() -> str:
    """
    Постоянная папка для настроек и обновлений. В одно-файловой сборке PyInstaller папка рядом
    с кодом — временная (_MEIPASS) и стирается при выходе, поэтому данные хранятся в профиле пользователя.
    """
    if is_android():
        path = os.environ.get("MH_DATA_DIR") or os.path.expanduser("~/MediaHarvester")
        os.makedirs(path, exist_ok=True)
        return path
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    path = os.path.join(base, "MediaHarvester")
    os.makedirs(path, exist_ok=True)
    return path


def check_ffmpeg(timeout: float = 8.0) -> tuple[bool, str]:
    """
    Проверяет, что FFmpeg найден и запускается. Возвращает (работает, версия или причина проблемы).
    Без FFmpeg не склеиваются видео и аудио дорожки (1080p и выше) и не работает конвертация в MP3.
    """
    if not FFMPEG_PATH:
        return False, "не найден"
    if not os.path.isfile(FFMPEG_PATH):
        return False, "файл не найден"
    try:
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        out = subprocess.run(
            [FFMPEG_PATH, "-version"], capture_output=True, text=True,
            timeout=timeout, **kwargs
        )
    except Exception as e:
        return False, f"не запускается ({type(e).__name__})"
    if out.returncode != 0:
        return False, "не запускается"
    first = (out.stdout or "").splitlines()[0] if out.stdout else ""
    parts = first.split()
    version = parts[2] if len(parts) >= 3 and parts[0].lower() == "ffmpeg" else "OK"
    return True, version


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
