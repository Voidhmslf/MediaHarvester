"""Каркас окна: шапка, контейнер экранов, статус-бар, окно «Подробнее», переключение экранов."""
import os
import customtkinter as ctk
from src.config import (
    ACCENT_BLUE,
    ACCENT_BLUE_HOVER,
    BG_MAIN,
    STATUS_AMBER,
    STATUS_GREEN,
    STATUS_RED,
    SURFACE_CARD,
    SURFACE_CARD_BORDER,
    SURFACE_INNER,
    SURFACE_INNER_BORDER,
    TEXT_MAIN,
    TEXT_MUTED,
    TEXT_SECONDARY,
)
from src.utils.report import build_report, format_failures
from src.utils.logger import get_log_dir, get_logger
from src.utils.helpers import open_folder

log = get_logger("app")


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
        card_wrap = max(200, w - 92)
        for attr in ("lbl_token_hint", "lbl_url_hint", "lbl_quality_info", "lbl_cookies_hint", "lbl_tracks_hint"):
            lbl = getattr(self, attr, None)
            if lbl:
                lbl.configure(wraplength=card_wrap, anchor="w")
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
