"""
Перевод технических ошибок (yt-dlp, gallery-dl, requests, ОС) в понятные пользователю сообщения.

explain_error(exc) -> ErrorInfo(message, hint, technical, kind):
  message   — коротко, что случилось (влезает в строку статуса);
  hint      — что делать;
  technical — исходный текст ошибки для лога и отчёта.
"""
import errno
import re
from dataclasses import dataclass

from src.utils.logger import redact


@dataclass
class ErrorInfo:
    message: str
    hint: str = ""
    technical: str = ""
    kind: str = "unknown"


# (kind, regex, сообщение, подсказка). Порядок важен: более конкретные правила — выше.
_RULES: list[tuple[str, str, str, str]] = [
    ("browser_cookies", r"could not copy .*cookie|failed to decrypt|cookies? (database|from browser)|"
                        r"не удалось прочитать cookies",
     "Не удалось прочитать cookies из браузера",
     "Закройте браузер и повторите, выберите Firefox либо укажите файл cookies.txt"),
    ("vk_scope", r"vk api error 15|no access to call this method|cannot be called with current scopes",
     "VK не разрешил этому токену доступ (ошибка 15)",
     "Для музыки войдите заново в режиме «Музыка» кнопкой «Войти через ВКонтакте» (нужен отдельный токен). "
     "Если не помогает — проверьте, что плейлист или профиль открыты"),
    ("vk_audio_closed", r"vk api error 3\b|unknown method passed",
     "VK сейчас не отдаёт музыку по этому токену (метод закрыт)",
     "Музыку VK через API получить не удаётся. Используйте режим «Треки по списку»: он ищет те же треки на YouTube "
     "и не обращается к VK"),
    ("vk_token", r"vk api error 5\b|user authorization failed|invalid access_token|access_token has expired",
     "Токен VK недействителен или истёк",
     "Нажмите «Войти через ВКонтакте» и подтвердите доступ заново"),
    ("vk_private", r"vk api error (30|200|201|203)\b|this profile is private|access to .* denied",
     "Доступ закрыт настройками приватности VK",
     "Попросите автора открыть доступ или используйте ссылку на открытый материал"),
    ("vk_flood", r"vk api error (6|9|29)\b|too many requests per second|flood control|rate limit reached",
     "VK временно ограничил частоту запросов",
     "Подождите несколько минут и повторите"),
    ("bot_check", r"confirm you.?re not a bot|not a bot",
     "YouTube просит подтвердить, что вы не бот",
     "Укажите cookies.txt из браузера, где вы вошли в YouTube, или повторите позже"),
    ("age", r"confirm your age|age.restricted|age-restricted|inappropriate for some users",
     "Видео с возрастным ограничением (18+)",
     "Укажите cookies.txt из браузера, где вы вошли в аккаунт"),
    ("members", r"members.only|join this channel|channel.s members|available to this channel",
     "Видео доступно только подписчикам канала",
     "Укажите cookies.txt аккаунта с оформленной подпиской"),
    ("login", r"private video|this video is private|login required|log in|sign in|"
              r"requires authentication|authentication required|not logged in|redirected to login|"
              r"checkpoint|unauthorized|\b401\b|private",
     "Нужен вход в аккаунт или доступ закрыт",
     "Укажите cookies.txt из браузера, где вы вошли в аккаунт (блок «Файл Cookies»)"),
    ("rate_limit", r"\b429\b|too many requests|rate.?limit",
     "Сайт временно ограничил запросы",
     "Подождите несколько минут, укажите cookies.txt или смените сеть/VPN"),
    ("geo", r"not available in your country|geo.?restrict|geo.?block|blocked it in your country|"
            r"not made this video available in your country",
     "Контент недоступен в вашей стране",
     "Попробуйте VPN"),
    ("copyright", r"copyright|blocked it on copyright|removed.*(claim|violation)|terms of service",
     "Контент заблокирован правообладателем или удалён за нарушение правил",
     "Скачать его не получится"),
    ("drm", r"\bdrm\b|drm.protected",
     "Контент защищён DRM",
     "Такие материалы скачать нельзя"),
    ("ffmpeg", r"ffmpeg|ffprobe|postprocessing|merger",
     "Не удалось обработать видео или звук (FFmpeg)",
     "Проверьте, что в шапке программы нет красной пометки про ffmpeg; при необходимости переустановите программу"),
    ("live", r"is live|live event|premieres in|will begin in|upcoming|not yet started|live stream",
     "Это прямой эфир или премьера, которая ещё не закончилась",
     "Дождитесь окончания трансляции и повторите"),
    ("format", r"requested format is not available|no video formats found|no formats found",
     "Выбранное качество недоступно для этого видео",
     "Выберите «Максимальное (Авто)» или другое качество"),
    ("unsupported", r"unsupported url|is not a valid url|no suitable extractor|invalid url",
     "Эта ссылка не поддерживается",
     "Нужна ссылка на конкретное видео, пост или альбом — откройте её в браузере и скопируйте адрес"),
    ("unavailable", r"video unavailable|this video is unavailable|has been removed|no longer available|"
                    r"does not exist|\b404\b|not found|has been deleted|account.*terminated|"
                    r"this content isn.t available|post.*(removed|deleted)",
     "Видео или пост недоступны: удалены или ссылка неверна",
     "Проверьте, что ссылка открывается в браузере"),
    ("forbidden", r"\b403\b|forbidden",
     "Сайт отказал в доступе (403)",
     "Попробуйте cookies.txt или VPN. Если не помогает — подождите: yt-dlp обновляется автоматически при запуске"),
    ("ssl", r"certificate_verify_failed|ssl:|sslerror|ssl error|certificate",
     "Ошибка защищённого соединения (SSL)",
     "Проверьте дату и время на компьютере, а также антивирус или VPN, подменяющие сертификаты"),
    ("network", r"getaddrinfo failed|failed to resolve|no address associated with hostname|name or service not known|temporary failure in name resolution|"
               r"network is unreachable|connection refused|connectionerror|max retries exceeded|"
               r"timed out|timeout|remote end closed|connection reset|connection aborted|"
               r"incompleteread|unable to connect|no route to host|urlopen error|read error|"
               r"сетевая ошибка",
     "Нет связи с сайтом",
     "Проверьте интернет или VPN и повторите попытку"),
    ("broken_extractor", r"unable to extract|nsig extraction|unable to download webpage|failed to extract|"
                         r"player response|signature extraction|unable to download json|"
                         r"unexpected response|extractor error|please report this issue|"
                         r"unable to download api page|cannot parse",
     "Сайт изменился, и загрузчик не смог разобрать страницу",
     "Обычно это лечится обновлением yt-dlp: оно проверяется при запуске — перезапустите программу позже"),
]

_OS_RULES: dict[int, tuple[str, str, str]] = {
    errno.ENOSPC: ("disk_full", "Недостаточно места на диске",
                   "Освободите место или выберите другую папку для сохранения"),
    errno.EACCES: ("permission", "Нет доступа к папке сохранения",
                   "Выберите другую папку (например, в «Документах» или «Загрузках»)"),
    errno.EPERM: ("permission", "Нет доступа к папке сохранения",
                  "Выберите другую папку (например, в «Документах» или «Загрузках»)"),
    errno.ENAMETOOLONG: ("path_too_long", "Слишком длинный путь или имя файла",
                         "Выберите папку ближе к корню диска, например D:\\Media"),
    errno.EROFS: ("permission", "Папка доступна только для чтения",
                  "Выберите другую папку для сохранения"),
}


def _is_cyrillic_message(text: str) -> bool:
    return bool(re.search(r"[А-Яа-яЁё]", text))


def explain_error(exc: BaseException | str) -> ErrorInfo:
    """Преобразует исключение (или текст ошибки) в понятное сообщение с подсказкой."""
    if isinstance(exc, BaseException):
        raw = str(exc)
        cause = exc.__cause__ or exc.__context__
        if cause is not None and str(cause) and str(cause) not in raw:
            raw = f"{raw} | {cause}"
    else:
        exc, raw = None, str(exc)
    technical = redact(f"{type(exc).__name__}: {raw}" if exc is not None else raw).strip()

    # Ошибки ОС: диск, права, длинные пути
    for e in (exc, getattr(exc, "__cause__", None)):
        if isinstance(e, OSError):
            code = e.errno
            winerr = getattr(e, "winerror", None)
            if winerr == 206:
                code = errno.ENAMETOOLONG
            elif winerr == 112:
                code = errno.ENOSPC
            if isinstance(e, PermissionError) and code is None:
                code = errno.EACCES
            if code in _OS_RULES:
                kind, message, hint = _OS_RULES[code]
                return ErrorInfo(message, hint, technical, kind)

    clean = raw
    if "ERROR:" in clean:
        clean = clean.split("ERROR:")[-1].strip()
    lowered = clean.lower()

    # Понятное сообщение движка (уже по-русски): оставляем как есть, не искажая причину
    friendly = _is_cyrillic_message(clean) and isinstance(exc, (RuntimeError, ValueError))
    if friendly:
        for kind, pattern, message, hint in _RULES:
            if kind in ("login", "rate_limit") and re.search(pattern, lowered):
                # engines уже подсказывают про cookies.txt — дополняем общей подсказкой, не меняя текст
                return ErrorInfo(clean, hint, technical, kind)
        return ErrorInfo(clean, "", technical, "engine")

    for kind, pattern, message, hint in _RULES:
        if re.search(pattern, lowered):
            return ErrorInfo(message, hint, technical, kind)

    short = re.sub(r"\s+", " ", clean).strip()
    short = redact(short)[:90] if short else type(exc).__name__ if exc is not None else "неизвестная ошибка"
    return ErrorInfo(
        f"Непредвиденная ошибка: {short}",
        "Нажмите «Подробнее» и отправьте отчёт разработчику — это поможет её исправить",
        technical, "unknown")
