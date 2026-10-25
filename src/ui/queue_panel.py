"""Очередь ссылок: карточка со списком, добавление и удаление."""
import customtkinter as ctk
from src.core.download_queue import (
    CANCELLED,
    DONE,
    ERROR,
    PENDING,
    QueueItem,
    WORKING,
    parse_urls,
)
from src.config import (
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
from src.core.router import detect_url_type


class QueuePanelMixin:
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
        if not self.queue or self._tracklist_mode:
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
