import os
import subprocess
import sys
import threading
from typing import Callable
from src.utils.helpers import DownloadCancelledError

# Максимум файлов при скачивании ленты целиком (доска, профиль, сабреддит)
LISTING_LIMIT = 500

MEDIA_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".webm", ".mov", ".mp3", ".m4a")


def _count_files(directory: str) -> int:
    return sum(len(files) for _, _, files in os.walk(directory))


def download_gallery(
    url: str,
    download_path: str,
    platform_name: str = "Gallery",
    cookies_path: str = "",
    status_callback: Callable[[str, str, float | None, str], None] | None = None,
    cancel_event: threading.Event | None = None,
    listing: bool = False,
    ytdlp_fallback: bool = True,
) -> str:
    """
    Скачивает фото, галереи, карусели и видео постов через gallery-dl (Instagram, X, Pinterest,
    Reddit, TikTok и др.). Поддерживает отмену через cancel_event и запуск из PyInstaller
    через --gallery-dl-worker. Для лент (listing=True) ограничивает число файлов LISTING_LIMIT.
    Если gallery-dl ничего не скачал и разрешён ytdlp_fallback, пробует yt-dlp.
    Возвращает путь к папке с сохранёнными медиа.
    """
    target_dir = os.path.join(download_path, f"{platform_name}_Downloads")
    os.makedirs(target_dir, exist_ok=True)

    def _notify(text: str, state: str = "working", progress: float | None = None, percent_str: str = "") -> None:
        if status_callback:
            status_callback(text, state, progress, percent_str)

    _notify(f"Подключение к {platform_name}...", "working")

    files_before = _count_files(target_dir)

    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--gallery-dl-worker"]
    else:
        cmd = [sys.executable, "-m", "gallery_dl"]
    cmd += ["--directory", target_dir, "--no-part", "--retries", "3"]
    if listing:
        cmd += ["--range", f"1-{LISTING_LIMIT}"]

    has_cookies = bool(cookies_path and os.path.isfile(cookies_path))
    if has_cookies:
        cmd.extend(["--cookies", cookies_path])

    cmd.append(url)

    startupinfo = None
    creationflags = 0
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        creationflags = subprocess.CREATE_NO_WINDOW

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            startupinfo=startupinfo,
            creationflags=creationflags
        )

        # Читаем вывод в реальном времени с поддержкой cancel_event
        if proc.stdout:
            for line in proc.stdout:
                if cancel_event and cancel_event.is_set():
                    try:
                        proc.terminate()
                        proc.wait(timeout=2)
                    except Exception:
                        proc.kill()
                    _notify(f"Загрузка из {platform_name} отменена", "warning")
                    raise DownloadCancelledError("Загрузка отменена пользователем")

                line_str = line.strip()
                if line_str:
                    stdout_lines.append(line_str)
                    base_name = os.path.basename(line_str)
                    if base_name and base_name.lower().endswith(MEDIA_EXTENSIONS):
                        _notify(f"Скачано: {base_name[:32]}", "working")

        _, stderr_text = proc.communicate()
        if stderr_text:
            stderr_lines.extend(stderr_text.splitlines())

        returncode = proc.returncode
    except DownloadCancelledError:
        raise
    except Exception as e:
        returncode = 1
        stderr_lines.append(str(e))

    if cancel_event and cancel_event.is_set():
        _notify(f"Загрузка из {platform_name} отменена", "warning")
        raise DownloadCancelledError("Загрузка отменена пользователем")

    downloaded_count = _count_files(target_dir) - files_before
    all_output = "\n".join(stdout_lines + stderr_lines)

    # Запасной вариант: yt-dlp, если gallery-dl не нашёл файлов (например, пост — это видео)
    if downloaded_count == 0 and ytdlp_fallback and not listing:
        _notify("Пробуем загрузку через yt-dlp...", "working")
        try:
            from src.core.ytdlp_engine import download_video
            title = download_video(
                url=url,
                download_path=target_dir,
                quality_choice="Максимальное (Авто)",
                progress_callback=status_callback or (lambda *args: None),
                cookies_path=cookies_path if has_cookies else "",
                cancel_event=cancel_event,
                allow_gallery_fallback=False,  # иначе yt-dlp вернёт нас сюда же
            )
            _notify(f"Готово: {title[:40]}", "success", 1.0, "100%")
            return target_dir
        except DownloadCancelledError:
            raise
        except Exception as yt_err:
            all_output += f"\n[yt-dlp error] {yt_err}"

    if downloaded_count > 0:
        _notify(f"Готово: скачано медиа-файлов: {downloaded_count}", "success", 1.0, "100%")
        return target_dir

    # Анализ ошибок и формирование понятного ответа
    out_lower = all_output.lower()
    if any(k in out_lower for k in ("login required", "401", "unauthorized", "checkpoint", "redirected to login", "private")):
        raise RuntimeError(f"Требуется авторизация {platform_name}: укажите cookies.txt в настройках")

    if any(k in out_lower for k in ("429", "too many requests", "rate limit")):
        raise RuntimeError(f"{platform_name} временно ограничил запросы (429). Укажите cookies.txt в настройках")

    if any(k in out_lower for k in ("404", "not found")):
        raise RuntimeError("Контент не найден: публикация удалена или ссылка неверна")

    clean_err = stderr_lines[-1] if stderr_lines else f"Не удалось скачать контент из {platform_name}"
    if "error" in clean_err.lower():
        clean_err = clean_err.split("]")[-1].strip()
    raise RuntimeError(f"{platform_name}: {clean_err[:70]}. Попробуйте указать cookies.txt")
