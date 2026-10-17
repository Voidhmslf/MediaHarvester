import customtkinter as ctk
from tkinter import filedialog
import vk_api
import vk_api.exceptions
import requests
import os
import sys
import shutil
import re
import webbrowser
import threading
from PIL import Image
import yt_dlp

# FFmpeg — для объединения раздельных видео/аудио потоков (1080p, 2K, 4K) и конвертации в MP3
FFMPEG_PATH = None
try:
    import imageio_ffmpeg
    FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_PATH = shutil.which("ffmpeg")

# vkpymusic — для скачивания музыки VK
try:
    from vkpymusic import Service as VkMusicService
    VKPYMUSIC_AVAILABLE = True
except ImportError:
    VKPYMUSIC_AVAILABLE = False

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
AUTH_URL_MUSIC = (
    "https://oauth.vk.com/authorize?client_id=7497650"
    "&scope=audio,offline"
    "&redirect_uri=https://oauth.vk.com/blank.html"
    "&display=page&response_type=token&revoke=1"
)

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

# VK API user-agent, используемый vkpymusic для запросов аудио
VK_MUSIC_USER_AGENT = (
    "VKAndroidApp/8.52-17600 (Android 14; SDK 34; arm64-v8a; "
    "Samsung Galaxy S24; ru; 2960x1440)"
)

# Настройки CustomTkinter
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def get_resource_path(relative_path: str) -> str:
    """Абсолютный путь к ресурсам (PyInstaller / обычный запуск)."""
    try:
        base_path = sys._MEIPASS  # type: ignore[attr-defined]
    except AttributeError:
        base_path = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base_path, relative_path)


def sanitize_filename(name: str) -> str:
    """Убирает из строки символы, недопустимые в именах файлов Windows."""
    return re.sub(r'[\\/*?:"<>|]', "_", name).strip(". ")


def get_video_format_spec(choice: str):
    """Формирует спецификацию формата yt-dlp и пост-процессоры по выбранному качеству."""
    postprocessors = []
    if "Только аудио" in choice:
        fmt = "bestaudio/best"
        if FFMPEG_PATH:
            postprocessors.append({
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            })
    elif "2160p" in choice or "4K" in choice:
        fmt = "bestvideo[height<=2160]+bestaudio/best[height<=2160]/best"
    elif "1440p" in choice or "2K" in choice:
        fmt = "bestvideo[height<=1440]+bestaudio/best[height<=1440]/best"
    elif "1080p" in choice:
        fmt = "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"
    elif "720p" in choice:
        fmt = "bestvideo[height<=720]+bestaudio/best[height<=720]/best"
    elif "480p" in choice:
        fmt = "bestvideo[height<=480]+bestaudio/best[height<=480]/best"
    elif "360p" in choice:
        fmt = "bestvideo[height<=360]+bestaudio/best[height<=360]/best"
    else:
        fmt = "bestvideo+bestaudio/best"
    return fmt, postprocessors


class VKDownloaderApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("VK Media Sync")
        self.geometry("540x720")
        self.minsize(460, 580)
        self.configure(fg_color=BG_MAIN)

        # Иконка окна
        self.icon_path = get_resource_path("logo.ico")
        try:
            if os.path.exists(self.icon_path):
                self.iconbitmap(self.icon_path)
        except Exception:
            pass

        # Логотип в заголовок через PIL
        self.logo_image = None
        try:
            if os.path.exists(self.icon_path):
                pil_img = Image.open(self.icon_path).resize((24, 24), Image.Resampling.LANCZOS)
                self.logo_image = ctk.CTkImage(
                    light_image=pil_img, dark_image=pil_img, size=(24, 24))
        except Exception:
            pass

        # Шрифты — Segoe UI
        self.font_title   = ctk.CTkFont(family="Segoe UI", size=15, weight="bold")
        self.font_subtitle = ctk.CTkFont(family="Segoe UI", size=11)
        self.font_section = ctk.CTkFont(family="Segoe UI", size=11, weight="bold")
        self.font_main    = ctk.CTkFont(family="Segoe UI", size=12)
        self.font_bold    = ctk.CTkFont(family="Segoe UI", size=12, weight="bold")
        self.font_small   = ctk.CTkFont(family="Segoe UI", size=11)
        self.font_mono    = ctk.CTkFont(family="Consolas", size=11)

        # Состояние
        self.download_path   = os.getcwd()
        self.is_downloading  = False
        self.is_probing      = False
        self.last_saved_folder: str | None = None
        self.current_screen  = "downloader"
        self._auth_url       = AUTH_URL_PHOTOS

        # Сборка UI
        self.create_header()
        self.create_views_container()
        self.create_downloader_view()
        self.create_info_view()
        self.create_statusbar()

        self.setup_keybindings()
        self.setup_adaptive_resizing()

        self.show_downloader_view()
        self.on_mode_change("Фотографии (Альбом)")

    # ──────────────────────────────────────────────────────
    # ГОРЯЧИЕ КЛАВИШИ
    # ──────────────────────────────────────────────────────
    def setup_keybindings(self):
        self.bind_all("<Control-v>", self._handle_ctrl_v, add="+")
        self.bind_all("<Control-V>", self._handle_ctrl_v, add="+")

    def _handle_ctrl_v(self, event):
        focused = self.focus_get()
        if focused is getattr(self.entry_token, "_entry", None):
            self.paste_clipboard(self.entry_token)
            return "break"
        if focused is getattr(self.entry_url, "_entry", None):
            self.paste_clipboard(self.entry_url)
            return "break"

    # ──────────────────────────────────────────────────────
    # АДАПТИВНОЕ МАСШТАБИРОВАНИЕ
    # ──────────────────────────────────────────────────────
    def setup_adaptive_resizing(self):
        self.bind("<Configure>", self._on_window_configure)

    def _on_window_configure(self, event=None):
        if event is not None and event.widget is not self:
            return
        w = self.winfo_width()
        card_wrap = max(200, w - 58)
        for attr in ("lbl_token_hint", "lbl_url_hint", "lbl_quality_info"):
            lbl = getattr(self, attr, None)
            if lbl:
                lbl.configure(wraplength=card_wrap)
        if hasattr(self, "info_labels"):
            for lbl in self.info_labels:
                lbl.configure(wraplength=card_wrap)
        if hasattr(self, "lbl_status_text"):
            self.lbl_status_text.configure(wraplength=max(140, w - 200))

    # ──────────────────────────────────────────────────────
    # ХЕДЕР
    # ──────────────────────────────────────────────────────
    def create_header(self):
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=16, pady=(14, 0))

        left = ctk.CTkFrame(hdr, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True)

        if self.logo_image:
            ctk.CTkLabel(left, image=self.logo_image, text="").pack(
                side="left", padx=(0, 10))

        meta = ctk.CTkFrame(left, fg_color="transparent")
        meta.pack(side="left")
        ctk.CTkLabel(meta, text="VK Media Sync", font=self.font_title,
                     text_color=TEXT_MAIN).pack(anchor="w")
        self.lbl_header_sub = ctk.CTkLabel(
            meta, text="Скачивание фото и видео из ВКонтакте",
            font=self.font_subtitle, text_color=TEXT_MUTED)
        self.lbl_header_sub.pack(anchor="w")

        self.btn_nav_info = ctk.CTkButton(
            hdr, text="Справка", width=84, height=30, corner_radius=6,
            font=self.font_small,
            fg_color=SURFACE_CARD, hover_color=SURFACE_CARD_BORDER,
            text_color=TEXT_SECONDARY, border_width=1,
            border_color=SURFACE_CARD_BORDER,
            command=self.toggle_view)
        self.btn_nav_info.pack(side="right")

        # Разделитель под хедером
        sep = ctk.CTkFrame(self, fg_color=SURFACE_CARD_BORDER, height=1,
                           corner_radius=0)
        sep.pack(fill="x", padx=0, pady=(10, 0))

    # ──────────────────────────────────────────────────────
    # КОНТЕЙНЕР ЭКРАНОВ
    # ──────────────────────────────────────────────────────
    def create_views_container(self):
        self.views_container = ctk.CTkFrame(self, fg_color="transparent")
        self.views_container.pack(fill="both", expand=True, padx=14, pady=(8, 0))

    # ──────────────────────────────────────────────────────
    # ЭКРАН 1: ЗАГРУЗЧИК
    # ──────────────────────────────────────────────────────
    def create_downloader_view(self):
        self.main_scroll = ctk.CTkScrollableFrame(
            self.views_container, fg_color="transparent",
            scrollbar_button_color=SURFACE_CARD_BORDER,
            scrollbar_button_hover_color=TEXT_MUTED)
        self._build_mode_card()
        self._build_token_card()
        self._build_url_card()
        self._build_quality_card()
        self._build_folder_card()

        self.btn_download = ctk.CTkButton(
            self.main_scroll, text="Начать скачивание", height=42,
            corner_radius=6, font=self.font_bold,
            fg_color=ACCENT_BLUE, hover_color=ACCENT_BLUE_HOVER,
            text_color=TEXT_MAIN,
            command=self.start_download_thread)
        self.btn_download.pack(fill="x", padx=2, pady=(12, 10))

    # ── Вспомогательные строители карточек ────────────────
    def _card(self, parent, pady=(0, 10)):
        f = ctk.CTkFrame(parent, fg_color=SURFACE_CARD, corner_radius=6,
                         border_width=1, border_color=SURFACE_CARD_BORDER)
        f.pack(fill="x", padx=2, pady=pady)
        return f

    def _section_label(self, parent, text, pady=(10, 6)):
        ctk.CTkLabel(parent, text=text, font=self.font_section,
                     text_color=TEXT_SECONDARY).pack(
            anchor="w", padx=14, pady=pady)

    def _build_mode_card(self):
        card = self._card(self.main_scroll)
        self._section_label(card, "Тип контента")
        self.combo_mode = ctk.CTkOptionMenu(
            card,
            values=["Фотографии (Альбом)", "Видео (ВК / YouTube)",
                    "Музыка (Плейлист / Профиль)"],
            command=self.on_mode_change,
            height=34, corner_radius=6,
            font=self.font_main, dropdown_font=self.font_main,
            fg_color=SURFACE_INNER,
            button_color=SURFACE_CARD_BORDER,
            button_hover_color=SURFACE_INNER_BORDER,
            dropdown_fg_color=SURFACE_CARD,
            dropdown_hover_color=SURFACE_CARD_BORDER,
            dropdown_text_color=TEXT_MAIN,
            text_color=TEXT_MAIN,
            dynamic_resizing=False)
        self.combo_mode.pack(fill="x", padx=14, pady=(0, 12))

    def _build_token_card(self):
        self.card_token = self._card(self.main_scroll)

        # Заголовок + бейдж
        hrow = ctk.CTkFrame(self.card_token, fg_color="transparent")
        hrow.pack(fill="x", padx=14, pady=(10, 6))
        ctk.CTkLabel(hrow, text="Токен доступа ВКонтакте",
                     font=self.font_section,
                     text_color=TEXT_SECONDARY).pack(side="left")
        self.badge_token_status = ctk.CTkLabel(
            hrow, text="Требуется",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            fg_color=SURFACE_INNER, text_color=TEXT_MUTED,
            corner_radius=4, padx=6, pady=2)
        self.badge_token_status.pack(side="right")

        # Кнопка получить токен
        self.btn_auth = ctk.CTkButton(
            self.card_token, text="Получить токен в браузере",
            height=34, corner_radius=6, font=self.font_main,
            fg_color=ACCENT_BLUE, hover_color=ACCENT_BLUE_HOVER,
            text_color=TEXT_MAIN, command=self.open_auth)
        self.btn_auth.pack(fill="x", padx=14, pady=(0, 8))

        # Строка ввода + Вставить
        erow = ctk.CTkFrame(self.card_token, fg_color="transparent")
        erow.pack(fill="x", padx=14, pady=(0, 6))
        self.entry_token = ctk.CTkEntry(
            erow,
            placeholder_text="Вставьте скопированную ссылку или токен...",
            font=self.font_main, height=34, corner_radius=6,
            fg_color=SURFACE_INNER, border_width=1,
            border_color=SURFACE_INNER_BORDER,
            text_color=TEXT_MAIN, placeholder_text_color=TEXT_MUTED)
        self.entry_token.pack(side="left", fill="x", expand=True,
                              padx=(0, 6))
        ctk.CTkButton(
            erow, text="Вставить", width=74, height=34, corner_radius=6,
            font=self.font_small,
            fg_color=SURFACE_CARD_BORDER,
            hover_color=SURFACE_INNER_BORDER,
            text_color=TEXT_SECONDARY,
            command=lambda: self.paste_clipboard(self.entry_token)
        ).pack(side="right")

        # Подсказка
        self.lbl_token_hint = ctk.CTkLabel(
            self.card_token,
            text="Токен извлекается автоматически из скопированной ссылки",
            font=self.font_subtitle, text_color=TEXT_MUTED, justify="left")
        self.lbl_token_hint.pack(anchor="w", padx=14, pady=(0, 10))

    def _build_url_card(self):
        self.card_url = self._card(self.main_scroll)
        self._section_label(self.card_url, "Ссылка на источник")

        erow = ctk.CTkFrame(self.card_url, fg_color="transparent")
        erow.pack(fill="x", padx=14, pady=(0, 6))
        self.entry_url = ctk.CTkEntry(
            erow,
            placeholder_text="Вставьте ссылку (альбом, видео, плейлист...)",
            font=self.font_main, height=34, corner_radius=6,
            fg_color=SURFACE_INNER, border_width=1,
            border_color=SURFACE_INNER_BORDER,
            text_color=TEXT_MAIN, placeholder_text_color=TEXT_MUTED)
        self.entry_url.pack(side="left", fill="x", expand=True,
                            padx=(0, 6))
        ctk.CTkButton(
            erow, text="Вставить", width=74, height=34, corner_radius=6,
            font=self.font_small,
            fg_color=SURFACE_CARD_BORDER,
            hover_color=SURFACE_INNER_BORDER,
            text_color=TEXT_SECONDARY,
            command=lambda: self.paste_clipboard(self.entry_url)
        ).pack(side="right", padx=(6, 0))
        ctk.CTkButton(
            erow, text="Очистить", width=74, height=34, corner_radius=6,
            font=self.font_small,
            fg_color=SURFACE_CARD_BORDER,
            hover_color=SURFACE_INNER_BORDER,
            text_color=TEXT_MUTED,
            command=self._clear_url
        ).pack(side="right")

        self.lbl_url_hint = ctk.CTkLabel(
            self.card_url,
            text="Например: https://vk.com/album-123456_789012",
            font=self.font_subtitle, text_color=TEXT_MUTED, justify="left")
        self.lbl_url_hint.pack(anchor="w", padx=14, pady=(0, 10))

    def _build_quality_card(self):
        """Карточка выбора качества (отображается в режиме Видео)."""
        self.card_quality = self._card(self.main_scroll)
        self._section_label(self.card_quality, "Качество видео")

        qrow = ctk.CTkFrame(self.card_quality, fg_color="transparent")
        qrow.pack(fill="x", padx=14, pady=(0, 6))

        self.combo_quality = ctk.CTkOptionMenu(
            qrow,
            values=QUALITY_PRESETS,
            height=34, corner_radius=6,
            font=self.font_main, dropdown_font=self.font_main,
            fg_color=SURFACE_INNER,
            button_color=SURFACE_CARD_BORDER,
            button_hover_color=SURFACE_INNER_BORDER,
            dropdown_fg_color=SURFACE_CARD,
            dropdown_hover_color=SURFACE_CARD_BORDER,
            dropdown_text_color=TEXT_MAIN,
            text_color=TEXT_MAIN,
            dynamic_resizing=False)
        self.combo_quality.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.btn_probe_quality = ctk.CTkButton(
            qrow, text="Проверить", width=90, height=34, corner_radius=6,
            font=self.font_small,
            fg_color=SURFACE_CARD_BORDER,
            hover_color=SURFACE_INNER_BORDER,
            text_color=TEXT_SECONDARY,
            command=self.probe_video_quality)
        self.btn_probe_quality.pack(side="right")

        self.lbl_quality_info = ctk.CTkLabel(
            self.card_quality,
            text="Нажмите «Проверить» или вставьте ссылку для анализа доступных качеств",
            font=self.font_subtitle, text_color=TEXT_MUTED, justify="left")
        self.lbl_quality_info.pack(anchor="w", padx=14, pady=(0, 10))

    def _build_folder_card(self):
        self.card_folder = self._card(self.main_scroll)
        self._section_label(self.card_folder, "Папка для сохранения")

        row = ctk.CTkFrame(self.card_folder, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 12))

        self.entry_folder_path = ctk.CTkEntry(
            row, font=self.font_mono, height=34, corner_radius=6,
            fg_color=SURFACE_INNER, border_width=1,
            border_color=SURFACE_INNER_BORDER,
            text_color=TEXT_SECONDARY)
        self.entry_folder_path.insert(0, self.download_path)
        self.entry_folder_path.configure(state="readonly")
        self.entry_folder_path.pack(side="left", fill="x", expand=True,
                                    padx=(0, 6))

        ctk.CTkButton(
            row, text="Обзор", width=68, height=34, corner_radius=6,
            font=self.font_small,
            fg_color=SURFACE_CARD_BORDER,
            hover_color=SURFACE_INNER_BORDER,
            text_color=TEXT_SECONDARY,
            command=self.choose_folder
        ).pack(side="right", padx=(6, 0))

        self.btn_open_folder = ctk.CTkButton(
            row, text="Открыть", width=68, height=34, corner_radius=6,
            font=self.font_small,
            fg_color=SURFACE_CARD_BORDER,
            hover_color=SURFACE_INNER_BORDER,
            text_color=TEXT_SECONDARY,
            command=self.open_target_folder)
        self.btn_open_folder.pack(side="right")

    # ── Очистка URL (thread-safe вызов из кнопки — в главном потоке) ──
    def _clear_url(self):
        self.entry_url.delete(0, "end")
        if hasattr(self, "lbl_quality_info"):
            self.lbl_quality_info.configure(
                text="Нажмите «Проверить» или вставьте ссылку для анализа доступных качеств",
                text_color=TEXT_MUTED)

    # ──────────────────────────────────────────────────────
    # АНАЛИЗ ДОСТУПНЫХ КАЧЕСТВ ВИДЕО (ПРОБИНГ)
    # ──────────────────────────────────────────────────────
    def probe_video_quality(self):
        """Проверяет доступные разрешения видео в фоновом потоке."""
        url = self.entry_url.get().strip()
        if not url:
            self.lbl_quality_info.configure(
                text="Сначала вставьте ссылку на видео в поле выше",
                text_color=TEXT_MUTED)
            return

        if self.is_probing:
            return

        self.is_probing = True
        self.btn_probe_quality.configure(state="disabled", text="Анализ...")
        self.lbl_quality_info.configure(
            text="Получение списка доступных разрешений...",
            text_color=TEXT_SECONDARY)

        def _worker():
            try:
                opts = {
                    "noplaylist": True,
                    "quiet": True,
                    "no_warnings": True,
                    "extractor_args": {
                        "youtube": {
                            "player_client": ["tv_embedded", "android", "web"]
                        }
                    }
                }
                if FFMPEG_PATH:
                    opts["ffmpeg_location"] = FFMPEG_PATH

                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)

                formats = info.get("formats", [])
                heights = sorted(list(set(f.get("height") for f in formats if f.get("height"))), reverse=True)
                title = info.get("title", "")

                def _success():
                    if heights:
                        h_str = ", ".join(f"{h}p" for h in heights[:6])
                        title_cut = f" • {title[:24]}..." if title else ""
                        self.lbl_quality_info.configure(
                            text=f"Доступно: {h_str}{title_cut}",
                            text_color=STATUS_GREEN
                        )
                    else:
                        self.lbl_quality_info.configure(
                            text="Видео доступно (наилучшее качество будет выбрано автоматически)",
                            text_color=STATUS_GREEN
                        )
                    self.btn_probe_quality.configure(state="normal", text="Проверить")
                    self.is_probing = False

                self.after(0, _success)
            except Exception:
                def _fail():
                    self.lbl_quality_info.configure(
                        text="Не удалось получить форматы заранее (будет скачано лучшее доступное)",
                        text_color=TEXT_MUTED
                    )
                    self.btn_probe_quality.configure(state="normal", text="Проверить")
                    self.is_probing = False

                self.after(0, _fail)

        threading.Thread(target=_worker, daemon=True).start()

    # ──────────────────────────────────────────────────────
    # ЭКРАН 2: СПРАВКА
    # ──────────────────────────────────────────────────────
    def create_info_view(self):
        self.info_scroll = ctk.CTkScrollableFrame(
            self.views_container, fg_color="transparent",
            scrollbar_button_color=SURFACE_CARD_BORDER,
            scrollbar_button_hover_color=TEXT_MUTED)
        self.info_labels = []

        # Шапка
        hcard = self._info_card(pady=(0, 10))
        hrow = ctk.CTkFrame(hcard, fg_color="transparent")
        hrow.pack(fill="x", padx=14, pady=12)
        ctk.CTkLabel(hrow, text="Руководство по использованию",
                     font=self.font_title,
                     text_color=TEXT_MAIN).pack(side="left")
        ctk.CTkButton(
            hrow, text="Назад", width=74, height=30, corner_radius=6,
            font=self.font_small,
            fg_color=ACCENT_BLUE, hover_color=ACCENT_BLUE_HOVER,
            text_color=TEXT_MAIN,
            command=self.show_downloader_view).pack(side="right")

        self._info_section(
            "1. Скачивание фотоальбомов ВКонтакте",
            "Нажмите «Получить токен в браузере». На открывшейся странице ВК "
            "подтвердите доступ — вас перенаправит на пустую страницу. "
            "Скопируйте весь URL из адресной строки и нажмите «Вставить» "
            "рядом с полем токена — программа извлечёт токен автоматически. "
            "Вставьте ссылку на альбом ВКонтакте и нажмите «Начать скачивание».")

        self._info_section(
            "2. Скачивание видео (ВКонтакте / YouTube)",
            "Токен не требуется — поле можно оставить пустым.\n"
            "Выберите желаемое качество: от 360p до 4K, либо «Только аудио (MP3)».\n"
            "Кнопка «Проверить» позволяет заранее узнать доступные разрешения конкретного ролика.\n"
            "Благодаря встроенному FFmpeg отдельные видео- и аудиодорожки Full HD / 4K "
            "автоматически объединяются в единый файл высокого качества.")

        self._info_section(
            "3. Скачивание музыки VK",
            "Выберите режим «Музыка». Нажмите «Получить токен» — "
            "авторизация будет запрошена с правами на аудио (scope=audio). "
            "После получения токена вставьте:\n"
            "  • Ссылку на плейлист: vk.com/music/playlist/-123456_789\n"
            "  • Или ссылку на профиль: vk.com/id123456\n"
            "Треки скачаются в папку VK_Music_… внутри выбранной директории. "
            "Для работы используется библиотека vkpymusic с поддержкой "
            "зашифрованных HLS-потоков ВКонтакте.")

        self._info_section(
            "Частые ошибки",
            "Альбом возвращает ошибку — проверьте настройки приватности: "
            "альбом должен быть открыт для всех или хотя бы для "
            "авторизованных пользователей.\n"
            "Токен недействителен — получите новый через кнопку «Получить "
            "токен».\n"
            "После успешного скачивания в строке состояния появляется кнопка "
            "«Открыть папку».")

        ctk.CTkButton(
            self.info_scroll, text="Вернуться к скачиванию", height=42,
            corner_radius=6, font=self.font_bold,
            fg_color=ACCENT_BLUE, hover_color=ACCENT_BLUE_HOVER,
            text_color=TEXT_MAIN,
            command=self.show_downloader_view
        ).pack(fill="x", padx=2, pady=(6, 12))

    def _info_card(self, pady=(0, 10)):
        f = ctk.CTkFrame(self.info_scroll, fg_color=SURFACE_CARD,
                         corner_radius=6, border_width=1,
                         border_color=SURFACE_CARD_BORDER)
        f.pack(fill="x", padx=2, pady=pady)
        return f

    def _info_section(self, title: str, body: str):
        card = self._info_card()
        ctk.CTkLabel(card, text=title, font=self.font_section,
                     text_color=TEXT_SECONDARY).pack(
            anchor="w", padx=14, pady=(12, 5))
        lbl = ctk.CTkLabel(card, text=body, font=self.font_main,
                           text_color=TEXT_MUTED, justify="left")
        lbl.pack(anchor="w", padx=14, pady=(0, 12))
        self.info_labels.append(lbl)

    # ──────────────────────────────────────────────────────
    # ПЕРЕКЛЮЧЕНИЕ ЭКРАНОВ
    # ──────────────────────────────────────────────────────
    def show_downloader_view(self):
        self.info_scroll.pack_forget()
        self.main_scroll.pack(fill="both", expand=True)
        self.current_screen = "downloader"
        self.btn_nav_info.configure(
            text="Справка",
            fg_color=SURFACE_CARD, hover_color=SURFACE_CARD_BORDER,
            text_color=TEXT_SECONDARY)
        self.lbl_header_sub.configure(
            text="Скачивание фото и видео из ВКонтакте")

    def show_info_view(self):
        self.main_scroll.pack_forget()
        self.info_scroll.pack(fill="both", expand=True)
        self.current_screen = "info"
        self.btn_nav_info.configure(
            text="Назад",
            fg_color=ACCENT_BLUE, hover_color=ACCENT_BLUE_HOVER,
            text_color=TEXT_MAIN)
        self.lbl_header_sub.configure(text="Руководство по использованию")
        self._on_window_configure()

    def toggle_view(self):
        if self.current_screen == "downloader":
            self.show_info_view()
        else:
            self.show_downloader_view()

    # ──────────────────────────────────────────────────────
    # СТАТУС-БАР
    # ──────────────────────────────────────────────────────
    def create_statusbar(self):
        # Верхняя граница статус-бара
        ctk.CTkFrame(self, fg_color=SURFACE_CARD_BORDER, height=1,
                     corner_radius=0).pack(fill="x", side="bottom")

        sb = ctk.CTkFrame(self, fg_color=SURFACE_CARD, height=58,
                          corner_radius=0)
        sb.pack(fill="x", side="bottom")
        sb.pack_propagate(False)

        top = ctk.CTkFrame(sb, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(8, 4))

        left_sb = ctk.CTkFrame(top, fg_color="transparent")
        left_sb.pack(side="left", fill="x", expand=True)

        self.lbl_status_icon = ctk.CTkLabel(
            left_sb, text="–", font=self.font_small,
            text_color=TEXT_MUTED, width=18)
        self.lbl_status_icon.pack(side="left", padx=(0, 6))

        self.lbl_status_text = ctk.CTkLabel(
            left_sb, text="Готов к работе", font=self.font_small,
            text_color=TEXT_MUTED, anchor="w", justify="left")
        self.lbl_status_text.pack(side="left", fill="x", expand=True)

        right_sb = ctk.CTkFrame(top, fg_color="transparent")
        right_sb.pack(side="right")

        self.lbl_percentage = ctk.CTkLabel(
            right_sb, text="", font=self.font_mono, text_color=TEXT_MUTED)
        self.lbl_percentage.pack(side="right", padx=(6, 0))

        # Кнопка «Открыть папку»
        self.btn_view_downloaded = ctk.CTkButton(
            right_sb, text="Открыть папку", height=24, width=108,
            corner_radius=4, font=self.font_small,
            fg_color=SURFACE_CARD_BORDER, hover_color=ACCENT_BLUE,
            text_color=TEXT_SECONDARY,
            command=self.open_downloaded_folder)
        self._folder_btn_visible = False

        self.progressbar = ctk.CTkProgressBar(
            sb, height=3, corner_radius=2,
            fg_color=SURFACE_INNER,
            progress_color=ACCENT_BLUE, mode="determinate")
        self.progressbar.pack(fill="x", padx=14, pady=(0, 8))
        self.progressbar.set(0)

    # ──────────────────────────────────────────────────────
    # ОБНОВЛЕНИЕ СТАТУС-БАРА (вызывается из любого потока)
    # ──────────────────────────────────────────────────────
    _STATUS_MAP = {
        "idle":    ("–",   TEXT_MUTED,      ACCENT_BLUE),
        "working": ("...", TEXT_SECONDARY,   ACCENT_BLUE),
        "success": ("OK",  STATUS_GREEN,     STATUS_GREEN),
        "error":   ("!",   STATUS_RED,       STATUS_RED),
        "warning": ("~",   STATUS_AMBER,     STATUS_AMBER),
    }

    def update_status(self, text: str, state: str = "idle",
                      progress: float | None = None,
                      percent_str: str = ""):
        icon, text_color, bar_color = self._STATUS_MAP.get(
            state, ("–", TEXT_MUTED, ACCENT_BLUE))

        def _upd():
            self.lbl_status_icon.configure(text=icon, text_color=text_color)
            self.lbl_status_text.configure(text=text, text_color=text_color)
            self.progressbar.configure(progress_color=bar_color)
            if progress is not None:
                self.progressbar.set(progress)
            if percent_str:
                self.lbl_percentage.configure(text=percent_str)
            elif progress is not None:
                self.lbl_percentage.configure(text=f"{int(progress * 100)}%")

        self.after(0, _upd)

    def _show_folder_button(self):
        """Показать кнопку «Открыть папку» (только из главного потока)."""
        if not self._folder_btn_visible:
            self.btn_view_downloaded.pack(side="right", padx=(0, 6))
            self._folder_btn_visible = True

    def _hide_folder_button(self):
        """Скрыть кнопку «Открыть папку» (только из главного потока)."""
        if self._folder_btn_visible:
            self.btn_view_downloaded.pack_forget()
            self._folder_btn_visible = False

    # ──────────────────────────────────────────────────────
    # ЛОГИКА РЕЖИМОВ
    # ──────────────────────────────────────────────────────
    def on_mode_change(self, choice: str):
        if "Фотографии" in choice:
            self._auth_url = AUTH_URL_PHOTOS
            self.badge_token_status.configure(text="Требуется")
            self.btn_auth.configure(fg_color=ACCENT_BLUE,
                                    hover_color=ACCENT_BLUE_HOVER)
            self.lbl_token_hint.configure(
                text="Токен извлекается автоматически из скопированной ссылки")
            self.lbl_url_hint.configure(
                text="Поддерживаются ссылки на любые открытые альбомы ВКонтакте")
            self.card_quality.pack_forget()
            self.update_status("Режим: фотоальбомы", state="idle")

        elif "Видео" in choice:
            self._auth_url = AUTH_URL_PHOTOS
            self.badge_token_status.configure(text="Не требуется")
            self.btn_auth.configure(fg_color=SURFACE_CARD_BORDER,
                                    hover_color=SURFACE_INNER_BORDER)
            self.lbl_token_hint.configure(
                text="Для видео токен не используется, поле можно оставить пустым")
            self.lbl_url_hint.configure(
                text="Ссылки на видеозаписи ВКонтакте, VK Клипы и YouTube")
            # Размещаем карточку качества перед папкой сохранения
            self.card_quality.pack(fill="x", padx=2, pady=(0, 10), before=self.card_folder)
            self.update_status("Режим: видео (ВК / YouTube)", state="idle")

        elif "Музыка" in choice:
            self._auth_url = AUTH_URL_MUSIC
            avail = VKPYMUSIC_AVAILABLE
            self.badge_token_status.configure(
                text="Требуется" if avail else "Недоступно")
            self.btn_auth.configure(
                fg_color=ACCENT_BLUE if avail else SURFACE_CARD_BORDER,
                hover_color=ACCENT_BLUE_HOVER if avail else SURFACE_INNER_BORDER)
            self.lbl_token_hint.configure(
                text=("Токен запрашивается с правами на аудио (scope=audio). "
                      "Вставьте ссылку после авторизации.")
                if avail else
                "Библиотека vkpymusic не установлена. "
                "Запустите: pip install vkpymusic")
            self.lbl_url_hint.configure(
                text="vk.com/music/playlist/-ID_плейлиста  или  vk.com/id12345")
            self.card_quality.pack_forget()
            self.update_status(
                "Режим: музыка VK" if avail else "Ошибка: vkpymusic не найден",
                state="idle" if avail else "error")

        self.update_idletasks()

    # ──────────────────────────────────────────────────────
    # АВТОРИЗАЦИЯ И ВЫБОР ПАПКИ
    # ──────────────────────────────────────────────────────
    def open_auth(self):
        webbrowser.open(self._auth_url)
        self.update_status(
            "Браузер открыт. Скопируйте ссылку после подтверждения",
            state="warning")

    def choose_folder(self):
        folder = filedialog.askdirectory(title="Выберите папку для сохранения")
        if folder:
            self.set_download_path(folder)
            self.update_status(
                f"Папка: {os.path.basename(self.download_path) or self.download_path}",
                state="idle")

    # ──────────────────────────────────────────────────────
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ UI
    # ──────────────────────────────────────────────────────
    def set_download_path(self, folder: str):
        self.download_path = os.path.normpath(folder)
        self.entry_folder_path.configure(state="normal")
        self.entry_folder_path.delete(0, "end")
        self.entry_folder_path.insert(0, self.download_path)
        self.entry_folder_path.configure(state="readonly")

    def paste_clipboard(self, entry_widget):
        """Вставить из буфера обмена. Безопасна только из главного потока."""
        try:
            text = self.clipboard_get().strip()
        except Exception:
            return
        if not text:
            return
        # Авто-извлечение токена из OAuth-redirect URL
        if entry_widget is self.entry_token and "access_token=" in text:
            extracted = self._extract_token(text)
            if extracted:
                text = extracted
        try:
            entry_widget.configure(state="normal")
        except Exception:
            pass
        entry_widget.delete(0, "end")
        entry_widget.insert(0, text)
        entry_widget.focus_set()
        self.update_idletasks()

        # Если вставили ссылку в режиме Видео — запускаем авто-проверку доступных качеств
        if entry_widget is self.entry_url and "Видео" in self.combo_mode.get():
            self.after(300, self.probe_video_quality)

    def open_target_folder(self):
        if os.path.exists(self.download_path):
            os.startfile(self.download_path)

    def open_downloaded_folder(self):
        target = (self.last_saved_folder
                  if self.last_saved_folder
                  and os.path.exists(self.last_saved_folder)
                  else self.download_path)
        if os.path.exists(target):
            os.startfile(target)

    # ──────────────────────────────────────────────────────
    # ПАРСИНГ ДАННЫХ
    # ──────────────────────────────────────────────────────
    def _extract_token(self, s: str) -> str:
        """Извлекает access_token из OAuth-redirect URL или возвращает строку как есть."""
        m = re.search(r"access_token=([^&#]+)", s, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return s.strip()

    def _extract_album_ids(self, url: str):
        """Разбирает ссылку на альбом VK → (owner_id, album_id) или (None, None)."""
        m = re.search(r"album(-?\d+)_([a-zA-Z0-9]+)", url)
        if m:
            oid = m.group(1)
            aid = m.group(2)
            aid = {"0": "profile", "00": "wall", "000": "saved"}.get(aid, aid)
            return oid, aid
        return None, None

    def _extract_music_target(self, url: str):
        """
        Разбирает ссылку для музыкального режима.
        Возвращает dict с ключами:
          type: 'playlist' | 'user'
          owner_id, playlist_id, access_key (для playlist)
          user_id (для user)
        Или None если не распознано.
        """
        m = re.search(r"playlist/(-?\d+)_(\d+)(?:_([a-zA-Z0-9]+))?", url)
        if m:
            return {
                "type": "playlist",
                "owner_id": int(m.group(1)),
                "playlist_id": int(m.group(2)),
                "access_key": m.group(3) or "",
            }
        m = re.search(r"vk\.com/id(\d+)", url)
        if m:
            return {"type": "user", "user_id": int(m.group(1))}
        m = re.match(r"^-?\d+$", url.strip())
        if m:
            return {"type": "user", "user_id": int(url.strip())}
        return None

    # ──────────────────────────────────────────────────────
    # УПРАВЛЕНИЕ ЗАНЯТОСТЬЮ UI (только через self.after из треда!)
    # ──────────────────────────────────────────────────────
    def _set_ui_busy_main(self, busy: bool):
        """Должна вызываться только из главного потока."""
        self.is_downloading = busy
        state = "disabled" if busy else "normal"
        self.btn_download.configure(
            state=state,
            text="Загрузка..." if busy else "Начать скачивание",
            fg_color=SURFACE_INNER if busy else ACCENT_BLUE)
        self.combo_mode.configure(state=state)
        if hasattr(self, "combo_quality"):
            self.combo_quality.configure(state=state)
        if hasattr(self, "btn_probe_quality"):
            self.btn_probe_quality.configure(state=state)
        if busy:
            self._hide_folder_button()

    def _set_busy(self, busy: bool):
        """Thread-safe обёртка над _set_ui_busy_main."""
        self.after(0, self._set_ui_busy_main, busy)

    # ──────────────────────────────────────────────────────
    # ЗАПУСК СКАЧИВАНИЯ
    # ──────────────────────────────────────────────────────
    def start_download_thread(self):
        if self.is_downloading:
            return
        self._set_ui_busy_main(True)
        threading.Thread(target=self._download_process,
                         daemon=True).start()

    def _download_process(self):
        """Основная логика скачивания — выполняется в background-треде."""
        mode       = self.combo_mode.get()
        target_url = self.entry_url.get().strip()
        token_raw  = self.entry_token.get().strip()

        if not target_url:
            self.update_status("Ошибка: вставьте ссылку на источник",
                               state="error")
            self._set_busy(False)
            return

        self.update_status("Подготовка...", state="working",
                           progress=0, percent_str="0%")

        try:
            if "Видео" in mode:
                self._download_video(target_url)
            elif "Музыка" in mode:
                self._download_music(token_raw, target_url)
            else:
                self._download_photos(token_raw, target_url)
        finally:
            self._set_busy(False)

    # ── Видео ─────────────────────────────────────────────
    def _download_video(self, url: str):
        self.update_status("Подключение к источнику...", state="working")

        def hook(d):
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                dl    = d.get("downloaded_bytes", 0)
                if total:
                    p = dl / total
                    self.update_status(f"Загрузка видео: {int(p * 100)}%",
                                       state="working", progress=p)
                else:
                    self.update_status("Загрузка видеопотока...",
                                       state="working")
            elif d["status"] == "finished":
                self.update_status("Обработка и объединение дорожек...",
                                   state="working", progress=0.98)

        quality_choice = self.combo_quality.get()
        fmt, postprocessors = get_video_format_spec(quality_choice)

        opts = {
            "outtmpl":        os.path.join(self.download_path,
                                           "%(title)s.%(ext)s"),
            "quiet":          True,
            "no_warnings":    True,
            "noplaylist":     True,
            "progress_hooks": [hook],
            "format":         fmt,
            "windowsfilenames": True,
            "extractor_args": {
                "youtube": {
                    "player_client": ["tv_embedded", "android", "web"]
                }
            },
        }
        if FFMPEG_PATH:
            opts["ffmpeg_location"] = FFMPEG_PATH
        if postprocessors:
            opts["postprocessors"] = postprocessors

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
            title = info.get("title", "видео") if info else "видео"
            self.last_saved_folder = self.download_path
            self.update_status(f"Готово: {title[:40]}", state="success",
                               progress=1.0, percent_str="100%")
            self.after(0, self._show_folder_button)
        except Exception as e:
            raw_msg = str(e)
            clean_msg = raw_msg
            if "ERROR:" in clean_msg:
                clean_msg = clean_msg.split("ERROR:")[-1].strip()
            if "Video unavailable" in raw_msg or "This video is unavailable" in raw_msg:
                err_text = "Видео недоступно или удалено"
            elif "Private" in raw_msg or "Sign in" in raw_msg or "login" in raw_msg.lower():
                err_text = "Видео приватное или требует авторизации"
            elif "Requested format is not available" in raw_msg:
                err_text = "Выбранное качество недоступно для этого видео"
            else:
                err_text = f"Ошибка: {clean_msg[:50]}"
            self.update_status(err_text, state="error")

    # ── Фотографии ────────────────────────────────────────
    def _download_photos(self, token_raw: str, url: str):
        if not token_raw:
            self.update_status(
                "Ошибка: для фотографий необходим токен", state="error")
            return

        token = self._extract_token(token_raw)
        owner_id, album_id = self._extract_album_ids(url)
        if not owner_id:
            self.update_status(
                "Ошибка: неверный формат ссылки на альбом VK", state="error")
            return

        self.update_status("Подключение к ВКонтакте...", state="working")
        try:
            vk = vk_api.VkApi(token=token).get_api()

            # Получаем название альбома
            album_title = f"VK_Album_{owner_id}_{album_id}"
            try:
                if album_id not in ("profile", "wall", "saved"):
                    info = vk.photos.getAlbums(
                        owner_id=owner_id, album_ids=[album_id])
                    if info.get("items"):
                        name = sanitize_filename(info["items"][0]["title"])
                        if name:
                            album_title = f"VK_{name}_{album_id}"
            except Exception:
                pass

            folder = os.path.join(self.download_path, album_title)
            os.makedirs(folder, exist_ok=True)
            self.last_saved_folder = folder

            # Пагинация: VK API отдаёт максимум 1000 фото за запрос
            all_items = []
            offset = 0
            per_page = 1000
            while True:
                resp = vk.photos.get(
                    owner_id=owner_id, album_id=album_id,
                    count=per_page, offset=offset)
                chunk = resp.get("items", [])
                all_items.extend(chunk)
                if len(chunk) < per_page:
                    break
                offset += per_page

            if not all_items:
                self.update_status(
                    "Альбом пуст или закрыт настройками приватности",
                    state="warning")
                return

            total = len(all_items)
            self.update_status(f"Найдено фото: {total}. Скачивание...",
                               state="working", progress=0)

            downloaded = 0
            for i, photo in enumerate(all_items):
                sizes = photo.get("sizes", [])
                if not sizes:
                    continue
                try:
                    r = requests.get(sizes[-1]["url"], stream=True,
                                     timeout=20)
                    r.raise_for_status()
                    out_path = os.path.join(folder, f"photo_{i + 1:04d}.jpg")
                    with open(out_path, "wb") as f:
                        shutil.copyfileobj(r.raw, f)
                    downloaded += 1
                except Exception:
                    pass
                p = (i + 1) / total
                self.update_status(f"Фото {i + 1} из {total}",
                                   state="working", progress=p,
                                   percent_str=f"{int(p * 100)}%")

            self.update_status(
                f"Готово: скачано {downloaded} из {total} фото",
                state="success", progress=1.0, percent_str="100%")
            self.after(0, self._show_folder_button)

        except vk_api.exceptions.ApiError as e:
            codes = {
                5:  "Недействительный или истекший токен VK.",
                15: "Альбом закрыт настройками приватности.",
                30: "Альбом закрыт настройками приватности.",
            }
            msg = codes.get(e.code, e.error.get("error_msg", str(e)))
            self.update_status(f"Ошибка API: {msg}", state="error")
        except requests.exceptions.ConnectionError:
            self.update_status(
                "Сетевая ошибка. Проверьте подключение к интернету",
                state="error")
        except Exception as e:
            self.update_status(f"Ошибка: {str(e)[:60]}", state="error")

    # ── Музыка ────────────────────────────────────────────
    def _download_music(self, token_raw: str, url: str):
        if not VKPYMUSIC_AVAILABLE:
            self.update_status(
                "Ошибка: установите vkpymusic (pip install vkpymusic)",
                state="error")
            return

        if not token_raw:
            self.update_status(
                "Ошибка: для скачивания музыки необходим токен (scope=audio)",
                state="error")
            return

        token = self._extract_token(token_raw)
        target = self._extract_music_target(url)
        if target is None:
            self.update_status(
                "Ошибка: не удалось распознать ссылку.\n"
                "Используйте vk.com/music/playlist/…  или  vk.com/id…",
                state="error")
            return

        self.update_status("Подключение к VK Music API...", state="working")
        try:
            service = VkMusicService(
                user_agent=VK_MUSIC_USER_AGENT, token=token)

            # Получаем список треков
            if target["type"] == "playlist":
                songs = service.get_songs_by_playlist_id(
                    user_id=target["owner_id"],
                    playlist_id=target["playlist_id"],
                    access_key=target["access_key"],
                    count=100)
            else:
                songs = service.get_songs_by_userid(
                    user_id=target["user_id"], count=100)

            if not songs:
                self.update_status(
                    "Плейлист пуст или недоступен для этого токена",
                    state="warning")
                return

            total = len(songs)
            self.update_status(f"Найдено треков: {total}. Скачивание...",
                               state="working", progress=0)

            # Создаём выходную папку
            if target["type"] == "playlist":
                folder_name = f"VK_Music_playlist_{target['playlist_id']}"
            else:
                folder_name = f"VK_Music_id{target['user_id']}"
            out_folder = os.path.join(self.download_path, folder_name)
            os.makedirs(out_folder, exist_ok=True)
            self.last_saved_folder = out_folder

            original_cwd = os.getcwd()
            os.chdir(out_folder)

            downloaded = 0
            errors = 0
            try:
                for i, song in enumerate(songs):
                    try:
                        result = VkMusicService.save_music(song)
                        if result:
                            music_sub = os.path.join(out_folder, "Music")
                            if os.path.isdir(music_sub):
                                for fn in os.listdir(music_sub):
                                    src = os.path.join(music_sub, fn)
                                    dst = os.path.join(out_folder, fn)
                                    if not os.path.exists(dst):
                                        shutil.move(src, dst)
                                    else:
                                        os.remove(src)
                            downloaded += 1
                        else:
                            errors += 1
                    except Exception:
                        errors += 1

                    p = (i + 1) / total
                    self.update_status(
                        f"Трек {i + 1} из {total}: "
                        f"{getattr(song, 'title', '...')[:30]}",
                        state="working", progress=p,
                        percent_str=f"{int(p * 100)}%")
            finally:
                os.chdir(original_cwd)
                music_sub = os.path.join(out_folder, "Music")
                try:
                    if os.path.isdir(music_sub) and not os.listdir(music_sub):
                        os.rmdir(music_sub)
                except Exception:
                    pass

            if downloaded == 0:
                self.update_status(
                    "Не удалось скачать ни одного трека. "
                    "Возможно, токен не имеет прав audio.",
                    state="error")
            else:
                status_text = f"Готово: {downloaded} из {total} треков"
                if errors:
                    status_text += f" ({errors} ошибок)"
                self.update_status(status_text, state="success",
                                   progress=1.0, percent_str="100%")
                self.after(0, self._show_folder_button)

        except Exception as e:
            err = str(e)
            if "token" in err.lower() or "auth" in err.lower():
                self.update_status(
                    "Ошибка авторизации: получите новый токен с правами audio",
                    state="error")
            else:
                self.update_status(f"Ошибка: {err[:70]}", state="error")


if __name__ == "__main__":
    app = VKDownloaderApp()
    app.mainloop()