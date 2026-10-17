import os
import subprocess
import sys
import threading
from typing import Callable, Any
from src.utils.helpers import DownloadCancelledError


def download_instagram(
    url: str,
    download_path: str,
    cookies_path: str = "",
    status_callback: Callable[[str, str, float | None, str], None] | None = None,
    cancel_event: threading.Event | None = None
) -> str:
    """
    Скачивает посты, карусели, фото, Reels и Stories из Instagram.
    Использует gallery-dl с автоматическим fallback на yt-dlp для Reels.
    Поддерживает отмену через cancel_event и запуск из PyInstaller через --gallery-dl-worker.
    Возвращает путь к папке с сохранёнными медиа.
    """
    target_dir = os.path.join(download_path, "Instagram_Downloads")
    os.makedirs(target_dir, exist_ok=True)

    def _notify(text: str, state: str = "working", progress: float | None = None, percent_str: str = "") -> None:
        if status_callback:
            status_callback(text, state, progress, percent_str)

    _notify("Подключение к Instagram...", "working")

    # Считаем файлы в target_dir до старта
    def _count_files(d: str) -> int:
        c = 0
        for _, _, files in os.walk(d):
            c += len(files)
        return c

    files_before = _count_files(target_dir)

    is_frozen = getattr(sys, "frozen", False)
    if is_frozen:
        cmd = [
            sys.executable, "--gallery-dl-worker",
            "--directory", target_dir,
            "--no-part",
            "--retries", "3"
        ]
    else:
        cmd = [
            sys.executable, "-m", "gallery_dl",
            "--directory", target_dir,
            "--no-part",
            "--retries", "3"
        ]

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
                    _notify("Загрузка из Instagram отменена", "warning")
                    raise DownloadCancelledError("Загрузка отменена пользователем")

                line_str = line.strip()
                if line_str:
                    stdout_lines.append(line_str)
                    base_name = os.path.basename(line_str)
                    if base_name and any(base_name.lower().endswith(ext) for ext in ('.jpg', '.png', '.mp4', '.webp')):
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
        _notify("Загрузка из Instagram отменена", "warning")
        raise DownloadCancelledError("Загрузка отменена пользователем")

    files_after = _count_files(target_dir)
    downloaded_count = files_after - files_before

    all_output = "\n".join(stdout_lines + stderr_lines)

    # Автоматический fallback на yt-dlp для Reels или если gallery-dl не скачал файлы
    is_reel_or_video = any(p in url.lower() for p in ("/reel/", "/reels/", "/tv/"))
    if downloaded_count == 0 and is_reel_or_video:
        _notify("Пробуем загрузку через yt-dlp...", "working")
        try:
            from src.core.ytdlp_engine import download_video
            title = download_video(
                url=url,
                download_path=target_dir,
                quality_choice="Максимальное (Авто)",
                progress_callback=status_callback or (lambda *args: None),
                cookies_path=cookies_path if has_cookies else "",
                cancel_event=cancel_event
            )
            _notify(f"Готово: {title[:40]}", "success", 1.0, "100%")
            return target_dir
        except DownloadCancelledError:
            raise
        except Exception as yt_err:
            all_output += f"\n[yt-dlp error] {yt_err}"

    # Если файлы успешно скачаны
    if downloaded_count > 0:
        _notify(f"Готово: скачано медиа-файлов: {downloaded_count}", "success", 1.0, "100%")
        return target_dir

    # Анализ ошибок и формирование понятного ответа
    out_lower = all_output.lower()
    if any(k in out_lower for k in ("login required", "401", "unauthorized", "checkpoint", "redirected to login", "private")):
        raise RuntimeError("Требуется авторизация Instagram: укажите cookies.txt в настройках")

    if any(k in out_lower for k in ("429", "too many requests", "rate limit")):
        raise RuntimeError("Instagram временно ограничил запросы (429). Укажите cookies.txt в настройках")

    if any(k in out_lower for k in ("404", "not found")):
        raise RuntimeError("Контент не найден: публикация удалена или ссылка неверна")

    # Если ничего не помогло и файлов 0
    if returncode != 0 or downloaded_count == 0:
        clean_err = stderr_lines[-1] if stderr_lines else "Не удалось скачать контент из Instagram"
        if "error" in clean_err.lower():
            clean_err = clean_err.split("]")[-1].strip()
        raise RuntimeError(f"Instagram: {clean_err[:70]}. Попробуйте указать cookies.txt")

    return target_dir
