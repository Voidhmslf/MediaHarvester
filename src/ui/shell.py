"""Каркас окна: шапка, контейнер экранов, статус-бар, окно «Подробнее», переключение экранов и тем."""
import os
import customtkinter as ctk
from src.ui import theme
from src.ui.theme import (
    ACCENT,
    BG_MAIN,
    BTN_SECONDARY,
    BTN_SECONDARY_HOVER,
    PAD,
    R_CTRL,
    STATUS_AMBER,
    STATUS_GREEN,
    STATUS_RED,
    SURFACE_CARD,
    SURFACE_CARD_BORDER,
    TEXT_MAIN,
    TEXT_MUTED,
    TEXT_SECONDARY,
)
from src.utils.report import build_report, format_failures
from src.utils.logger import get_log_dir, get_logger
from src.utils.helpers import open_folder

log = get_logger("app")

SUBTITLE_DOWNLOADER = "YouTube • VK • Instagram • TikTok • X и другие"
SUBTITLE_INFO = "Руководство по использованию"


class ShellMixin:
    # ──────────────────────────────────────────────────────
    # АДАПТИВНОЕ МАСШТАБИРОВАНИЕ
    # ──────────────────────────────────────────────────────
    def setup_adaptive_resizing(self):
        self.bind("<Configure>", self._on_window_configure)

    def _on_window_configure(self, event=None):
        if event is not None and event.widget is not self:
            return
        try:
            scaling = self._get_window_scaling() or 1.0
        except Exception:
            scaling = 1.0
        w = int(self.winfo_width() / scaling)  # CustomTkinter задаёт перенос строк в логических пикселях
        card_wrap = max(200, w - 104)
        for attr in ("lbl_token_hint", "lbl_url_hint", "lbl_quality_info", "lbl_cookies_hint", "lbl_tracks_hint",
                     "lbl_experiment_warning"):
            lbl = getattr(self, attr, None)
            if lbl:
                lbl.configure(wraplength=card_wrap, anchor="w")
        if hasattr(self, "info_labels"):
            for lbl in self.info_labels:
                lbl.configure(wraplength=card_wrap)
        if hasattr(self, "lbl_status_text"):
            self.lbl_status_text.configure(wraplength=max(140, w - 230))
        if hasattr(self, "lbl_engine_info"):
            self.lbl_engine_info.configure(wraplength=max(200, w - 48), justify="left")  # длинная строка версий не обрезается

    # ──────────────────────────────────────────────────────
    # ТЕМА (светлая / тёмная / как в системе)
    # ──────────────────────────────────────────────────────
    def set_theme(self, choice: str):
        """Переключает оформление на лету и запоминает выбор."""
        self.theme_choice = theme.apply_theme(choice)
        self.settings.set("theme", self.theme_choice)
        if hasattr(self, "seg_theme"):
            self.seg_theme.set(theme.THEME_LABELS[self.theme_choice])
        self.after(80, lambda: theme.apply_titlebar(self))

    def toggle_theme(self):
        self.set_theme("light" if theme.is_dark() else "dark")

    # ──────────────────────────────────────────────────────
    # ХЕДЕР
    # ──────────────────────────────────────────────────────
    def create_header(self):
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=20, pady=(16, 4))

        top = ctk.CTkFrame(hdr, fg_color="transparent")
        top.pack(fill="x")

        if self.logo_image:
            ctk.CTkLabel(top, image=self.logo_image, text="").pack(side="left")
        else:
            ctk.CTkLabel(top, text="MediaHarvester", font=self.font_title,
                         text_color=ACCENT).pack(side="left")

        self.btn_nav_info = ctk.CTkButton(
            top, text="Справка", width=88, height=34, font=self.font_medium,
            fg_color=BTN_SECONDARY, hover_color=BTN_SECONDARY_HOVER,
            text_color=TEXT_SECONDARY, corner_radius=R_CTRL,
            command=self.toggle_view)
        self.btn_nav_info.pack(side="right")

        self.btn_theme = ctk.CTkButton(
            top, text="", image=self.icon_theme, width=38, height=34,
            fg_color=BTN_SECONDARY, hover_color=BTN_SECONDARY_HOVER, corner_radius=R_CTRL,
            command=self.toggle_theme)
        self.btn_theme.pack(side="right", padx=(0, 8))

        self.lbl_header_sub = ctk.CTkLabel(
            hdr, text=SUBTITLE_DOWNLOADER, font=self.font_small, text_color=TEXT_SECONDARY, anchor="w")
        self.lbl_header_sub.pack(fill="x", pady=(10, 0))
        self.lbl_engine_info = ctk.CTkLabel(
            hdr, text="", font=self.font_caption, text_color=TEXT_MUTED, anchor="w")  # показывается, когда есть текст

    # ──────────────────────────────────────────────────────
    # КОНТЕЙНЕР ЭКРАНОВ
    # ──────────────────────────────────────────────────────
    def create_views_container(self):
        self.views_container = ctk.CTkFrame(self, fg_color="transparent")
        self.views_container.pack(fill="both", expand=True, padx=14, pady=(6, 0))

    # ──────────────────────────────────────────────────────
    # ПЕРЕКЛЮЧЕНИЕ ЭКРАНОВ
    # ──────────────────────────────────────────────────────
    def show_downloader_view(self):
        self.info_scroll.pack_forget()
        self.main_scroll.pack(fill="both", expand=True)
        if not self.action_bar.winfo_ismapped():
            self.action_bar.pack(side="bottom", fill="x", padx=16, pady=(10, 12), before=self.views_container)
        self.current_screen = "downloader"
        self.btn_nav_info.configure(
            text="Справка",
            fg_color=BTN_SECONDARY, hover_color=BTN_SECONDARY_HOVER, text_color=TEXT_SECONDARY)
        self.lbl_header_sub.configure(text=SUBTITLE_DOWNLOADER)

    def show_info_view(self):
        self.main_scroll.pack_forget()
        self.action_bar.pack_forget()
        self.info_scroll.pack(fill="both", expand=True)
        self.current_screen = "info"
        self.btn_nav_info.configure(
            text="Назад",
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER, text_color=theme.TEXT_ON_ACCENT)
        self.lbl_header_sub.configure(text=SUBTITLE_INFO)
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
        sb = ctk.CTkFrame(self, fg_color=SURFACE_CARD, height=66, corner_radius=0)
        sb.pack(fill="x", side="bottom")
        sb.pack_propagate(False)
        ctk.CTkFrame(sb, fg_color=SURFACE_CARD_BORDER, height=1, corner_radius=0).pack(fill="x", side="top")

        top = ctk.CTkFrame(sb, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(10, 6))

        left_sb = ctk.CTkFrame(top, fg_color="transparent")
        left_sb.pack(side="left", fill="x", expand=True)

        self.status_dot = ctk.CTkFrame(left_sb, width=9, height=9, corner_radius=5, fg_color=TEXT_MUTED)
        self.status_dot.pack(side="left", padx=(0, 10))
        self.status_dot.pack_propagate(False)

        self.lbl_status_text = ctk.CTkLabel(
            left_sb, text="Готов к работе", font=self.font_small,
            text_color=TEXT_MUTED, anchor="w", justify="left")
        self.lbl_status_text.pack(side="left", fill="x", expand=True)

        right_sb = ctk.CTkFrame(top, fg_color="transparent")
        right_sb.pack(side="right")

        self.lbl_percentage = ctk.CTkLabel(
            right_sb, text="", font=self.font_mono, text_color=TEXT_SECONDARY)
        self.lbl_percentage.pack(side="right", padx=(8, 0))

        self.btn_view_downloaded = ctk.CTkButton(
            right_sb, text="Открыть папку", height=26, width=112,
            corner_radius=theme.R_SMALL, font=self.font_small,
            fg_color=BTN_SECONDARY, hover_color=BTN_SECONDARY_HOVER,
            text_color=TEXT_SECONDARY,
            command=self.open_downloaded_folder)
        self._folder_btn_visible = False

        self.btn_details = ctk.CTkButton(
            right_sb, text="Подробнее", height=26, width=88,
            corner_radius=theme.R_SMALL, font=self.font_small,
            fg_color=BTN_SECONDARY, hover_color=BTN_SECONDARY_HOVER,
            text_color=STATUS_RED,
            command=self.show_error_details)
        self._details_btn_visible = False

        self.progressbar = ctk.CTkProgressBar(
            sb, height=4, corner_radius=2,
            fg_color=BTN_SECONDARY,
            progress_color=ACCENT, mode="determinate")
        self.progressbar.pack(fill="x", padx=20, pady=(0, 10))
        self.progressbar.set(0)

    # ──────────────────────────────────────────────────────
    # ОБНОВЛЕНИЕ СТАТУС-БАРА (Thread-safe)
    # ──────────────────────────────────────────────────────
    # состояние → (цвет точки, цвет текста, цвет полосы прогресса)
    _STATUS_MAP = {
        "idle":    (TEXT_MUTED,     TEXT_MUTED,     ACCENT),
        "working": (ACCENT,         TEXT_SECONDARY, ACCENT),
        "success": (STATUS_GREEN,   STATUS_GREEN,   STATUS_GREEN),
        "error":   (STATUS_RED,     STATUS_RED,     STATUS_RED),
        "warning": (STATUS_AMBER,   STATUS_AMBER,   STATUS_AMBER),
    }

    def update_status(self, text: str, state: str = "idle",
                      progress: float | None = None,
                      percent_str: str = ""):
        dot_color, text_color, bar_color = self._STATUS_MAP.get(state, self._STATUS_MAP["idle"])

        def _upd():
            self.status_dot.configure(fg_color=dot_color)
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
        win.geometry("580x500")
        win.minsize(440, 340)
        win.configure(fg_color=BG_MAIN)
        win.transient(self)
        try:
            if os.path.exists(self.icon_path):
                win.after(250, lambda: win.iconbitmap(self.icon_path))
        except Exception:
            pass
        win.after(300, lambda: theme.apply_titlebar(win))

        ctk.CTkLabel(
            win, text=f"Не удалось скачать: {len(items)}", font=self.font_title,
            text_color=TEXT_MAIN).pack(anchor="w", padx=PAD + 4, pady=(18, 8))

        box = ctk.CTkTextbox(
            win, font=self.font_mono, fg_color=SURFACE_CARD, text_color=TEXT_SECONDARY,
            border_width=1, border_color=SURFACE_CARD_BORDER, corner_radius=theme.R_CARD, wrap="word")
        box.pack(fill="both", expand=True, padx=PAD + 4, pady=(0, 10))
        box.insert("1.0", format_failures(items))
        box.configure(state="disabled")

        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(fill="x", padx=PAD + 4, pady=(0, 16))

        def copy_report():
            self.clipboard_clear()
            self.clipboard_append(build_report(items, self._engine_state))
            btn_copy.configure(text="Скопировано")

        btn_copy = ctk.CTkButton(
            btns, text="Скопировать отчёт", height=36, font=self.font_medium,
            command=copy_report, **theme.primary_button())
        btn_copy.pack(side="left")
        ctk.CTkButton(
            btns, text="Открыть папку логов", height=36, font=self.font_medium,
            command=lambda: open_folder(get_log_dir()), **theme.secondary_button()
        ).pack(side="left", padx=(8, 0))
        ctk.CTkButton(
            btns, text="Закрыть", width=88, height=36, font=self.font_medium,
            command=win.destroy, **theme.secondary_button()
        ).pack(side="right")

    def report_callback_exception(self, exc, val, tb):
        """Ошибки в обработчиках Tk: пишем в лог вместо молчаливого вывода в консоль."""
        log.critical("Ошибка в обработчике интерфейса", exc_info=(exc, val, tb))

    def _hide_folder_button(self):
        if self._folder_btn_visible:
            self.btn_view_downloaded.pack_forget()
            self._folder_btn_visible = False
