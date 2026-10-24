import os
import threading
import time
import webbrowser
from tkinter import filedialog
import customtkinter as ctk
from PIL import Image

from src.config import (
    BG_MAIN,
    SURFACE_CARD,
    SURFACE_CARD_BORDER,
    SURFACE_INNER,
    SURFACE_INNER_BORDER,
    ACCENT_BLUE,
    ACCENT_BLUE_HOVER,
    STATUS_GREEN,
    STATUS_RED,
    STATUS_AMBER,
    TEXT_MAIN,
    TEXT_SECONDARY,
    TEXT_MUTED,
    AUTH_URL_PHOTOS,
    AUTH_URL_MUSIC,
    CONTENT_MODES,
    QUALITY_PRESETS,
    SettingsManager,
)
from src.utils.helpers import (
    get_resource_path,
    open_folder,
    check_ffmpeg,
    DownloadCancelledError,
)
from src.utils.ytdlp_updater import current_version as ytdlp_version, check_for_update
from src.core.vk_auth import login_in_window, find_auth_result, fetch_user_name
from src.utils.errors import explain_error
from src.utils.logger import setup_logging, get_logger, get_log_dir, register_secret, redact
from src.utils.report import build_report, format_failures

log = get_logger("app")
from src.core.router import detect_url_type, gallery_platform_name
from src.core.gallery_engine import download_gallery
from src.core.download_queue import (
    QueueItem,
    parse_urls,
    run_queue,
    RUNNABLE,
    PENDING,
    WORKING,
    DONE,
    ERROR,
    CANCELLED,
)
from src.core.ytdlp_engine import (
    probe_video_quality,
    download_video,
)
from src.core.insta_engine import download_instagram
from src.core.vk_engine import (
    extract_token,
    download_vk_photos,
    download_vk_music,
    VKPYMUSIC_AVAILABLE,
)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class MediaHarvesterApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        setup_logging()
        self.settings = SettingsManager()
        register_secret(self.settings.vk_token)
        self.cancel_event = threading.Event()

        self.title("MediaHarvester")
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
                pil_img = Image.open(self.icon_path).resize((24, 24), Image.Resampling.LANCZOS)
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
        saved_token = self.settings.vk_token
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

    # ──────────────────────────────────────────────────────
    # ПРОВЕРКИ ПРИ СТАРТЕ: FFMPEG И YT-DLP
    # ──────────────────────────────────────────────────────
    def _background_checks(self):
        ok, info = check_ffmpeg()
        self._engine_state["ffmpeg"] = (ok, info)
        try:
            self._engine_state["ytdlp"] = ytdlp_version()
        except Exception:
            self._engine_state["ytdlp"] = "?"
        log.info("Окружение: yt-dlp %s, ffmpeg %s (%s)", self._engine_state["ytdlp"], ok, info)
        self.after(0, self._render_engine_info)

        if not ok:
            self.update_status(
                "FFmpeg не найден: видео выше 720p и конвертация в MP3 могут не работать",
                state="warning")

        if not self.settings.get("auto_update_ytdlp", True):
            return
        self._engine_state["update"] = "checking"
        self.after(0, self._render_engine_info)
        result = check_for_update()
        log.info("Проверка обновления yt-dlp: %s %s %s", result.status, result.latest, result.message)
        if result.status == "updated":
            self._engine_state["update"] = f"updated:{result.latest}"
        else:
            self._engine_state["update"] = ""
        self.after(0, self._render_engine_info)

    def _render_engine_info(self):
        st = self._engine_state
        parts, color = [], TEXT_MUTED
        if st["ytdlp"]:
            parts.append(f"yt-dlp {st['ytdlp']}")
        if st["update"] == "checking":
            parts.append("проверка обновлений...")
        elif st["update"].startswith("updated:"):
            parts.append(f"обновлён до {st['update'].split(':', 1)[1]} — перезапустите программу")
            color = STATUS_AMBER
        if st["ffmpeg"] is not None:
            ok, info = st["ffmpeg"]
            parts.append(f"ffmpeg {info}" if ok else f"ffmpeg: {info}")
            if not ok:
                color = STATUS_RED
        self.lbl_engine_info.configure(text=" • ".join(parts), text_color=color)

    def _on_auto_update_toggled(self):
        self.settings.set("auto_update_ytdlp", bool(self.chk_auto_update.get()))

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
        for attr in ("lbl_token_hint", "lbl_url_hint", "lbl_quality_info", "lbl_cookies_hint"):
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
        ctk.CTkLabel(meta, text="MediaHarvester", font=self.font_title,
                     text_color=TEXT_MAIN).pack(anchor="w")
        self.lbl_header_sub = ctk.CTkLabel(
            meta, text="Мультимедийный комбайн: YouTube • VK • Instagram • TikTok • X и другие",
            font=self.font_subtitle, text_color=TEXT_MUTED)
        self.lbl_header_sub.pack(anchor="w")
        self.lbl_engine_info = ctk.CTkLabel(
            meta, text="", font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=TEXT_MUTED)
        self.lbl_engine_info.pack(anchor="w")

        self.btn_nav_info = ctk.CTkButton(
            hdr, text="Справка", width=84, height=30, corner_radius=6,
            font=self.font_small,
            fg_color=SURFACE_CARD, hover_color=SURFACE_CARD_BORDER,
            text_color=TEXT_SECONDARY, border_width=1,
            border_color=SURFACE_CARD_BORDER,
            command=self.toggle_view)
        self.btn_nav_info.pack(side="right")

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
        self._build_url_card()
        self._build_queue_card()
        self._build_quality_card()
        self._build_token_card()
        self._build_cookies_card()
        self._build_folder_card()

        self.btn_download = ctk.CTkButton(
            self.main_scroll, text="Начать скачивание", height=42,
            corner_radius=6, font=self.font_bold,
            fg_color=ACCENT_BLUE, hover_color=ACCENT_BLUE_HOVER,
            text_color=TEXT_MAIN,
            command=self.start_download_thread)
        self.btn_download.pack(fill="x", padx=2, pady=(12, 10))

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
        self._section_label(card, "Режим загрузки")
        self.combo_mode = ctk.CTkOptionMenu(
            card,
            values=CONTENT_MODES,
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

    def _build_url_card(self):
        self.card_url = self._card(self.main_scroll)

        # Заголовок + Бейдж автоопределения
        hrow = ctk.CTkFrame(self.card_url, fg_color="transparent")
        hrow.pack(fill="x", padx=14, pady=(10, 6))
        ctk.CTkLabel(hrow, text="Ссылка на источник",
                     font=self.font_section,
                     text_color=TEXT_SECONDARY).pack(side="left")
        self.badge_detected = ctk.CTkLabel(
            hrow, text="Ожидание ссылки",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            fg_color=SURFACE_INNER, text_color=TEXT_MUTED,
            corner_radius=4, padx=6, pady=2)
        self.badge_detected.pack(side="right")

        erow = ctk.CTkFrame(self.card_url, fg_color="transparent")
        erow.pack(fill="x", padx=14, pady=(0, 6))
        self.entry_url = ctk.CTkEntry(
            erow,
            placeholder_text="Вставьте ссылку (YouTube, TikTok, Instagram, VK, X...)",
            font=self.font_main, height=34, corner_radius=6,
            fg_color=SURFACE_INNER, border_width=1,
            border_color=SURFACE_INNER_BORDER,
            text_color=TEXT_MAIN, placeholder_text_color=TEXT_MUTED)
        self.entry_url.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.entry_url.bind("<KeyRelease>", self._on_url_changed)
        self.entry_url.bind("<Return>", lambda e: self.add_entry_to_queue())

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

        self.btn_add_queue = ctk.CTkButton(
            self.card_url, text="+ Добавить в очередь (Enter)", height=30,
            corner_radius=6, font=self.font_small,
            fg_color=SURFACE_CARD_BORDER,
            hover_color=SURFACE_INNER_BORDER,
            text_color=TEXT_SECONDARY,
            command=self.add_entry_to_queue)
        self.btn_add_queue.pack(fill="x", padx=14, pady=(0, 6))

        self.lbl_url_hint = ctk.CTkLabel(
            self.card_url,
            text=("Поддерживаются YouTube, TikTok, Instagram, X, Pinterest, Reddit, SoundCloud, фото и музыка VK. "
                  "Можно вставить сразу несколько ссылок — они попадут в очередь"),
            font=self.font_subtitle, text_color=TEXT_MUTED, justify="left")
        self.lbl_url_hint.pack(anchor="w", padx=14, pady=(0, 10))

    # ──────────────────────────────────────────────────────
    # ОЧЕРЕДЬ ССЫЛОК
    # ──────────────────────────────────────────────────────
    _QUEUE_ICONS = {
        PENDING:   ("•",   TEXT_MUTED),
        WORKING:   ("...", TEXT_SECONDARY),
        DONE:      ("OK",  STATUS_GREEN),
        ERROR:     ("!",   STATUS_RED),
        CANCELLED: ("~",   STATUS_AMBER),
    }

    def _build_queue_card(self):
        # Карточка показывается только когда в очереди есть элементы (см. _refresh_queue_view)
        self.card_queue = ctk.CTkFrame(
            self.main_scroll, fg_color=SURFACE_CARD, corner_radius=6,
            border_width=1, border_color=SURFACE_CARD_BORDER)

        hrow = ctk.CTkFrame(self.card_queue, fg_color="transparent")
        hrow.pack(fill="x", padx=14, pady=(10, 6))
        self.lbl_queue_title = ctk.CTkLabel(
            hrow, text="Очередь", font=self.font_section, text_color=TEXT_SECONDARY)
        self.lbl_queue_title.pack(side="left")

        self.btn_queue_clear = ctk.CTkButton(
            hrow, text="Очистить", width=70, height=24, corner_radius=4,
            font=self.font_small, fg_color=SURFACE_CARD_BORDER,
            hover_color=SURFACE_INNER_BORDER, text_color=TEXT_MUTED,
            command=self.clear_queue)
        self.btn_queue_clear.pack(side="right")
        self.btn_queue_clean_done = ctk.CTkButton(
            hrow, text="Убрать готовые", width=104, height=24, corner_radius=4,
            font=self.font_small, fg_color=SURFACE_CARD_BORDER,
            hover_color=SURFACE_INNER_BORDER, text_color=TEXT_MUTED,
            command=self.remove_done_from_queue)
        self.btn_queue_clean_done.pack(side="right", padx=(0, 6))

        self.queue_rows = ctk.CTkFrame(self.card_queue, fg_color="transparent")
        self.queue_rows.pack(fill="x", padx=14, pady=(0, 10))

    def _enqueue_text(self, text: str) -> int:
        """Добавляет ссылки из текста в очередь (без дублей). Возвращает число добавленных."""
        urls = parse_urls(text) or ([text.strip()] if text.strip() else [])
        known = {it.url for it in self.queue}
        added = 0
        for url in urls:
            if url in known:
                continue
            known.add(url)
            self.queue.append(QueueItem(url=url, label=detect_url_type(url)["label"]))
            added += 1
        self._refresh_queue_view()
        return added

    def add_entry_to_queue(self):
        text = self.entry_url.get().strip()
        if not text or self.is_downloading:
            return
        added = self._enqueue_text(text)
        self._clear_url()
        self.update_status(
            f"В очередь добавлено: {added}" if added else "Эта ссылка уже в очереди",
            state="idle")

    def clear_queue(self):
        if self.is_downloading:
            return
        self.queue.clear()
        self._refresh_queue_view()

    def remove_done_from_queue(self):
        if self.is_downloading:
            return
        self.queue = [it for it in self.queue if it.status != DONE]
        self._refresh_queue_view()

    def remove_queue_item(self, item: QueueItem):
        if self.is_downloading or item not in self.queue:
            return
        self.queue.remove(item)
        self._refresh_queue_view()

    def _refresh_queue_view(self):
        if not self.queue:
            self.card_queue.pack_forget()
            return

        if not self.card_queue.winfo_ismapped():
            self.card_queue.pack(fill="x", padx=2, pady=(0, 10), after=self.card_url)

        done = sum(1 for it in self.queue if it.status == DONE)
        self.lbl_queue_title.configure(text=f"Очередь: {done} из {len(self.queue)}")

        for child in self.queue_rows.winfo_children():
            child.destroy()

        for item in self.queue:
            icon, color = self._QUEUE_ICONS.get(item.status, ("•", TEXT_MUTED))
            row = ctk.CTkFrame(self.queue_rows, fg_color=SURFACE_INNER, corner_radius=4)
            row.pack(fill="x", pady=2)

            ctk.CTkLabel(row, text=icon, width=26, font=self.font_small,
                         text_color=color).pack(side="left", padx=(6, 0))

            short = item.url if len(item.url) <= 46 else item.url[:43] + "..."
            text_col = ctk.CTkFrame(row, fg_color="transparent")
            text_col.pack(side="left", fill="x", expand=True, padx=4, pady=3)
            ctk.CTkLabel(text_col, text=short, font=self.font_small,
                         text_color=TEXT_MAIN, anchor="w").pack(fill="x")
            sub = item.message[:60] if item.status == ERROR and item.message else item.label
            ctk.CTkLabel(text_col, text=sub, font=ctk.CTkFont(family="Segoe UI", size=10),
                         text_color=STATUS_RED if item.status == ERROR else TEXT_MUTED,
                         anchor="w").pack(fill="x")

            ctk.CTkButton(
                row, text="✕", width=26, height=24, corner_radius=4,
                font=self.font_small, fg_color="transparent",
                hover_color=SURFACE_CARD_BORDER, text_color=TEXT_MUTED,
                state="disabled" if self.is_downloading else "normal",
                command=lambda it=item: self.remove_queue_item(it)
            ).pack(side="right", padx=4)

    def _build_quality_card(self):
        self.card_quality = self._card(self.main_scroll)
        self._section_label(self.card_quality, "Качество видео / аудио")

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
            command=self.start_probe_quality_thread)
        self.btn_probe_quality.pack(side="right")

        # Чекбокс загрузки плейлистов
        self.chk_playlist = ctk.CTkCheckBox(
            self.card_quality,
            text="Скачивать весь плейлист (если ссылка содержит список)",
            font=self.font_small,
            text_color=TEXT_SECONDARY,
            fg_color=ACCENT_BLUE,
            hover_color=ACCENT_BLUE_HOVER)
        self.chk_playlist.pack(anchor="w", padx=14, pady=(2, 6))

        self.lbl_quality_info = ctk.CTkLabel(
            self.card_quality,
            text="Нажмите «Проверить» или вставьте ссылку для анализа доступных качеств",
            font=self.font_subtitle, text_color=TEXT_MUTED, justify="left")
        self.lbl_quality_info.pack(anchor="w", padx=14, pady=(0, 10))

    def _build_token_card(self):
        self.card_token = self._card(self.main_scroll)

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

        self.btn_auth = ctk.CTkButton(
            self.card_token, text="Войти через ВКонтакте",
            height=34, corner_radius=6, font=self.font_main,
            fg_color=ACCENT_BLUE, hover_color=ACCENT_BLUE_HOVER,
            text_color=TEXT_MAIN, command=self.start_browser_login)
        self.btn_auth.pack(fill="x", padx=14, pady=(0, 4))

        self.btn_auth_window = ctk.CTkButton(
            self.card_token, text="Войти во встроенном окне (может не сработать)",
            height=24, corner_radius=4, font=self.font_small,
            fg_color="transparent", hover_color=SURFACE_CARD_BORDER,
            text_color=TEXT_MUTED, command=self.start_vk_login)
        self.btn_auth_window.pack(fill="x", padx=14, pady=(0, 8))

        erow = ctk.CTkFrame(self.card_token, fg_color="transparent")
        erow.pack(fill="x", padx=14, pady=(0, 6))
        self.entry_token = ctk.CTkEntry(
            erow,
            placeholder_text="...или вставьте ссылку/токен вручную",
            font=self.font_main, height=34, corner_radius=6,
            fg_color=SURFACE_INNER, border_width=1,
            border_color=SURFACE_INNER_BORDER,
            text_color=TEXT_MAIN, placeholder_text_color=TEXT_MUTED)
        self.entry_token.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.entry_token.bind("<KeyRelease>", self._on_token_changed)

        ctk.CTkButton(
            erow, text="Вставить", width=74, height=34, corner_radius=6,
            font=self.font_small,
            fg_color=SURFACE_CARD_BORDER,
            hover_color=SURFACE_INNER_BORDER,
            text_color=TEXT_SECONDARY,
            command=lambda: self.paste_clipboard(self.entry_token)
        ).pack(side="right")

        self.lbl_token_hint = ctk.CTkLabel(
            self.card_token,
            text=self._TOKEN_HINT,
            font=self.font_subtitle, text_color=TEXT_MUTED, justify="left")
        self.lbl_token_hint.pack(anchor="w", padx=14, pady=(0, 10))

    def _build_cookies_card(self):
        """Компактная карточка настройки Cookies для Instagram и возрастных видео YouTube."""
        self.card_cookies = self._card(self.main_scroll)

        hrow = ctk.CTkFrame(self.card_cookies, fg_color="transparent")
        hrow.pack(fill="x", padx=14, pady=(10, 6))
        ctk.CTkLabel(hrow, text="Файл Cookies (Instagram / YouTube 18+)",
                     font=self.font_section,
                     text_color=TEXT_SECONDARY).pack(side="left")
        self.badge_cookies_status = ctk.CTkLabel(
            hrow, text="Не задан",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            fg_color=SURFACE_INNER, text_color=TEXT_MUTED,
            corner_radius=4, padx=6, pady=2)
        self.badge_cookies_status.pack(side="right")

        erow = ctk.CTkFrame(self.card_cookies, fg_color="transparent")
        erow.pack(fill="x", padx=14, pady=(0, 6))

        self.entry_cookies_path = ctk.CTkEntry(
            erow,
            font=self.font_mono, height=34, corner_radius=6,
            fg_color=SURFACE_INNER, border_width=1,
            border_color=SURFACE_INNER_BORDER,
            text_color=TEXT_SECONDARY,
            placeholder_text="Путь к файлу cookies.txt...")
        self.entry_cookies_path.configure(state="readonly")
        self.entry_cookies_path.pack(side="left", fill="x", expand=True, padx=(0, 6))

        ctk.CTkButton(
            erow, text="Обзор", width=68, height=34, corner_radius=6,
            font=self.font_small,
            fg_color=SURFACE_CARD_BORDER,
            hover_color=SURFACE_INNER_BORDER,
            text_color=TEXT_SECONDARY,
            command=self.choose_cookies_file
        ).pack(side="right", padx=(6, 0))

        ctk.CTkButton(
            erow, text="Сбросить", width=68, height=34, corner_radius=6,
            font=self.font_small,
            fg_color=SURFACE_CARD_BORDER,
            hover_color=SURFACE_INNER_BORDER,
            text_color=TEXT_MUTED,
            command=self.clear_cookies_file
        ).pack(side="right")

        self.lbl_cookies_hint = ctk.CTkLabel(
            self.card_cookies,
            text="Для скачивания приватных постов Instagram, каруселей и видео 18+",
            font=self.font_subtitle, text_color=TEXT_MUTED, justify="left")
        self.lbl_cookies_hint.pack(anchor="w", padx=14, pady=(0, 10))

    def _build_folder_card(self):
        self.card_folder = self._card(self.main_scroll)
        self._section_label(self.card_folder, "Папка для сохранения")

        row = ctk.CTkFrame(self.card_folder, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 6))

        self.entry_folder_path = ctk.CTkEntry(
            row, font=self.font_mono, height=34, corner_radius=6,
            fg_color=SURFACE_INNER, border_width=1,
            border_color=SURFACE_INNER_BORDER,
            text_color=TEXT_SECONDARY)
        self.entry_folder_path.insert(0, self.download_path)
        self.entry_folder_path.configure(state="readonly")
        self.entry_folder_path.pack(side="left", fill="x", expand=True, padx=(0, 6))

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

        self.chk_auto_update = ctk.CTkCheckBox(
            self.card_folder, text="Автоматически обновлять yt-dlp",
            font=self.font_small, text_color=TEXT_SECONDARY,
            fg_color=ACCENT_BLUE, hover_color=ACCENT_BLUE_HOVER,
            command=self._on_auto_update_toggled)
        if self.settings.get("auto_update_ytdlp", True):
            self.chk_auto_update.select()
        self.chk_auto_update.pack(anchor="w", padx=14, pady=(0, 12))

    def _clear_url(self):
        self.entry_url.delete(0, "end")
        self._on_url_changed()

    def _on_url_changed(self, event=None):
        url = self.entry_url.get().strip()
        detected = detect_url_type(url)

        # Обновление статус-бейджа роутера
        if not url:
            self.badge_detected.configure(
                text="Ожидание ссылки", text_color=TEXT_MUTED, fg_color=SURFACE_INNER)
        else:
            self.badge_detected.configure(
                text=detected["label"], text_color=STATUS_GREEN, fg_color=SURFACE_INNER)

        # Если включен режим автоопределения, адаптируем видимость карточек
        current_mode = self.combo_mode.get()
        if "Автоопределение" in current_mode:
            self._apply_smart_routing(detected)

    def _apply_smart_routing(self, detected: dict):
        engine = detected.get("engine", "none")

        if engine in ("vk_photos", "vk_music"):
            self._auth_url = AUTH_URL_PHOTOS if engine == "vk_photos" else AUTH_URL_MUSIC
            self.card_quality.pack_forget()
            if not self.card_token.winfo_ismapped():
                self.card_token.pack(fill="x", padx=2, pady=(0, 10), before=self.card_cookies)
            self._update_token_badge()
        elif engine in ("insta", "gallery"):
            self.card_quality.pack_forget()
            self.card_token.pack_forget()
        elif engine == "ytdlp":
            if not self.card_quality.winfo_ismapped():
                self.card_quality.pack(fill="x", padx=2, pady=(0, 10), before=self.card_cookies)
            self.card_token.pack_forget()
        else:
            # По умолчанию в Smart-режиме держим карточку качества видимой
            if not self.card_quality.winfo_ismapped():
                self.card_quality.pack(fill="x", padx=2, pady=(0, 10), before=self.card_cookies)
            self.card_token.pack_forget()

        self.update_idletasks()

    # ──────────────────────────────────────────────────────
    # УПРАВЛЕНИЕ COOKIES
    # ──────────────────────────────────────────────────────
    def choose_cookies_file(self):
        filename = filedialog.askopenfilename(
            title="Выберите файл cookies.txt",
            filetypes=[("Text files (*.txt)", "*.txt"), ("All files", "*.*")]
        )
        if filename:
            self.settings.cookies_path = filename
            self.entry_cookies_path.configure(state="normal")
            self.entry_cookies_path.delete(0, "end")
            self.entry_cookies_path.insert(0, filename)
            self.entry_cookies_path.configure(state="readonly")
            self._update_cookies_badge()
            self.update_status(f"Cookies сохранены: {os.path.basename(filename)}", state="idle")

    def clear_cookies_file(self):
        self.settings.cookies_path = ""
        self.entry_cookies_path.configure(state="normal")
        self.entry_cookies_path.delete(0, "end")
        self.entry_cookies_path.configure(state="readonly")
        self._update_cookies_badge()
        self.update_status("Cookies сброшены", state="idle")

    def _update_cookies_badge(self):
        c_path = self.settings.cookies_path
        if c_path and os.path.isfile(c_path):
            self.badge_cookies_status.configure(
                text="Настроен", text_color=STATUS_GREEN, fg_color=SURFACE_INNER)
        else:
            self.badge_cookies_status.configure(
                text="Не задан", text_color=TEXT_MUTED, fg_color=SURFACE_INNER)

    # ──────────────────────────────────────────────────────
    # ПРОБИНГ КАЧЕСТВА ВИДЕО
    # ──────────────────────────────────────────────────────
    def start_probe_quality_thread(self):
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

        cookies = self.settings.cookies_path

        def _worker():
            try:
                heights, title = probe_video_quality(url, cookies_path=cookies)

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

        hcard = self._info_card(pady=(0, 10))
        hrow = ctk.CTkFrame(hcard, fg_color="transparent")
        hrow.pack(fill="x", padx=14, pady=12)
        ctk.CTkLabel(hrow, text="Руководство MediaHarvester",
                     font=self.font_title,
                     text_color=TEXT_MAIN).pack(side="left")
        ctk.CTkButton(
            hrow, text="Назад", width=74, height=30, corner_radius=6,
            font=self.font_small,
            fg_color=ACCENT_BLUE, hover_color=ACCENT_BLUE_HOVER,
            text_color=TEXT_MAIN,
            command=self.show_downloader_view).pack(side="right")

        self._info_section(
            "1. Умное автоопределение (Smart Mode)",
            "Вставьте любую ссылку на видео, пост или музыку — MediaHarvester "
            "самостоятельно определит платформу (YouTube, TikTok, Instagram, X, Pinterest, Reddit, SoundCloud, VK) "
            "и подберёт оптимальный модуль скачивания без необходимости "
            "вручную переключать режим.")

        self._info_section(
            "Другие платформы: TikTok, X, Pinterest, Reddit, SoundCloud",
            "Просто вставьте ссылку — тип определится сам. Видео берутся через yt-dlp, фото и галереи "
            "через gallery-dl, и программа сама переключается между ними, если пост оказался не тем.\n"
            "Ссылки на списки (плейлист SoundCloud, профиль TikTok) скачиваются целиком. "
            "Страницы-ленты (доска Pinterest, профиль X, сабреддит) ограничены первыми 500 файлами. "
            "Для X и закрытого контента может понадобиться cookies.txt.")

        self._info_section(
            "Если что-то не скачалось",
            "В строке статуса — короткая причина, а кнопка «Подробнее» показывает, что делать, "
            "и техническую причину по каждой ссылке. «Скопировать отчёт» собирает всё для разработчика: "
            "версии, ошибки и последние строки лога (токены и ключи в ссылках скрываются).\n"
            "Лог хранится в %LOCALAPPDATA%\\MediaHarvester\\logs — откройте его кнопкой в окне «Подробнее».")

        self._info_section(
            "Очередь ссылок",
            "Вставьте сразу несколько ссылок (по одной в строке) или нажимайте Enter / "
            "«Добавить в очередь» после каждой. «Начать скачивание» скачает всё по порядку; "
            "ошибка на одной ссылке не останавливает остальные. Неудавшиеся ссылки остаются "
            "в списке — повторный запуск скачает только их. «Остановить» прерывает всю очередь.")

        self._info_section(
            "2. Безопасная отмена загрузки",
            "Во время любого скачивания кнопка меняется на «Остановить скачивание». "
            "При нажатии процесс завершается корректно и безопасно, сохраняя уже загруженные файлы "
            "и не подвешивая графический интерфейс.")

        self._info_section(
            "3. Instagram (Фото, Карусели, Reels, Stories)",
            "Поддерживается скачивание одиночных фотопостов, каруселей "
            "(содержащих фото и видео вместе), Stories и Reels в максимальном качестве.\n"
            "Если пост находится в закрытом аккаунте или Instagram блокирует гостевой доступ, "
            "экспортируйте файл cookies.txt из браузера и укажите его в блоке Cookies.")

        self._info_section(
            "4. Экспорт cookies.txt для Instagram и YouTube 18+",
            "Для скачивания контента, требующего авторизации:\n"
            "  1. Установите расширение для браузера (например, «Get cookies.txt LOCALLY» в Chrome/Firefox).\n"
            "  2. Авторизуйтесь на сайте Instagram или YouTube.\n"
            "  3. Нажмите на иконку расширения и сохраните файл cookies.txt.\n"
            "  4. В MediaHarvester нажмите «Обзор» в блоке Cookies и выберите этот файл.")

        self._info_section(
            "5. Скачивание видео и аудио (YouTube • VK • IG Reels)",
            "Выберите желаемое качество: от 360p до 4K, либо «Только аудио (MP3)» в битрейте 320 kbps.\n"
            "При скачивании в MP3 в файл автоматически встраиваются ID3-теги исполнителя и трека.\n"
            "Включите чекбокс «Скачивать весь плейлист», чтобы сохранить все ролики подборки в отдельную папку.")

        self._info_section(
            "6. Скачивание музыки и фотоальбомов ВКонтакте",
            "Для доступа к фотоальбомам и музыке VK нажмите «Войти через ВКонтакте»: откроется ваш браузер "
            "со страницей VK. Нажмите «Продолжить», затем скопируйте адрес страницы (Ctrl+L, Ctrl+C) — "
            "программа сама заберёт токен из буфера обмена и очистит его. "
            "Логин и пароль программа не видит и не хранит.\n"
            "Кнопка «Войти во встроенном окне» — запасной способ: VK ID не всегда отдаёт токен во встроенном окне.\n"
            "Для музыки нужен вход именно в режиме «Музыка» (другое право доступа). "
            "Поддерживаются плейлисты и аудиозаписи профилей до 1000 треков.")

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
            text="Мультимедийный комбайн: YouTube • VK • Instagram • TikTok • X и другие")

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

        self.btn_view_downloaded = ctk.CTkButton(
            right_sb, text="Открыть папку", height=24, width=108,
            corner_radius=4, font=self.font_small,
            fg_color=SURFACE_CARD_BORDER, hover_color=ACCENT_BLUE,
            text_color=TEXT_SECONDARY,
            command=self.open_downloaded_folder)
        self._folder_btn_visible = False

        self.btn_details = ctk.CTkButton(
            right_sb, text="Подробнее", height=24, width=84,
            corner_radius=4, font=self.font_small,
            fg_color=SURFACE_CARD_BORDER, hover_color=STATUS_RED,
            text_color=TEXT_SECONDARY,
            command=self.show_error_details)
        self._details_btn_visible = False

        self.progressbar = ctk.CTkProgressBar(
            sb, height=3, corner_radius=2,
            fg_color=SURFACE_INNER,
            progress_color=ACCENT_BLUE, mode="determinate")
        self.progressbar.pack(fill="x", padx=14, pady=(0, 8))
        self.progressbar.set(0)

    # ──────────────────────────────────────────────────────
    # ОБНОВЛЕНИЕ СТАТУС-БАРА (Thread-safe)
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
        if not self._folder_btn_visible:
            self.btn_view_downloaded.pack(side="right", padx=(0, 6))
            self._folder_btn_visible = True

    def _show_details_button(self):
        if not self._details_btn_visible:
            self.btn_details.pack(side="right", padx=(0, 6))
            self._details_btn_visible = True

    def _hide_details_button(self):
        if self._details_btn_visible:
            self.btn_details.pack_forget()
            self._details_btn_visible = False

    # ──────────────────────────────────────────────────────
    # ОКНО «ПОДРОБНЕЕ» ОБ ОШИБКАХ
    # ──────────────────────────────────────────────────────
    def show_error_details(self):
        items = self.last_errors
        if not items:
            return
        win = ctk.CTkToplevel(self)
        win.title("Что пошло не так")
        win.geometry("560x480")
        win.minsize(420, 320)
        win.configure(fg_color=BG_MAIN)
        win.transient(self)
        try:
            if os.path.exists(self.icon_path):
                win.after(250, lambda: win.iconbitmap(self.icon_path))
        except Exception:
            pass

        ctk.CTkLabel(
            win, text=f"Не удалось скачать: {len(items)}", font=self.font_title,
            text_color=TEXT_MAIN).pack(anchor="w", padx=16, pady=(14, 6))

        box = ctk.CTkTextbox(
            win, font=self.font_mono, fg_color=SURFACE_INNER, text_color=TEXT_SECONDARY,
            border_width=1, border_color=SURFACE_INNER_BORDER, wrap="word")
        box.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        box.insert("1.0", format_failures(items))
        box.configure(state="disabled")

        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(fill="x", padx=16, pady=(0, 14))

        def copy_report():
            self.clipboard_clear()
            self.clipboard_append(build_report(items, self._engine_state))
            btn_copy.configure(text="Скопировано")

        btn_copy = ctk.CTkButton(
            btns, text="Скопировать отчёт", height=32, corner_radius=6, font=self.font_small,
            fg_color=ACCENT_BLUE, hover_color=ACCENT_BLUE_HOVER, text_color=TEXT_MAIN,
            command=copy_report)
        btn_copy.pack(side="left")
        ctk.CTkButton(
            btns, text="Открыть папку логов", height=32, corner_radius=6, font=self.font_small,
            fg_color=SURFACE_CARD_BORDER, hover_color=SURFACE_INNER_BORDER,
            text_color=TEXT_SECONDARY, command=lambda: open_folder(get_log_dir())
        ).pack(side="left", padx=(8, 0))
        ctk.CTkButton(
            btns, text="Закрыть", width=84, height=32, corner_radius=6, font=self.font_small,
            fg_color=SURFACE_CARD_BORDER, hover_color=SURFACE_INNER_BORDER,
            text_color=TEXT_SECONDARY, command=win.destroy
        ).pack(side="right")

    def report_callback_exception(self, exc, val, tb):
        """Ошибки в обработчиках Tk: пишем в лог вместо молчаливого вывода в консоль."""
        log.critical("Ошибка в обработчике интерфейса", exc_info=(exc, val, tb))

    def _hide_folder_button(self):
        if self._folder_btn_visible:
            self.btn_view_downloaded.pack_forget()
            self._folder_btn_visible = False

    # ──────────────────────────────────────────────────────
    # ЛОГИКА РЕЖИМОВ
    # ──────────────────────────────────────────────────────
    def on_mode_change(self, choice: str):
        url = self.entry_url.get().strip()
        detected = detect_url_type(url)

        if "Автоопределение" in choice:
            self._apply_smart_routing(detected)
            self.update_status("Режим: Умное автоопределение (Smart)", state="idle")

        elif "Видео" in choice:
            self._auth_url = AUTH_URL_PHOTOS
            self.card_token.pack_forget()
            if not self.card_quality.winfo_ismapped():
                self.card_quality.pack(fill="x", padx=2, pady=(0, 10), before=self.card_cookies)
            self.update_status("Режим: видео / аудио (ВК / YouTube / Reels)", state="idle")

        elif "Instagram" in choice:
            self.card_token.pack_forget()
            self.card_quality.pack_forget()
            self.update_status("Режим: Instagram (Фото, Карусели, Reels, Stories)", state="idle")

        elif "Галереи" in choice:
            self.card_token.pack_forget()
            self.card_quality.pack_forget()
            self.update_status("Режим: галереи и посты (Pinterest, X, Reddit, TikTok)", state="idle")

        elif "Фотографии" in choice:
            self._auth_url = AUTH_URL_PHOTOS
            self.card_quality.pack_forget()
            if not self.card_token.winfo_ismapped():
                self.card_token.pack(fill="x", padx=2, pady=(0, 10), before=self.card_cookies)
            self.btn_auth.configure(fg_color=ACCENT_BLUE, hover_color=ACCENT_BLUE_HOVER)
            self.lbl_token_hint.configure(text=self._TOKEN_HINT)
            self._update_token_badge()
            self.update_status("Режим: фотоальбомы ВКонтакте", state="idle")

        elif "Музыка" in choice:
            self._auth_url = AUTH_URL_MUSIC
            avail = VKPYMUSIC_AVAILABLE
            self.card_quality.pack_forget()
            if not self.card_token.winfo_ismapped():
                self.card_token.pack(fill="x", padx=2, pady=(0, 10), before=self.card_cookies)
            self.btn_auth.configure(
                fg_color=ACCENT_BLUE if avail else SURFACE_CARD_BORDER,
                hover_color=ACCENT_BLUE_HOVER if avail else SURFACE_INNER_BORDER)
            self.lbl_token_hint.configure(
                text=("Для музыки токен запрашивается с правом на аудио — "
                      "войдите заново, если раньше входили в режиме фото.")
                if avail else
                "Библиотека vkpymusic не установлена. Запустите: pip install vkpymusic")
            self._update_token_badge()
            self.update_status(
                "Режим: музыка VK" if avail else "Ошибка: vkpymusic не найден",
                state="idle" if avail else "error")

        self.update_idletasks()

    def _update_token_badge(self):
        token = self.entry_token.get().strip()
        mode = self.combo_mode.get()

        if "Музыка" in mode and not VKPYMUSIC_AVAILABLE:
            self.badge_token_status.configure(
                text="Недоступно", text_color=STATUS_RED, fg_color=SURFACE_INNER)
        elif token:
            self.badge_token_status.configure(
                text="Сохранён", text_color=STATUS_GREEN, fg_color=SURFACE_INNER)
        else:
            self.badge_token_status.configure(
                text="Требуется", text_color=STATUS_AMBER, fg_color=SURFACE_INNER)

    def _on_token_changed(self, event=None):
        raw = self.entry_token.get().strip()
        extracted = extract_token(raw)
        if extracted != self.settings.vk_token:
            self.settings.vk_token = extracted
            register_secret(extracted)
        self._update_token_badge()

    # ──────────────────────────────────────────────────────
    # АВТОРИЗАЦИЯ И ВЫБОР ПАПКИ
    # ──────────────────────────────────────────────────────
    _TOKEN_HINT = ("Нажмите «Войти»: в браузере подтвердите доступ и скопируйте адрес страницы "
                   "(Ctrl+L, Ctrl+C) — токен подхватится сам. Пароль программе не передаётся")

    def _set_login_busy(self, busy: bool):
        self._login_busy = busy
        self.btn_auth.configure(text="Отменить вход" if busy else "Войти через ВКонтакте")
        self.btn_auth_window.configure(state="disabled" if busy else "normal")

    def start_vk_login(self):
        """Встроенное окно входа VK (запасной способ: VK ID не всегда отдаёт токен во встроенном окне)."""
        if self._login_busy:
            self._login_cancel.set()
            self._clipboard_watch_until = 0.0
            return
        self._login_cancel.clear()
        self._set_login_busy(True)
        self.update_status("Открыто окно входа ВКонтакте. Подтвердите доступ...", state="working")
        url = self._auth_url

        def _worker():
            outcome = login_in_window(url, self._login_cancel)
            self.after(0, lambda: self._finish_vk_login(outcome))

        threading.Thread(target=_worker, daemon=True).start()

    def _finish_vk_login(self, outcome):
        log.info("Вход VK (окно): %s %s", outcome.status, outcome.detail)
        self._set_login_busy(False)
        if outcome.status == "ok":
            self._accept_vk_token(outcome.result.token)
        elif outcome.status == "unavailable":
            # Окно WebView2 недоступно — запасной путь через обычный браузер
            self.update_status("Окно входа недоступно, открываю обычный браузер...", state="warning")
            self.start_browser_login()
        elif outcome.status == "denied":
            self.update_status("ВКонтакте отклонил вход: " + (outcome.detail or "доступ не выдан")[:50],
                               state="error")
        elif outcome.status == "timeout":
            self.update_status("Время на вход истекло. Нажмите «Войти» ещё раз", state="warning")
        else:  # closed / cancelled
            self.update_status("Вход отменён", state="idle")

    def start_browser_login(self):
        """Основной вход: обычный браузер + автоматический захват адреса из буфера обмена."""
        if self._login_busy:
            # повторное нажатие на «Отменить вход»
            self._login_cancel.set()
            self._clipboard_watch_until = 0.0
            return
        self._login_cancel.clear()
        self._set_login_busy(True)
        webbrowser.open(self._auth_url)
        self._clipboard_watch_until = time.monotonic() + 600
        self.update_status(
            "В браузере нажмите «Продолжить», затем скопируйте адрес страницы: Ctrl+L, Ctrl+C. Токен подхватится сам",
            state="warning")
        self.after(700, self._watch_clipboard)

    def _watch_clipboard(self):
        if not self._login_busy:
            return
        if self._login_cancel.is_set() or time.monotonic() > self._clipboard_watch_until:
            timed_out = not self._login_cancel.is_set()
            self._set_login_busy(False)
            self.update_status(
                "Время на вход истекло" if timed_out else "Вход отменён",
                state="warning" if timed_out else "idle")
            return
        try:
            text = self.clipboard_get()
        except Exception:
            text = ""
        result = find_auth_result(text)
        if result:
            self._set_login_busy(False)
            self.clipboard_clear()  # токен не должен оставаться в буфере обмена
            self._accept_vk_token(result.token)
            return
        self.after(700, self._watch_clipboard)

    def _accept_vk_token(self, token: str):
        """Сохраняет токен, показывает его в поле и проверяет владельца в фоне."""
        register_secret(token)
        self.settings.vk_token = token
        self.entry_token.delete(0, "end")
        self.entry_token.insert(0, token)
        self._update_token_badge()
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except Exception:
            pass
        self.update_status("Токен сохранён. Проверяю вход...", state="working")

        def _verify():
            try:
                name = fetch_user_name(token)
            except Exception:
                self.after(0, lambda: self.update_status(
                    "ВКонтакте не принял токен. Войдите заново", state="error"))
                return
            text = (f"Вход выполнен: {name}" if name else "Токен сохранён") + ". Вкладку VK можно закрыть"
            self.after(0, lambda: self.update_status(text, state="success"))

        threading.Thread(target=_verify, daemon=True).start()

    def choose_folder(self):
        folder = filedialog.askdirectory(
            title="Выберите папку для сохранения",
            initialdir=self.download_path
        )
        if folder:
            self.set_download_path(folder)
            self.settings.download_path = folder
            self.update_status(
                f"Папка: {os.path.basename(self.download_path) or self.download_path}",
                state="idle")

    def set_download_path(self, folder: str):
        self.download_path = os.path.normpath(folder)
        self.entry_folder_path.configure(state="normal")
        self.entry_folder_path.delete(0, "end")
        self.entry_folder_path.insert(0, self.download_path)
        self.entry_folder_path.configure(state="readonly")

    def paste_clipboard(self, entry_widget):
        try:
            text = self.clipboard_get().strip()
        except Exception:
            return
        if not text:
            return

        if entry_widget is self.entry_token:
            text = extract_token(text)
            self.settings.vk_token = text
            register_secret(text)

        if entry_widget is self.entry_url and len(parse_urls(text)) > 1:
            if self.is_downloading:
                return
            added = self._enqueue_text(text)
            self.update_status(f"В очередь добавлено ссылок: {added}", state="idle")
            return

        try:
            entry_widget.configure(state="normal")
        except Exception:
            pass
        entry_widget.delete(0, "end")
        entry_widget.insert(0, text)
        entry_widget.focus_set()

        if entry_widget is self.entry_token:
            self._update_token_badge()
        elif entry_widget is self.entry_url:
            self._on_url_changed()

        self.update_idletasks()

        if entry_widget is self.entry_url:
            detected = detect_url_type(text)
            if detected.get("engine") == "ytdlp":
                self.after(300, self.start_probe_quality_thread)

    def open_target_folder(self):
        open_folder(self.download_path)

    def open_downloaded_folder(self):
        target = (self.last_saved_folder
                  if self.last_saved_folder and os.path.exists(self.last_saved_folder)
                  else self.download_path)
        open_folder(target)

    # ──────────────────────────────────────────────────────
    # УПРАВЛЕНИЕ ЗАНЯТОСТЬЮ UI
    # ──────────────────────────────────────────────────────
    def _set_ui_busy_main(self, busy: bool):
        self.is_downloading = busy
        state = "disabled" if busy else "normal"

        if busy:
            self.btn_download.configure(
                state="normal",
                text="Остановить скачивание",
                fg_color=STATUS_RED,
                hover_color="#A83232"
            )
        else:
            self.btn_download.configure(
                state="normal",
                text="Начать скачивание",
                fg_color=ACCENT_BLUE,
                hover_color=ACCENT_BLUE_HOVER
            )

        self.combo_mode.configure(state=state)
        if hasattr(self, "combo_quality"):
            self.combo_quality.configure(state=state)
        if hasattr(self, "btn_probe_quality"):
            self.btn_probe_quality.configure(state=state)
        if hasattr(self, "chk_playlist"):
            self.chk_playlist.configure(state=state)

        if busy:
            self._hide_folder_button()
            self._hide_details_button()
        self._refresh_queue_view()

    def _set_busy(self, busy: bool):
        self.after(0, self._set_ui_busy_main, busy)

    # ──────────────────────────────────────────────────────
    # ЗАПУСК И ОТМЕНА СКАЧИВАНИЯ
    # ──────────────────────────────────────────────────────
    def start_download_thread(self):
        # Если загрузка уже идёт — кнопка работает как "Остановить скачивание"
        if self.is_downloading:
            self.cancel_event.set()
            self.btn_download.configure(text="Отмена...", state="disabled")
            self.update_status("Остановка скачивания...", state="warning")
            return

        entry_text = self.entry_url.get().strip()
        runnable_in_queue = [it for it in self.queue if it.status in RUNNABLE]

        if runnable_in_queue:
            # Ссылка из поля ввода тоже уходит в очередь
            if entry_text:
                self._enqueue_text(entry_text)
                self._clear_url()
            items = [it for it in self.queue if it.status in RUNNABLE]
            use_queue = True
        elif entry_text:
            # Одиночная загрузка без очереди (как раньше)
            items = [QueueItem(url=entry_text, label=detect_url_type(entry_text)["label"])]
            use_queue = False
        else:
            self.update_status("Ошибка: вставьте ссылку на источник", state="error")
            return

        # Снимок настроек из интерфейса (рабочий поток не трогает виджеты)
        opts = {
            "mode": self.combo_mode.get(),
            "token_raw": self.entry_token.get().strip(),
            "cookies_path": self.settings.cookies_path,
            "quality": self.combo_quality.get(),
            "allow_playlist": bool(self.chk_playlist.get()),
            "download_path": self.download_path,
        }

        self.cancel_event.clear()
        self._set_ui_busy_main(True)
        threading.Thread(
            target=self._download_process, args=(items, opts, use_queue), daemon=True
        ).start()

    def _download_process(self, items: list[QueueItem], opts: dict, use_queue: bool):
        def on_change():
            if use_queue:
                self.after(0, self._refresh_queue_view)

        def run_one(item: QueueItem, number: int, total: int) -> str:
            prefix = f"[{number}/{total}] " if total > 1 else ""

            def cb(text, state="idle", progress=None, percent_str=""):
                # Промежуточный успех элемента не должен выглядеть как конец всей очереди
                if prefix and state == "success":
                    state = "working"
                self.update_status(prefix + text, state, progress, percent_str)

            self.update_status(prefix + "Определение источника...", state="working",
                               progress=0, percent_str="0%")
            return self._download_one(item.url, opts, cb)

        try:
            summary = run_queue(items, run_one, self.cancel_event, on_change)
        finally:
            self._set_busy(False)

        done, failed, total = summary["done"], summary["failed"], summary["total"]
        saved = [it.folder for it in items if it.status == DONE and it.folder]
        if saved:
            self.last_saved_folder = saved[-1]
            self.after(0, self._show_folder_button)

        self.last_errors = [it for it in items if it.status == ERROR]
        if self.last_errors:
            self.after(0, self._show_details_button)

        if summary["cancelled"] or self.cancel_event.is_set():
            self.update_status(
                "Загрузка отменена пользователем" if total == 1
                else f"Очередь остановлена: готово {done} из {total}",
                state="warning")
        elif total == 1:
            if failed:
                self.update_status(items[0].message[:90], state="error")
            # при успехе движок уже показал «Готово…»
        elif failed:
            self.update_status(
                f"Очередь завершена: готово {done} из {total}, ошибок {failed}",
                state="warning", progress=1.0, percent_str="100%")
        else:
            self.update_status(
                f"Очередь завершена: готово {done} из {total}",
                state="success", progress=1.0, percent_str="100%")

    def _download_one(self, target_url: str, opts: dict, cb) -> str:
        """Скачивает одну ссылку нужным движком. Возвращает путь к папке; ошибки — исключением."""
        mode = opts["mode"]
        detected = detect_url_type(target_url)
        if "Автоопределение" in mode:
            engine = detected["engine"]
        elif "Видео" in mode:
            engine = "ytdlp"
        elif "Instagram" in mode:
            engine = "insta"
        elif "Галереи" in mode:
            engine = "gallery"
        elif "Фотографии" in mode:
            engine = "vk_photos"
        elif "Музыка" in mode:
            engine = "vk_music"
        else:
            engine = "ytdlp"

        download_path = opts["download_path"]

        if engine == "insta":
            return download_instagram(
                url=target_url,
                download_path=download_path,
                cookies_path=opts["cookies_path"],
                status_callback=cb,
                cancel_event=self.cancel_event
            )
        if engine == "gallery":
            return download_gallery(
                url=target_url,
                download_path=download_path,
                platform_name=gallery_platform_name(target_url) or "Gallery",
                cookies_path=opts["cookies_path"],
                status_callback=cb,
                cancel_event=self.cancel_event,
                listing=bool(detected.get("listing")),
            )
        if engine == "vk_photos":
            return download_vk_photos(
                token_raw=opts["token_raw"],
                url=target_url,
                download_path=download_path,
                progress_callback=cb,
                cancel_event=self.cancel_event
            )
        if engine == "vk_music":
            return download_vk_music(
                token_raw=opts["token_raw"],
                url=target_url,
                download_path=download_path,
                progress_callback=cb,
                cancel_event=self.cancel_event
            )

        title = download_video(
            url=target_url,
            download_path=download_path,
            quality_choice=opts["quality"],
            progress_callback=cb,
            cookies_path=opts["cookies_path"],
            cancel_event=self.cancel_event,
            # Плейлист включается и сам, если ссылка ведёт на список (SoundCloud set, профиль TikTok)
            allow_playlist=opts["allow_playlist"] or bool(detected.get("playlist"))
        )
        cb(f"Готово: {title[:40]}", "success", 1.0, "100%")
        return download_path
