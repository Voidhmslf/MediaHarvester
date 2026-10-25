"""Главное окно MediaHarvester: собирается из миксинов src/ui/*.py."""
import os
import threading
import customtkinter as ctk
from src.config import (
    AUTH_URL_PHOTOS,
    CONTENT_MODES,
    SettingsManager,
)
from src.ui import theme
from src.ui.theme import BG_MAIN
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

ctk.set_default_color_theme("blue")


class MediaHarvesterApp(EditKeysMixin, ShellMixin, InfoViewMixin, DownloaderCardsMixin, QueuePanelMixin, TracklistPanelMixin, VkTokenPanelMixin, DownloadRunnerMixin, EngineStatusMixin, ctk.CTk):
    """Окно приложения. Логика разнесена по миксинам; здесь — инициализация состояния и сборка интерфейса."""

    def __init__(self):
        # Тема должна быть выбрана до создания окна и виджетов, иначе окно мигнёт чужим цветом
        theme.apply_theme(SettingsManager().get("theme", "system"))
        super().__init__()

        setup_logging()
        self.settings = SettingsManager()
        self.theme_choice: str = theme.normalize_theme(self.settings.get("theme", "system"))
        for kind in ("photos", "music"):
            register_secret(self.settings.get_vk_token(kind))
        self.cancel_event = threading.Event()

        self.title(f"{APP_NAME} {__version__}")
        # Высота — под рабочую область экрана: иначе на ноутбуках нижняя часть окна уходила бы под панель задач
        height = theme.fit_window_height(self, preferred=820, minimum=540)
        self.geometry(theme.centered_geometry(self, 580, height))
        self.minsize(500, min(640, height))
        self.configure(fg_color=BG_MAIN)

        # Иконка окна
        self.icon_path = get_resource_path(os.path.join("assets", "logo.ico"))
        try:
            if os.path.exists(self.icon_path):
                self.iconbitmap(self.icon_path)
        except Exception:
            pass

        # Логотип (знак + надпись) для шапки и иконка переключателя темы
        self.logo_image = theme.lockup_image(32)
        self.icon_theme = theme.theme_toggle_icon(18)

        # Шрифты бренда (Inter из assets/fonts; без него — системный Segoe UI)
        fonts = theme.build_fonts()
        self.font_title    = fonts.title
        self.font_section  = fonts.section
        self.font_main     = fonts.main
        self.font_medium   = fonts.medium
        self.font_bold     = fonts.bold
        self.font_small    = fonts.small
        self.font_subtitle = fonts.small
        self.font_caption  = fonts.caption
        self.font_mono     = fonts.mono

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
        # Порядок важен для pack: сначала то, что прижато к низу (статус-бар, кнопка), потом растягиваемая область
        self.create_header()
        self.create_statusbar()
        self.create_action_bar()
        self.create_views_container()
        self.create_downloader_view()
        self.create_info_view()

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

        self.after(300, lambda: theme.apply_titlebar(self))

        # Проверки окружения (ffmpeg, обновление yt-dlp) — в фоне, чтобы не задерживать запуск
        self.after(800, lambda: threading.Thread(
            target=self._background_checks, daemon=True).start())
