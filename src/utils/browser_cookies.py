"""
Cookies прямо из браузера пользователя (вместо ручного экспорта cookies.txt).

gallery-dl и yt-dlp умеют читать профиль браузера сами. Лучше всего работает Firefox; Chrome, Edge, Opera
и другие на Chromium хранят cookies в базе, которую браузер держит открытой, поэтому для них браузер
нужно закрыть, а у новых версий Chrome шифрование мешает чтению совсем (тогда подойдёт Firefox или cookies.txt).
"""
import os
import sys

NONE_CHOICE = "Не использовать"

# Название в списке -> (имя для gallery-dl/yt-dlp, функция пути профиля или None)
_APPDATA = os.environ.get("APPDATA", "")
_BROWSERS: dict[str, tuple[str, str | None]] = {
    "Firefox": ("firefox", None),
    "Chrome": ("chrome", None),
    "Edge": ("edge", None),
    "Opera": ("opera", None),
    "Opera GX": ("opera", os.path.join("Opera Software", "Opera GX Stable")),
    "Brave": ("brave", None),
    "Vivaldi": ("vivaldi", None),
}
if sys.platform.startswith("linux"):
    # Opera GX есть только для Windows и macOS; зато на Linux распространён Chromium
    del _BROWSERS["Opera GX"]
    _BROWSERS["Chromium"] = ("chromium", None)

BROWSER_CHOICES = [NONE_CHOICE, *_BROWSERS]


def resolve(choice: str) -> tuple[str, str | None] | None:
    """(браузер, путь к профилю или None) для выбранного пункта либо None, если браузер не выбран."""
    entry = _BROWSERS.get(choice or "")
    if entry is None:
        return None
    browser, relative_profile = entry
    if relative_profile is None:
        return browser, None
    return browser, os.path.join(os.environ.get("APPDATA", _APPDATA), relative_profile)


def gallery_dl_arg(choice: str) -> str | None:
    """Значение для `gallery-dl --cookies-from-browser` (БРАУЗЕР[:ПРОФИЛЬ])."""
    resolved = resolve(choice)
    if resolved is None:
        return None
    browser, profile = resolved
    return f"{browser}:{profile}" if profile else browser


def ytdlp_option(choice: str) -> tuple | None:
    """Значение для параметра yt-dlp `cookiesfrombrowser`: (браузер, профиль, keyring, контейнер)."""
    resolved = resolve(choice)
    if resolved is None:
        return None
    browser, profile = resolved
    return (browser, profile, None, None)
