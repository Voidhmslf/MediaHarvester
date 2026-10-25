import json
import os
import sys
from typing import Any

from src.utils.helpers import get_app_data_dir

# ─────────────────────────────────────────
# ЦВЕТОВАЯ ПАЛИТРА (Fluent / Windows 11 Dark)
# ─────────────────────────────────────────
BG_MAIN             = "#202020"
SURFACE_CARD        = "#2B2B2B"
SURFACE_CARD_BORDER = "#3A3A3A"
SURFACE_INNER       = "#1A1A1A"
SURFACE_INNER_BORDER = "#404040"

ACCENT_BLUE         = "#0078D4"
ACCENT_BLUE_HOVER   = "#006CBE"

# Статусные цвета — только в статус-баре
STATUS_GREEN = "#3DB06B"
STATUS_RED   = "#C84242"
STATUS_AMBER = "#C48F1A"

TEXT_MAIN      = "#FFFFFF"
TEXT_SECONDARY = "#AAAAAA"
TEXT_MUTED     = "#707070"

# Scope-конфиги OAuth для каждого режима
AUTH_URL_PHOTOS = (
    "https://oauth.vk.com/authorize?client_id=7497650"
    "&scope=photos,offline"
    "&redirect_uri=https://oauth.vk.com/blank.html"
    "&display=page&response_type=token&revoke=1"
)
# Музыку VK отдаёт только официальным клиентам: vkpymusic рассчитан на токен Kate Mobile (client_id 2685278)
# и на её User-Agent (см. VK_MUSIC_USER_AGENT). Токен сторонних приложений даёт ошибку VK API 15.
AUTH_URL_MUSIC = (
    "https://oauth.vk.com/authorize?client_id=2685278"
    "&scope=audio,offline"
    "&redirect_uri=https://oauth.vk.com/blank.html"
    "&display=page&response_type=token&revoke=1"
)

# Режимы работы загрузчика
CONTENT_MODES = [
    "Автоопределение (Smart)",
    "Видео / Аудио (YouTube, VK, IG Reels)",
    "Instagram (Фото, Карусели, Reels, Stories)",
    "Галереи и посты (Pinterest, X, Reddit, TikTok)",
    "Фотографии ВК (Альбом)",
    "Музыка ВК (Плейлист / Профиль)",
    "Треки по списку (поиск на YouTube)",
]

# Опции качества видео
QUALITY_PRESETS = [
    "Максимальное (Авто)",
    "4K (2160p)",
    "2K (1440p)",
    "Full HD (1080p)",
    "HD (720p)",
    "SD (480p)",
    "360p",
    "Только аудио (MP3)"
]

# ЭКСПЕРИМЕНТ: вход от имени официального приложения VK для Android (client_id и User-Agent взяты из
# vkpymusic.client.VkMobileClient). Нарушает правила VK и может привести к ограничениям аккаунта.
AUTH_URL_MUSIC_ANDROID = (
    "https://oauth.vk.com/authorize?client_id=2274003"
    "&scope=audio,offline"
    "&redirect_uri=https://oauth.vk.com/blank.html"
    "&display=page&response_type=token&revoke=1"
)
VK_ANDROID_USER_AGENT = "VKAndroidApp/4.13.1-1206 (Android 4.4.3; SDK 19; armeabi; ; ru)"

# User-Agent клиента, выдавшего токен (должен совпадать с клиентом из AUTH_URL_MUSIC)
VK_MUSIC_USER_AGENT = (
    "KateMobileAndroid/56 lite-460 (Android 4.4.2; SDK 19; x86; "
    "unknown Android SDK built for x86; en)"
)


class SettingsManager:
    """Менеджер для сохранения и загрузки локальных настроек приложения (settings.json)."""

    def __init__(self, filepath: str | None = None):
        if filepath is None:
            if getattr(sys, "frozen", False):
                # В .exe папка с кодом временная — храним настройки в профиле пользователя
                filepath = os.path.join(get_app_data_dir(), "settings.json")
            else:
                # Определяем корень проекта относительно src/config.py
                root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                filepath = os.path.join(root_dir, "settings.json")
        self.filepath = filepath

        default_downloads = os.path.join(os.path.expanduser("~"), "Downloads")
        initial_path = default_downloads if os.path.isdir(default_downloads) else os.getcwd()

        self._defaults = {
            "download_path": initial_path,
            "vk_token": "",
            "cookies_path": "",
            "auto_update_ytdlp": True,
        }
        self._data: dict[str, Any] = dict(self._defaults)
        self.load()

    def load(self) -> None:
        """Загружает настройки из JSON-файла."""
        if not os.path.exists(self.filepath):
            return
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    self._data.update(saved)
        except Exception:
            pass

    def save(self) -> None:
        """Сохраняет текущие настройки в JSON-файл."""
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    @property
    def download_path(self) -> str:
        path = self._data.get("download_path")
        if not path or not os.path.exists(path):
            return self._defaults["download_path"]
        return str(path)

    @download_path.setter
    def download_path(self, value: str) -> None:
        if value:
            self._data["download_path"] = os.path.normpath(value)
            self.save()

    # Токены для фото и музыки выдают разные приложения VK, поэтому хранятся отдельно.
    # Старый общий ключ "vk_token" считается токеном для фото.
    def get_vk_token(self, kind: str = "photos") -> str:
        key = f"vk_token_{kind}"
        value = self._data.get(key)
        if value is None and kind == "photos":
            value = self._data.get("vk_token", "")
        return str(value or "").strip()

    def set_vk_token(self, kind: str, value: str) -> None:
        self._data[f"vk_token_{kind}"] = value.strip()
        self.save()

    @property
    def vk_token(self) -> str:
        return self.get_vk_token("photos")

    @vk_token.setter
    def vk_token(self, value: str) -> None:
        self.set_vk_token("photos", value)

    @property
    def cookies_path(self) -> str:
        return str(self._data.get("cookies_path", "")).strip()

    @cookies_path.setter
    def cookies_path(self, value: str) -> None:
        self._data["cookies_path"] = value.strip()
        self.save()

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self.save()
