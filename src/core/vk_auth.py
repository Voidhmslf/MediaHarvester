"""
Вход в ВКонтакте без ручного копирования токена.

Основной путь — отдельное окно со страницей авторизации VK (pywebview + Edge WebView2): как только
VK перенаправляет на blank.html с access_token в адресе, токен забирается автоматически.
Окно запускается отдельным процессом (так же, как gallery-dl), потому что pywebview требует
главный поток, а он занят интерфейсом приложения.
Запасной путь (если окно недоступно) — обычный браузер и слежение за буфером обмена:
см. find_auth_result() и MediaHarvesterApp._watch_clipboard.
"""
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from src.utils.logger import get_logger

log = get_logger("vk_auth")

BLANK_PREFIX = "https://oauth.vk.com/blank.html"
LOGIN_TIMEOUT_SECONDS = 600
WORKER_FLAG = "--vk-login-worker"

# Коды завершения окна входа
EXIT_OK = 0
EXIT_UNAVAILABLE = 3


@dataclass
class VkAuthResult:
    token: str = ""
    user_id: str = ""
    expires_in: str = ""
    error: str = ""
    error_description: str = ""


@dataclass
class LoginOutcome:
    status: str          # "ok" | "closed" | "denied" | "unavailable" | "cancelled" | "timeout"
    result: VkAuthResult | None = None
    detail: str = ""


def parse_auth_url(url: str) -> VkAuthResult | None:
    """Достаёт access_token (или ошибку авторизации) из адреса, на который VK перенаправил после входа."""
    if not url:
        return None
    parsed = urlparse(url.strip())
    params: dict[str, list[str]] = {}
    for part in (parsed.query, parsed.fragment):
        for key, values in parse_qs(part).items():
            params.setdefault(key, []).extend(values)

    def first(key: str) -> str:
        return params.get(key, [""])[0]

    token = first("access_token")
    if token:
        return VkAuthResult(token=token, user_id=first("user_id"), expires_in=first("expires_in"))
    if first("error"):
        return VkAuthResult(error=first("error"), error_description=first("error_description"))
    return None


def find_auth_result(text: str, success_prefix: str = BLANK_PREFIX) -> VkAuthResult | None:
    """Ищет в тексте (например, в буфере обмена) адрес-результат авторизации VK."""
    for token in (text or "").split():
        if token.startswith(success_prefix):
            result = parse_auth_url(token)
            if result and result.token:
                return result
    return None


# ──────────────────────────────────────────────────────────────
# Окно входа (рабочий процесс)
# ──────────────────────────────────────────────────────────────
def _is_success_url(url: str, success_prefix: str) -> bool:
    """Адрес, на который VK вернул результат авторизации (токен или ошибку)."""
    if not url:
        return False
    if url.startswith(success_prefix):
        return True
    # VK может отдавать результат на любом своём домене (vk.com, vk.ru) — важно только наличие токена/ошибки
    host = (urlparse(url).hostname or "").lower()
    if host == "vk.com" or host.endswith(".vk.com") or host == "vk.ru" or host.endswith(".vk.ru"):
        return parse_auth_url(url) is not None
    return False


def _url_shape(url: str) -> str:
    """Адрес без значений параметров (токены не попадают в диагностику): host/path#имена,параметров."""
    parsed = urlparse(url or "")
    names = sorted(set(parse_qs(parsed.query)) | set(parse_qs(parsed.fragment)))
    tail = f" [{','.join(names)}]" if names else ""
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}{tail}"


def _debug(message: str) -> None:
    """Диагностика окна входа (только формы адресов, без значений) в logs/vk_login_debug.log."""
    try:
        from src.utils.logger import get_log_dir
        with open(os.path.join(get_log_dir(), "vk_login_debug.log"), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except Exception:
        pass


def run_login_window(auth_url: str, success_prefix: str = BLANK_PREFIX) -> int:
    """
    Показывает окно с авторизацией VK и печатает в stdout одну JSON-строку с результатом.
    Выполняется в отдельном процессе (см. login_in_window).
    Адрес окна проверяется и по событию загрузки, и опросом каждые 0.25 с: редирект VK
    может прийти раньше, чем успеет сработать событие.
    """
    def emit(payload: dict) -> None:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    try:
        import webview
    except Exception as e:
        emit({"status": "unavailable", "detail": f"pywebview не загружен: {e}"})
        return EXIT_UNAVAILABLE

    state = {"emitted": False, "last": None}
    lock = threading.Lock()
    _debug("окно входа запущено")

    def check(url: str | None, source: str) -> None:
        if not url:
            return
        if url != state["last"]:
            state["last"] = url
            _debug(f"{source}: {_url_shape(url)}")
        if not _is_success_url(url, success_prefix):
            return
        result = parse_auth_url(url)
        if result is None:
            return
        with lock:
            if state["emitted"]:
                return
            state["emitted"] = True
        _debug("результат получен: " + ("токен" if result.token else f"отказ ({result.error})"))
        if result.token:
            emit({"status": "ok", "token": result.token, "user_id": result.user_id,
                  "expires_in": result.expires_in})
        else:
            emit({"status": "denied", "detail": result.error_description or result.error})
        window.destroy()

    def current_url() -> str | None:
        # Адрес из самой страницы надёжнее: он содержит фрагмент (#access_token=...)
        try:
            href = window.evaluate_js("window.location.href")
            if isinstance(href, str) and href:
                return href
        except Exception:
            pass
        try:
            return window.get_current_url()
        except Exception:
            return None

    window = webview.create_window("Вход ВКонтакте", auth_url, width=470, height=700)

    def on_loaded() -> None:
        check(current_url(), "loaded")

    def poll() -> None:
        failures = 0
        while not state["emitted"]:
            url = current_url()
            failures = failures + 1 if url is None else 0
            if failures > 40:  # окно закрыто
                return
            check(url, "poll")
            time.sleep(0.25)

    def on_shown() -> None:
        threading.Thread(target=poll, daemon=True).start()

    window.events.loaded += on_loaded
    window.events.shown += on_shown

    try:
        # Без постоянного профиля: после закрытия окна cookie VK не остаются на диске
        webview.start(gui="edgechromium" if sys.platform == "win32" else None, private_mode=True)
    except Exception as e:
        _debug(f"webview.start упал: {e}")
        if not state["emitted"]:
            emit({"status": "unavailable", "detail": f"окно входа не запустилось: {e}"})
            return EXIT_UNAVAILABLE

    if not state["emitted"]:
        _debug("окно закрыто пользователем")
        emit({"status": "closed"})
    return EXIT_OK


def _worker_command(auth_url: str, success_prefix: str) -> tuple[list[str], str | None]:
    if getattr(sys, "frozen", False):
        return [sys.executable, WORKER_FLAG, auth_url, success_prefix], None
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return [sys.executable, "-m", "src.core.vk_auth", auth_url, success_prefix], root


def login_in_window(
    auth_url: str,
    cancel_event: threading.Event | None = None,
    success_prefix: str = BLANK_PREFIX,
    timeout: float = LOGIN_TIMEOUT_SECONDS,
) -> LoginOutcome:
    """Запускает окно входа отдельным процессом и ждёт результата. Блокирующий вызов — для рабочего потока."""
    cmd, cwd = _worker_command(auth_url, success_prefix)
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", creationflags=creationflags)
    except Exception as e:
        log.warning("Не удалось запустить окно входа: %s", e)
        return LoginOutcome("unavailable", detail=str(e))

    deadline = time.monotonic() + timeout
    while True:
        try:
            proc.wait(timeout=0.3)
            break
        except subprocess.TimeoutExpired:
            pass
        if cancel_event and cancel_event.is_set():
            _kill(proc)
            return LoginOutcome("cancelled")
        if time.monotonic() > deadline:
            _kill(proc)
            return LoginOutcome("timeout")

    stdout, stderr = proc.communicate()
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        status = data.get("status", "unavailable")
        if status == "ok" and data.get("token"):
            return LoginOutcome("ok", VkAuthResult(
                token=data["token"], user_id=str(data.get("user_id", "")),
                expires_in=str(data.get("expires_in", ""))))
        return LoginOutcome(status, detail=data.get("detail", ""))

    log.warning("Окно входа завершилось без результата (код %s): %s", proc.returncode, (stderr or "")[-300:])
    return LoginOutcome("unavailable", detail=(stderr or "")[-200:] or f"код {proc.returncode}")


def _kill(proc: subprocess.Popen) -> None:
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def fetch_user_name(token: str) -> str | None:
    """Имя и фамилия владельца токена или None, если определить не удалось (нет сети и т.п.)."""
    import vk_api
    import vk_api.exceptions
    try:
        users = vk_api.VkApi(token=token).get_api().users.get()
    except vk_api.exceptions.ApiError as e:
        if e.code == 5:
            raise
        return None
    except Exception:
        return None
    if users:
        return f"{users[0].get('first_name', '')} {users[0].get('last_name', '')}".strip() or None
    return None


if __name__ == "__main__":
    prefix = sys.argv[2] if len(sys.argv) > 2 else BLANK_PREFIX
    sys.exit(run_login_window(sys.argv[1], prefix))
