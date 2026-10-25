"""Режим «Треки по списку»: поле со списком треков."""
import tkinter as tk
import customtkinter as ctk
from src.ui import theme
from src.ui.theme import (
    PAD,
    R_CARD,
    SURFACE_CARD,
    SURFACE_CARD_BORDER,
    SURFACE_INNER,
    SURFACE_INNER_BORDER,
    TEXT_MAIN,
    TEXT_MUTED,
    card_pack,
)
from src.core.track_search import parse_track_list


class TracklistPanelMixin:
    # ──────────────────────────────────────────────────────
    # РЕЖИМ «ТРЕКИ ПО СПИСКУ»
    # ──────────────────────────────────────────────────────
    def _build_tracklist_card(self):
        # Карточка показывается только в режиме «Треки по списку» (см. _set_tracklist_mode)
        self.card_tracklist = ctk.CTkFrame(
            self.main_scroll, fg_color=SURFACE_CARD, corner_radius=R_CARD,
            border_width=1, border_color=SURFACE_CARD_BORDER)

        hrow = ctk.CTkFrame(self.card_tracklist, fg_color="transparent")
        hrow.pack(fill="x", padx=PAD, pady=(14, 8))
        ctk.CTkLabel(hrow, text="Список треков", font=self.font_section,
                     text_color=TEXT_MAIN).pack(side="left")
        self.lbl_tracks_count = self._badge(hrow, "Треков: 0")
        self.lbl_tracks_count.pack(side="right")

        self.txt_tracks = ctk.CTkTextbox(
            self.card_tracklist, height=190, font=self.font_main, wrap="word",
            fg_color=SURFACE_INNER, border_width=1, border_color=SURFACE_INNER_BORDER,
            corner_radius=theme.R_CTRL, text_color=TEXT_MAIN)
        self.txt_tracks.pack(fill="x", padx=PAD, pady=(0, 8))
        self.txt_tracks.bind("<KeyRelease>", lambda e: self._on_tracks_changed())
        self.txt_tracks.bind("<Control-KeyPress>", self._on_text_key)
        theme.bind_focus_ring(self.txt_tracks)

        btns = ctk.CTkFrame(self.card_tracklist, fg_color="transparent")
        btns.pack(fill="x", padx=PAD, pady=(0, 8))
        ctk.CTkButton(
            btns, text="Вставить", width=92, height=34, font=self.font_medium,
            command=self._paste_into_tracks, **theme.secondary_button()).pack(side="left")
        ctk.CTkButton(
            btns, text="Очистить", width=92, height=34, font=self.font_small,
            command=self._clear_tracks, **theme.ghost_button()).pack(side="left", padx=(6, 0))

        self.lbl_tracks_hint = ctk.CTkLabel(
            self.card_tracklist,
            text=("По одному треку в строке: «Исполнитель — Название» (нумерация и пустые строки допустимы). "
                  "Каждый трек ищется на YouTube и сохраняется в MP3 в лучшем доступном качестве. "
                  "К VK приложение не обращается: токен не нужен. Это не те же файлы, что в VK, "
                  "и редкие треки могут не найтись — их список сохранится в _not_found.txt"),
            font=self.font_subtitle, text_color=TEXT_MUTED, justify="left", anchor="w", wraplength=440)
        self.lbl_tracks_hint.pack(anchor="w", padx=PAD, pady=(0, 14))

    def _set_tracklist_mode(self, on: bool):
        """Режим списка: вместо поля ссылки, очереди, качества и токена показывается список треков."""
        self._tracklist_mode = on
        if on:
            for card in (self.card_url, self.card_queue, self.card_quality, self.card_token):
                card.pack_forget()
            if not self.card_tracklist.winfo_ismapped():
                self.card_tracklist.pack(**card_pack(), after=self.card_mode)
        else:
            self.card_tracklist.pack_forget()
            if not self.card_url.winfo_ismapped():
                self.card_url.pack(**card_pack(), after=self.card_mode)
            self._refresh_queue_view()

    def _on_tracks_changed(self):
        count = len(parse_track_list(self.txt_tracks.get("1.0", "end")))
        self.lbl_tracks_count.configure(text=f"Треков: {count}",
                                        **theme.badge_style("ok" if count else "muted"))

    def _clear_tracks(self):
        self.txt_tracks.delete("1.0", "end")
        self._on_tracks_changed()

    def _paste_into_tracks(self):
        text = self._read_clipboard()
        if not text or not text.strip():
            self._warn_empty_clipboard("список треков")
            return
        self._clear_clipboard_warning()
        box = self.txt_tracks._textbox
        try:
            box.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
        box.insert("insert", text)
        self._on_tracks_changed()

    def _on_text_key(self, event):
        """Ctrl+V/C/X/A в списке треков в любой раскладке."""
        if event.state & 0x20000:
            return None
        box = self.txt_tracks._textbox
        code = event.keycode
        if code == self._VK_V:
            self._paste_into_tracks()
        elif code in (self._VK_C, self._VK_X):
            try:
                selected = box.get("sel.first", "sel.last")
            except tk.TclError:
                selected = ""
            if selected:
                self._write_clipboard(selected)
                if code == self._VK_X:
                    box.delete("sel.first", "sel.last")
                    self._on_tracks_changed()
        elif code == self._VK_A:
            box.tag_add("sel", "1.0", "end-1c")
        else:
            return None
        return "break"
