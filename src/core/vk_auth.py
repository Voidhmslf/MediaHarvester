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
    """Ищет в тексте (например, в буфере обмена) адрес-результат авторизации VK (vk.com или vk.ru)."""
    for token in (text or "").split():
        if _is_success_url(token, success_prefix):
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
    if _is_vk_host(url):
        return parse_auth_url(url) is not None
    return False


def _is_vk_host(url: str) -> bool:
    host = (urlparse(url or "").hostname or "").lower()
    return host in ("vk.com", "vk.ru") or host.endswith((".vk.com", ".vk.ru"))


def _is_static(url: str) -> bool:
    path = urlparse(url or "").path.lower()
    return path.endswith((".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".woff",
                          ".woff2", ".ico", ".map", ".json"))


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

    state = {"emitted": False, "last": None, "probed": False, "responses": 0, "requests": 0}
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

    def with_timeout(fn, timeout: float = 2.0):
        """Вызов, который может повиснуть во время навигации (evaluate_js), не должен вешать слежение."""
        box: list = []

        def run() -> None:
            try:
                box.append(fn())
            except Exception:
                pass

        t = threading.Thread(target=run, daemon=True)
        t.start()
        t.join(timeout)
        return box[0] if box else None

    def current_urls() -> list[str]:
        """Адрес окна: из кэша pywebview и из самой страницы (там есть фрагмент #...)."""
        urls: list[str] = []
        url = with_timeout(window.get_current_url)
        if isinstance(url, str) and url:
            urls.append(url)
        href = with_timeout(lambda: window.evaluate_js("window.location.href"))
        if isinstance(href, str) and href and href not in urls:
            urls.append(href)
        return urls

    def probe_blank_page() -> None:
        """Страница-приёмник открыта, а токена в адресе нет: ищем его в записи навигации и referrer."""
        if state["probed"]:
            return
        state["probed"] = True
        script = ("JSON.stringify({nav: (performance.getEntriesByType('navigation')[0]||{}).name || '',"
                  " ref: document.referrer || '', len: history.length, name: window.name || ''})")
        raw = with_timeout(lambda: window.evaluate_js(script), 3.0)
        try:
            info = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except ValueError:
            info = {}
        _debug(f"страница без токена: nav={_url_shape(info.get('nav', ''))} "
               f"ref={_url_shape(info.get('ref', ''))} history={info.get('len')} "
               f"window.name={'есть' if info.get('name') else 'пусто'}")
        for candidate in (info.get("nav", ""), info.get("ref", ""), info.get("name", "")):
            check(candidate, "probe")

    window = webview.create_window("Вход ВКонтакте", auth_url, width=470, height=700)

    def on_loaded() -> None:
        for url in current_urls():
            check(url, "loaded")

    def poll() -> None:
        empty_polls = 0
        while not state["emitted"]:
            urls = current_urls()
            empty_polls = empty_polls + 1 if not urls else 0
            if empty_polls > 40:  # окно закрыто
                return
            for url in urls:
                check(url, "poll")
                if url.startswith(("https://oauth.vk.", "http://oauth.vk.")) and "/blank.html" in url:
                    if parse_auth_url(url) is None:
                        probe_blank_page()
            time.sleep(0.25)

    def on_shown() -> None:
        threading.Thread(target=poll, daemon=True).start()

    def on_response(response) -> None:
        """Редирект VK приходит заголовком Location: в нём фрагмент с токеном виден целиком."""
        try:
            location = next((v for k, v in (response.headers or {}).items() if str(k).lower() == "location"), "")
            if location or _is_vk_host(response.url) and not _is_static(response.url):
                if state["responses"] < 150:
                    state["responses"] += 1
                    _debug(f"response {response.status_code} {_url_shape(response.url)}"
                           + (f" -> {_url_shape(location)}" if location else ""))
            if location:
                check(location, "redirect")
        except Exception as e:
            _debug(f"on_response: {e}")

    def on_request(request) -> None:
        try:
            if _is_vk_host(request.url) and not _is_static(request.url) and state["requests"] < 150:
                state["requests"] += 1
                _debug(f"request {request.method} {_url_shape(request.url)}")
            check(request.url, "request")
        except Exception as e:
            _debug(f"on_request: {e}")

    window.events.loaded += on_loaded
    window.events.shown += on_shown
    for event_name, handler in (("response_received", on_response), ("request_sent", on_request)):
        try:
            getattr(window.events, event_name).__iadd__(handler)
        except Exception as e:
            _debug(f"не удалось подписаться на {event_name}: {e}")

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
