"""
Диагностика токена VK: какие методы API отвечают с этим токеном и при каких параметрах запроса.
Результаты (только коды и тексты ошибок VK, без токена) пишутся в лог и в короткую сводку для статуса.
"""
import time

from src.utils.logger import get_logger

log = get_logger("vk_diag")

HOSTS = ("api.vk.com", "api.vk.ru")
VERSIONS = ("5.131", "5.199")
REQUEST_PAUSE = 0.4  # VK ограничивает токен тремя запросами в секунду


def _call(host: str, method: str, params: dict, user_agent: str | None, timeout: float = 15.0):
    """Один запрос к VK API. Возвращает (ok, описание, ответ)."""
    from curl_cffi import requests as curl_requests  # тот же клиент, что использует vkpymusic
    headers = {"User-Agent": user_agent} if user_agent else {}
    try:
        response = curl_requests.get(
            f"https://{host}/method/{method}", params=params, headers=headers,
            impersonate="chrome110", timeout=timeout)
        data = response.json()
    except Exception as e:
        return False, f"сеть: {type(e).__name__}", None
    if "response" in data:
        return True, "OK", data["response"]
    error = data.get("error", {})
    if isinstance(error, dict):
        return False, f"ошибка {error.get('error_code', '?')}: {str(error.get('error_msg', ''))[:70]}", None
    return False, f"ошибка: {str(error)[:70]}", None


def run_diagnostics(token: str, kind: str, user_agents: dict[str, str]) -> tuple[str, list[str]]:
    """
    Перебирает хосты, версии API и User-Agent для users.get и «главного» метода раздела
    (audio.get для музыки, photos.getAlbums для фото).
    user_agents: {"имя": "строка UA"}; пустая строка — запрос без User-Agent.
    Возвращает (краткая сводка, строки отчёта).
    """
    target = "audio.get" if kind == "music" else "photos.getAlbums"
    lines: list[str] = []
    user_id = None
    users_ok = 0
    target_ok: list[str] = []
    attempts = 0

    for host in HOSTS:
        for version in VERSIONS:
            for ua_name, ua in user_agents.items():
                base = {"access_token": token, "v": version, "https": 1, "lang": "ru"}
                ok, text, resp = _call(host, "users.get", dict(base), ua or None)
                attempts += 1
                lines.append(f"{host} v={version} ua={ua_name} users.get: {text}")
                if ok:
                    users_ok += 1
                    if user_id is None and resp:
                        user_id = resp[0].get("id")
                time.sleep(REQUEST_PAUSE)

                params = dict(base)
                if kind == "music":
                    params.update({"count": 1, "extended": 1, "owner_id": user_id or 0})
                    if not user_id:
                        params.pop("owner_id")
                else:
                    params.update({"owner_id": user_id or 0, "need_system": 1})
                    if not user_id:
                        params.pop("owner_id")
                ok, text, _ = _call(host, target, params, ua or None)
                attempts += 1
                lines.append(f"{host} v={version} ua={ua_name} {target}: {text}")
                if ok:
                    target_ok.append(f"{host} v={version} ua={ua_name}")
                time.sleep(REQUEST_PAUSE)

    for line in lines:
        log.info("диагностика (%s): %s", kind, line)

    if users_ok == 0:
        summary = "Токен не принят VK ни в одной комбинации: войдите заново"
    elif target_ok:
        summary = f"Токен рабочий: {target} отвечает ({len(target_ok)} комб.): {target_ok[0]}"
    else:
        # самый частый ответ метода — по нему видно причину
        errors = sorted({l.split(f"{target}: ", 1)[1] for l in lines if f" {target}: " in l})
        summary = f"Токен принят (users.get OK), но {target} не работает: {errors[0] if errors else '?'}"
    log.info("диагностика (%s): итог — %s", kind, summary)
    return summary, lines
