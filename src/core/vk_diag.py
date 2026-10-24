"""
Диагностика токена VK: какие методы API отвечают с этим токеном и при каких параметрах запроса.
Результаты (только коды, тексты ошибок и служебные заголовки VK, без токена) пишутся в лог
и в короткую сводку для статуса.

Запросы идут бережно: VK ограничивает частоту, а ответ «Flood control» (ошибка 9) легко принять
за «токен неверный». Поэтому сначала короткий этап с одним набором параметров; если уже он упирается
в лимит, перебор не продолжается.
"""
import time

from src.utils.logger import get_logger, redact

log = get_logger("vk_diag")

HOSTS = ("api.vk.com", "api.vk.ru")
VERSIONS = ("5.131", "5.199")
REQUEST_PAUSE = 1.0  # VK ограничивает токен тремя запросами в секунду; берём запас
INTERESTING_HEADERS = ("retry-after", "x-ratelimit-remaining", "x-ratelimit-limit", "x-vk-trace")


class CallResult:
    def __init__(self, ok: bool, text: str, code: int | None = None, data=None, details: str = ""):
        self.ok, self.text, self.code, self.data, self.details = ok, text, code, data, details


def _call(host: str, method: str, params: dict, user_agent: str | None, transport: str = "curl",
          timeout: float = 15.0) -> CallResult:
    """Один запрос к VK API через curl_cffi (как у vkpymusic) или requests."""
    headers = {"User-Agent": user_agent} if user_agent else {}
    url = f"https://{host}/method/{method}"
    started = time.monotonic()
    try:
        if transport == "requests":
            import requests
            response = requests.get(url, params=params, headers=headers, timeout=timeout)
        else:
            from curl_cffi import requests as curl_requests
            response = curl_requests.get(url, params=params, headers=headers,
                                         impersonate="chrome110", timeout=timeout)
        data = response.json()
    except Exception as e:
        return CallResult(False, f"сеть: {type(e).__name__}")
    elapsed = time.monotonic() - started
    hdrs = {k.lower(): v for k, v in dict(response.headers).items()}
    extra = ",".join(f"{h}={hdrs[h]}" for h in INTERESTING_HEADERS if h in hdrs)
    details = f"http={response.status_code} {elapsed:.1f}s" + (f" [{extra}]" if extra else "")
    if "response" in data:
        return CallResult(True, "OK", data=data["response"], details=details)
    error = data.get("error", {})
    if isinstance(error, dict):
        code = error.get("error_code")
        keys = ",".join(sorted(k for k in error if k not in ("request_params", "error_code", "error_msg")))
        msg = redact(str(error.get("error_msg", "")))[:80]
        return CallResult(False, f"ошибка {code}: {msg}", code=code,
                          details=details + (f" extra_keys=[{keys}]" if keys else ""))
    return CallResult(False, f"ошибка: {redact(str(error))[:80]}", details=details)


def _fmt(label: str, r: CallResult) -> str:
    return f"{label}: {r.text} ({r.details})" if r.details else f"{label}: {r.text}"


def run_diagnostics(token: str, kind: str, user_agents: dict[str, str]) -> tuple[str, list[str]]:
    """
    Этап 1 (мягкий): users.get, account.getProfileInfo и главный метод раздела (audio.get для музыки,
    photos.getAlbums для фото) на api.vk.com с первым User-Agent, двумя транспортами.
    Этап 2 (только если users.get отвечает): перебор хостов, версий API и User-Agent для главного метода.
    Возвращает (краткая сводка, строки отчёта).
    """
    target = "audio.get" if kind == "music" else "photos.getAlbums"
    lines: list[str] = []
    ua_items = list(user_agents.items())
    first_ua_name, first_ua = ua_items[0]

    def base(version: str) -> dict:
        return {"access_token": token, "v": version, "https": 1, "lang": "ru"}

    def target_params(version: str, user_id) -> dict:
        params = base(version)
        if kind == "music":
            params.update({"count": 1, "extended": 1})
        else:
            params.update({"need_system": 1})
        if user_id:
            params["owner_id"] = user_id
        return params

    user_id = None
    users_results: list[CallResult] = []
    target_results: list[CallResult] = []

    # ── Этап 1
    for transport in ("curl", "requests"):
        host, version = HOSTS[0], VERSIONS[0]
        label = f"[этап 1] {transport} {host} v={version} ua={first_ua_name}"
        r = _call(host, "users.get", base(version), first_ua or None, transport)
        lines.append(_fmt(f"{label} users.get", r)); users_results.append(r)
        if r.ok and r.data and user_id is None:
            user_id = r.data[0].get("id")
        time.sleep(REQUEST_PAUSE)

        r = _call(host, "account.getProfileInfo", base(version), first_ua or None, transport)
        lines.append(_fmt(f"{label} account.getProfileInfo", r))
        time.sleep(REQUEST_PAUSE)

        r = _call(host, target, target_params(version, user_id), first_ua or None, transport)
        lines.append(_fmt(f"{label} {target}", r)); target_results.append(r)
        time.sleep(REQUEST_PAUSE)

    users_ok = any(r.ok for r in users_results)
    flood = [r for r in users_results if r.code in (6, 9, 29)]
    auth_bad = [r for r in users_results if r.code == 5]

    # ── Этап 2
    if users_ok:
        for host in HOSTS:
            for version in VERSIONS:
                for ua_name, ua in ua_items:
                    label = f"[этап 2] curl {host} v={version} ua={ua_name}"
                    r = _call(host, target, target_params(version, user_id), ua or None, "curl")
                    lines.append(_fmt(f"{label} {target}", r)); target_results.append(r)
                    time.sleep(REQUEST_PAUSE)

    for line in lines:
        log.info("диагностика (%s): %s", kind, line)

    working = [r for r in target_results if r.ok]
    if working:
        summary = f"Токен рабочий: {target} отвечает ({len(working)} из {len(target_results)} попыток)"
    elif auth_bad and not users_ok:
        summary = "VK не принимает токен (ошибка 5): войдите заново"
    elif flood and not users_ok:
        summary = (f"VK отвечает «{flood[0].text}» даже на users.get: это ограничение частоты, а не неверный токен. "
                   "Подождите 10–15 минут и повторите")
    elif users_ok:
        errors = sorted({r.text for r in target_results})
        summary = f"Токен принят (users.get OK), но {target} не работает: {errors[0] if errors else '?'}"
    else:
        summary = "Ни один метод не ответил: " + (users_results[0].text if users_results else "нет ответа")
    log.info("диагностика (%s): итог — %s", kind, summary)
    return summary, lines
