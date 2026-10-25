"""Главное окно MediaHarvester: собирается из миксинов src/ui/*.py."""
import os
import threading
import customtkinter as ctk
from src.config import (
    AUTH_URL_PHOTOS,
    BG_MAIN,
    CONTENT_MODES,
    SettingsManager,
)
from PIL import Image
from src.core.download_queue import QueueItem
from src.utils.helpers import get_resource_path
from src.utils.logger import register_secret, setup_logging
from src.ui.edit_keys import EditKeysMixin
from src.ui.shell import ShellMixin
from src.ui.info_view import InfoViewMixin
from src.ui.downloader_cards import DownloaderCardsMixin
from src.ui.queue_panel import QueuePanelMixin
from src.ui.tracklist_panel import TracklistPanelMixin
from src.ui.vk_token_panel import VkTokenPanelMixin
from src.version import APP_NAME, __version__
from src.ui.download_runner import DownloadRunnerMixin
from src.ui.engine_status import EngineStatusMixin

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class MediaHarvesterApp(EditKeysMixin, ShellMixin, InfoViewMixin, DownloaderCardsMixin, QueuePanelMixin, TracklistPanelMixin, VkTokenPanelMixin, DownloadRunnerMixin, EngineStatusMixin, ctk.CTk):
    """Окно приложения. Логика разнесена по миксинам; здесь — инициализация состояния и сборка интерфейса."""

    def __init__(self):
        super().__init__()

        setup_logging()
        self.settings = SettingsManager()
        for kind in ("photos", "music"):
            register_secret(self.settings.get_vk_token(kind))
        self.cancel_event = threading.Event()

        self.title(f"{APP_NAME} {__version__}")
        self.geometry("540x780")
        self.minsize(460, 600)
        self.configure(fg_color=BG_MAIN)

        # Иконка окна
        self.icon_path = get_resource_path(os.path.join("assets", "logo.ico"))
        try:
            if os.path.exists(self.icon_path):
                self.iconbitmap(self.icon_path)
        except Exception:
            pass

        # Логотип в заголовок через PIL
        self.logo_image = None
        try:
            if os.path.exists(self.icon_path):
                with Image.open(self.icon_path) as source:
                    pil_img = source.resize((24, 24), Image.Resampling.LANCZOS)
                self.logo_image = ctk.CTkImage(
                    light_image=pil_img, dark_image=pil_img, size=(24, 24)
                )
        except Exception:
            pass

        # Шрифты — Segoe UI
        self.font_title    = ctk.CTkFont(family="Segoe UI", size=15, weight="bold")
        self.font_subtitle = ctk.CTkFont(family="Segoe UI", size=11)
        self.font_section  = ctk.CTkFont(family="Segoe UI", size=11, weight="bold")
        self.font_main     = ctk.CTkFont(family="Segoe UI", size=12)
        self.font_bold     = ctk.CTkFont(family="Segoe UI", size=12, weight="bold")
        self.font_small    = ctk.CTkFont(family="Segoe UI", size=11)
        self.font_mono     = ctk.CTkFont(family="Consolas", size=11)

        # Состояние приложения
        self.download_path: str = self.settings.download_path
        self.is_downloading: bool = False
        self.is_probing: bool = False
        self.last_saved_folder: str | None = None
        self.queue: list[QueueItem] = []
        self._engine_state: dict = {"ytdlp": "", "ffmpeg": None, "update": ""}
        self.last_errors: list[QueueItem] = []
        self.current_screen: str = "downloader"
        self._auth_url: str = AUTH_URL_PHOTOS
        self._tracklist_mode: bool = False  # режим «Треки по списку»: вместо ссылок показывается список
        self._token_kind: str = "photos"   # какой токен показан: "photos", "music" (Kate) или "music_android" (эксперимент)
        self._login_kind: str = "photos"   # для какого вида идёт вход в данный момент
        self._login_busy: bool = False
        self._login_cancel = threading.Event()
        self._clipboard_watch_until: float = 0.0

        # Построение интерфейса
        self.create_header()
        self.create_views_container()
        self.create_downloader_view()
        self.create_info_view()
        self.create_statusbar()

        self.setup_keybindings()
        self.setup_adaptive_resizing()

        # Восстановление сохраненных данных
        saved_token = self.settings.get_vk_token(self._token_kind)
        if saved_token:
            self.entry_token.insert(0, saved_token)

        saved_cookies = self.settings.cookies_path
        if saved_cookies:
            self.entry_cookies_path.configure(state="normal")
            self.entry_cookies_path.insert(0, saved_cookies)
            self.entry_cookies_path.configure(state="readonly")
            self._update_cookies_badge()

        self.show_downloader_view()
        self.combo_mode.set(CONTENT_MODES[0])  # "Автоопределение (Smart)" по умолчанию
        self.on_mode_change(CONTENT_MODES[0])
        self._update_token_badge()

        # Проверки окружения (ffmpeg, обновление yt-dlp) — в фоне, чтобы не задерживать запуск
        self.after(800, lambda: threading.Thread(
            target=self._background_checks, daemon=True).start())
