"""Главный экран: карточки режима, ссылки, качества, cookies и папки; выбор режима и умная маршрутизация."""
import os
import threading
import customtkinter as ctk
from src.config import (
    CONTENT_MODES,
    QUALITY_PRESETS,
)
from src.ui import theme
from src.ui.theme import (
    ACCENT,
    ACCENT_HOVER,
    BTN_SECONDARY,
    BTN_SECONDARY_HOVER,
    PAD,
    R_CARD,
    STATUS_GREEN,
    SURFACE_CARD,
    SURFACE_CARD_BORDER,
    TEXT_MAIN,
    TEXT_MUTED,
    TEXT_SECONDARY,
    card_pack,
)
from src.core.vk_engine import VKPYMUSIC_AVAILABLE
from src.core.router import detect_url_type
from tkinter import filedialog
from src.utils import browser_cookies
from src.utils.helpers import open_folder
from src.core.ytdlp_engine import probe_video_quality


class DownloaderCardsMixin:
    # ──────────────────────────────────────────────────────
    # ЭКРАН 1: ЗАГРУЗЧИК
    # ──────────────────────────────────────────────────────
    def create_downloader_view(self):
        self.main_scroll = ctk.CTkScrollableFrame(
            self.views_container, fg_color="transparent", **theme.scrollbar_style())
        self._build_mode_card()
        self._build_url_card()
        self._build_queue_card()
        self._build_tracklist_card()
        self._build_quality_card()
        self._build_token_card()
        self._build_cookies_card()
        self._build_folder_card()

    def create_action_bar(self):
        """Главная кнопка закреплена внизу окна: видна при любой прокрутке карточек."""
        self.action_bar = ctk.CTkFrame(self, fg_color="transparent")
        self.btn_download = ctk.CTkButton(
            self.action_bar, text="Начать скачивание", height=50,
            font=self.font_bold, command=self.start_download_thread,
            **dict(theme.primary_button(), corner_radius=12))
        self.btn_download.pack(fill="x")
        self.action_bar.pack(side="bottom", fill="x", padx=16, pady=(10, 12))

    def _card(self, parent, pady=(0, theme.CARD_GAP)):
        f = ctk.CTkFrame(parent, fg_color=SURFACE_CARD, corner_radius=R_CARD,
                         border_width=1, border_color=SURFACE_CARD_BORDER)
        f.pack(fill="x", padx=2, pady=pady)
        return f

    def _section_label(self, parent, text, pady=(14, 8)):
        ctk.CTkLabel(parent, text=text, font=self.font_section,
                     text_color=TEXT_MAIN).pack(anchor="w", padx=PAD, pady=pady)

    def _badge(self, parent, text: str, kind: str = "muted"):
        """Плашка-статус справа в заголовке карточки."""
        return ctk.CTkLabel(parent, text=text, font=self.font_caption, corner_radius=theme.R_PILL,
                            padx=10, pady=3, **theme.badge_style(kind))

    def _build_mode_card(self):
        card = self._card(self.main_scroll)
        self.card_mode = card
        self._section_label(card, "Режим загрузки")
        self.combo_mode = ctk.CTkOptionMenu(
            card,
            values=CONTENT_MODES,
            command=self.on_mode_change,
            height=38,
            font=self.font_main, dropdown_font=self.font_main,
            **theme.option_menu_style())
        self.combo_mode.pack(fill="x", padx=PAD, pady=(0, 16))

    def _build_url_card(self):
        self.card_url = self._card(self.main_scroll)

        # Заголовок + бейдж автоопределения
        hrow = ctk.CTkFrame(self.card_url, fg_color="transparent")
        hrow.pack(fill="x", padx=PAD, pady=(14, 8))
        ctk.CTkLabel(hrow, text="Ссылка на источник", font=self.font_section,
                     text_color=TEXT_MAIN).pack(side="left")
        self.badge_detected = self._badge(hrow, "Ожидание ссылки")
        self.badge_detected.pack(side="right")

        erow = ctk.CTkFrame(self.card_url, fg_color="transparent")
        erow.pack(fill="x", padx=PAD, pady=(0, 8))
        self.entry_url = ctk.CTkEntry(
            erow,
            placeholder_text="Вставьте ссылку: YouTube, TikTok, Instagram, VK, X…",
            font=self.font_main, height=42, **theme.entry_style())
        self.entry_url.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.entry_url.bind("<KeyRelease>", self._on_url_changed)
        self.entry_url.bind("<Return>", lambda e: self.add_entry_to_queue())
        theme.bind_focus_ring(self.entry_url)

        ctk.CTkButton(
            erow, text="Вставить", width=88, height=42, font=self.font_medium,
            command=lambda: self.paste_clipboard(self.entry_url),
            **theme.secondary_button()
        ).pack(side="right")

        brow = ctk.CTkFrame(self.card_url, fg_color="transparent")
        brow.pack(fill="x", padx=PAD, pady=(0, 8))
        self.btn_add_queue = ctk.CTkButton(
            brow, text="+ Добавить в очередь (Enter)", height=32, font=self.font_small,
            command=self.add_entry_to_queue, **theme.secondary_button())
        self.btn_add_queue.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            brow, text="Очистить", width=88, height=32, font=self.font_small,
            command=self._clear_url, **theme.ghost_button()
        ).pack(side="right")

        self.lbl_url_hint = ctk.CTkLabel(
            self.card_url,
            text=("Поддерживаются YouTube, TikTok, Instagram, X, Pinterest, Reddit, SoundCloud, фото и музыка VK. "
                  "Можно вставить сразу несколько ссылок — они попадут в очередь"),
            font=self.font_subtitle, text_color=TEXT_MUTED, justify="left")
        self.lbl_url_hint.pack(anchor="w", padx=PAD, pady=(0, 14))

    def _build_quality_card(self):
        self.card_quality = self._card(self.main_scroll)
        self._section_label(self.card_quality, "Качество видео и аудио")

        qrow = ctk.CTkFrame(self.card_quality, fg_color="transparent")
        qrow.pack(fill="x", padx=PAD, pady=(0, 10))

        self.combo_quality = ctk.CTkOptionMenu(
            qrow,
            values=QUALITY_PRESETS,
            height=38,
            font=self.font_main, dropdown_font=self.font_main,
            **theme.option_menu_style())
        self.combo_quality.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.btn_probe_quality = ctk.CTkButton(
            qrow, text="Проверить", width=96, height=38, font=self.font_medium,
            command=self.start_probe_quality_thread, **theme.secondary_button())
        self.btn_probe_quality.pack(side="right")

        # Чекбокс загрузки плейлистов
        self.chk_playlist = ctk.CTkCheckBox(
            self.card_quality,
            text="Скачивать весь плейлист (если ссылка содержит список)",
            font=self.font_small, **theme.checkbox_style())
        self.chk_playlist.pack(anchor="w", padx=PAD, pady=(2, 8))

        self.lbl_quality_info = ctk.CTkLabel(
            self.card_quality,
            text="Нажмите «Проверить» или вставьте ссылку для анализа доступных качеств",
            font=self.font_subtitle, text_color=TEXT_MUTED, justify="left")
        self.lbl_quality_info.pack(anchor="w", padx=PAD, pady=(0, 14))

    def _build_cookies_card(self):
        """Компактная карточка настройки Cookies для Instagram и возрастных видео YouTube."""
        self.card_cookies = self._card(self.main_scroll)

        hrow = ctk.CTkFrame(self.card_cookies, fg_color="transparent")
        hrow.pack(fill="x", padx=PAD, pady=(14, 8))
        ctk.CTkLabel(hrow, text="Cookies (Instagram, YouTube 18+)", font=self.font_section,
                     text_color=TEXT_MAIN).pack(side="left")
        self.badge_cookies_status = self._badge(hrow, "Не задан")
        self.badge_cookies_status.pack(side="right")

        erow = ctk.CTkFrame(self.card_cookies, fg_color="transparent")
        erow.pack(fill="x", padx=PAD, pady=(0, 8))

        self.entry_cookies_path = ctk.CTkEntry(
            erow, font=self.font_mono, height=38,
            placeholder_text="Путь к файлу cookies.txt…", **theme.entry_style(readonly=True))
        self.entry_cookies_path.configure(state="readonly")
        self.entry_cookies_path.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(
            erow, text="Обзор", width=72, height=38, font=self.font_medium,
            command=self.choose_cookies_file, **theme.secondary_button()
        ).pack(side="right")

        ctk.CTkButton(
            erow, text="Сбросить", width=84, height=38, font=self.font_small,
            command=self.clear_cookies_file, **dict(theme.ghost_button(), corner_radius=theme.R_CTRL)
        ).pack(side="right", padx=(0, 4))

        brow = ctk.CTkFrame(self.card_cookies, fg_color="transparent")
        brow.pack(fill="x", padx=PAD, pady=(0, 8))
        ctk.CTkLabel(brow, text="или взять из браузера:", font=self.font_small,
                     text_color=TEXT_SECONDARY).pack(side="left", padx=(0, 10))
        self.combo_cookies_browser = ctk.CTkOptionMenu(
            brow, values=browser_cookies.BROWSER_CHOICES, command=self._on_cookies_browser_changed,
            height=34, font=self.font_small, dropdown_font=self.font_small, width=180,
            **theme.option_menu_style())
        saved_browser = self.settings.get("cookies_browser", "")
        self.combo_cookies_browser.set(saved_browser if saved_browser in browser_cookies.BROWSER_CHOICES
                                       else browser_cookies.NONE_CHOICE)
        self.combo_cookies_browser.pack(side="left")

        self.lbl_cookies_hint = ctk.CTkLabel(
            self.card_cookies,
            text=("Нужно для постов и каруселей Instagram (даже публичных), закрытых аккаунтов и видео 18+. "
                  "Проще всего выбрать Firefox, где вы вошли в аккаунт; для Chrome, Edge и Opera браузер "
                  "нужно закрыть на время скачивания"),
            font=self.font_subtitle, text_color=TEXT_MUTED, justify="left")
        self.lbl_cookies_hint.pack(anchor="w", padx=PAD, pady=(0, 14))

    def _build_folder_card(self):
        self.card_folder = self._card(self.main_scroll)
        self._section_label(self.card_folder, "Папка для сохранения")

        row = ctk.CTkFrame(self.card_folder, fg_color="transparent")
        row.pack(fill="x", padx=PAD, pady=(0, 10))

        self.entry_folder_path = ctk.CTkEntry(
            row, font=self.font_mono, height=38, **theme.entry_style(readonly=True))
        self.entry_folder_path.insert(0, self.download_path)
        self.entry_folder_path.configure(state="readonly")
        self.entry_folder_path.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(
            row, text="Обзор", width=72, height=38, font=self.font_medium,
            command=self.choose_folder, **theme.secondary_button()
        ).pack(side="right")

        self.btn_open_folder = ctk.CTkButton(
            row, text="Открыть", width=84, height=38, font=self.font_medium,
            command=self.open_target_folder, **theme.secondary_button())
        self.btn_open_folder.pack(side="right", padx=(0, 8))

        self.chk_auto_update = ctk.CTkCheckBox(
            self.card_folder, text="Автоматически обновлять yt-dlp",
            font=self.font_small, command=self._on_auto_update_toggled, **theme.checkbox_style())
        if self.settings.get("auto_update_ytdlp", True):
            self.chk_auto_update.select()
        self.chk_auto_update.pack(anchor="w", padx=PAD, pady=(0, 14))

    def _clear_url(self):
        self.entry_url.delete(0, "end")
        self._on_url_changed()

    def _on_url_changed(self, event=None):
        url = self.entry_url.get().strip()
        detected = detect_url_type(url)

        # Обновление статус-бейджа роутера
        if not url:
            self.badge_detected.configure(text="Ожидание ссылки", **theme.badge_style("muted"))
        else:
            self.badge_detected.configure(text=detected["label"], **theme.badge_style("accent"))

        # Если включен режим автоопределения, адаптируем видимость карточек
        current_mode = self.combo_mode.get()
        if "Автоопределение" in current_mode:
            self._apply_smart_routing(detected)

    def _apply_smart_routing(self, detected: dict):
        engine = detected.get("engine", "none")

        if engine in ("vk_photos", "vk_music"):
            self._set_token_kind("photos" if engine == "vk_photos" else self._music_kind())
            self.card_quality.pack_forget()
            if not self.card_token.winfo_ismapped():
                self.card_token.pack(**card_pack(), before=self.card_cookies)
            self._update_token_badge()
        elif engine in ("insta", "gallery"):
            self.card_quality.pack_forget()
            self.card_token.pack_forget()
        elif engine == "ytdlp":
            if not self.card_quality.winfo_ismapped():
                self.card_quality.pack(**card_pack(), before=self.card_cookies)
            self.card_token.pack_forget()
        else:
            # По умолчанию в Smart-режиме держим карточку качества видимой
            if not self.card_quality.winfo_ismapped():
                self.card_quality.pack(**card_pack(), before=self.card_cookies)
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

    def _on_cookies_browser_changed(self, choice: str):
        self.settings.set("cookies_browser", "" if choice == browser_cookies.NONE_CHOICE else choice)
        self._update_cookies_badge()

    def _update_cookies_badge(self):
        c_path = self.settings.cookies_path
        browser = self.settings.get("cookies_browser", "")
        if c_path and os.path.isfile(c_path):
            self.badge_cookies_status.configure(text="Файл", **theme.badge_style("ok"))
        elif browser:
            self.badge_cookies_status.configure(text=browser, **theme.badge_style("ok"))
        else:
            self.badge_cookies_status.configure(text="Не задан", **theme.badge_style("muted"))

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
        cookies_browser = self.settings.get("cookies_browser", "")

        def _worker():
            try:
                heights, title = probe_video_quality(url, cookies_path=cookies, cookies_browser=cookies_browser)

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
    # ЛОГИКА РЕЖИМОВ
    # ──────────────────────────────────────────────────────
    def on_mode_change(self, choice: str):
        url = self.entry_url.get().strip()
        detected = detect_url_type(url)
        self._set_tracklist_mode("по списку" in choice)

        if "Автоопределение" in choice:
            self._apply_smart_routing(detected)
            self.update_status("Режим: Умное автоопределение (Smart)", state="idle")

        elif "Видео" in choice:
            self._set_token_kind("photos")
            self.card_token.pack_forget()
            if not self.card_quality.winfo_ismapped():
                self.card_quality.pack(**card_pack(), before=self.card_cookies)
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
            self._set_token_kind("photos")
            self.card_quality.pack_forget()
            if not self.card_token.winfo_ismapped():
                self.card_token.pack(**card_pack(), before=self.card_cookies)
            self.btn_auth.configure(fg_color=ACCENT, hover_color=ACCENT_HOVER)
            self.lbl_token_hint.configure(text=self._TOKEN_HINT)
            self._update_token_badge()
            self.update_status("Режим: фотоальбомы ВКонтакте", state="idle")

        elif "по списку" in choice:
            self.update_status("Режим: треки по списку (поиск на YouTube, без обращения к VK)", state="idle")

        elif "Музыка" in choice:
            self._set_token_kind(self._music_kind())
            avail = VKPYMUSIC_AVAILABLE
            self.card_quality.pack_forget()
            if not self.card_token.winfo_ismapped():
                self.card_token.pack(**card_pack(), before=self.card_cookies)
            self.btn_auth.configure(
                fg_color=ACCENT if avail else BTN_SECONDARY,
                hover_color=ACCENT_HOVER if avail else BTN_SECONDARY_HOVER)
            self.lbl_token_hint.configure(
                text=self._music_hint() if avail else
                "Библиотека vkpymusic не установлена. Запустите: pip install vkpymusic")
            self._update_token_badge()
            self.update_status(
                "Режим: музыка VK" if avail else "Ошибка: vkpymusic не найден",
                state="idle" if avail else "error")

        self.update_idletasks()

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

    def open_target_folder(self):
        open_folder(self.download_path)

    def open_downloaded_folder(self):
        target = (self.last_saved_folder
                  if self.last_saved_folder and os.path.exists(self.last_saved_folder)
                  else self.download_path)
        open_folder(target)
