"""Буфер обмена и горячие клавиши полей ввода (в любой раскладке), контекстное меню."""
import tkinter as tk
from src.ui.theme import (
    ACCENT,
    SURFACE_CARD,
    TEXT_MAIN,
    TEXT_ON_ACCENT,
    resolve,
)
from src.core.router import detect_url_type
from src.core.vk_engine import extract_token
from src.core.download_queue import parse_urls
from src.utils.logger import register_secret, get_logger
from src.utils import clipboard as sysclip

log = get_logger("app")


class EditKeysMixin:
    # ──────────────────────────────────────────────────────
    # ГОРЯЧИЕ КЛАВИШИ
    # ──────────────────────────────────────────────────────
    # Коды клавиш Windows: не зависят от раскладки (в русской раскладке Ctrl+М — это та же клавиша V)
    _VK_A, _VK_C, _VK_V, _VK_X = 65, 67, 86, 88

    def setup_keybindings(self):
        for entry in (self.entry_url, self.entry_token):
            entry.bind("<Control-KeyPress>", lambda e, ent=entry: self._on_edit_key(e, ent))
            entry.bind("<Button-3>", lambda e, ent=entry: self._show_entry_menu(e, ent))

    def _on_edit_key(self, event, entry):
        """Ctrl+V/C/X/A в полях ввода в любой раскладке (возврат "break" отключает стандартную обработку)."""
        if event.state & 0x20000:  # Alt (в т.ч. AltGr) — не наш случай
            return None
        code = event.keycode
        if code == self._VK_V:
            self.paste_clipboard(entry)
        elif code == self._VK_C:
            self._copy_from_entry(entry, cut=False)
        elif code == self._VK_X:
            self._copy_from_entry(entry, cut=True)
        elif code == self._VK_A:
            entry._entry.select_range(0, "end")
            entry._entry.icursor("end")
        else:
            return None
        return "break"

    def _show_entry_menu(self, event, entry):
        """Контекстное меню поля ввода (правая кнопка мыши)."""
        entry.focus_set()
        # Чистый tk-виджет не понимает пары цветов — берём цвет текущей темы
        menu = tk.Menu(self, tearoff=0, bg=resolve(SURFACE_CARD), fg=resolve(TEXT_MAIN),
                       activebackground=resolve(ACCENT), activeforeground=resolve(TEXT_ON_ACCENT),
                       font=self.font_small, bd=0)
        menu.add_command(label="Вырезать", command=lambda: self._copy_from_entry(entry, cut=True))
        menu.add_command(label="Копировать", command=lambda: self._copy_from_entry(entry, cut=False))
        menu.add_command(label="Вставить", command=lambda: self.paste_clipboard(entry))
        menu.add_separator()
        menu.add_command(label="Выделить всё",
                         command=lambda: (entry._entry.select_range(0, "end"), entry._entry.icursor("end")))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _read_clipboard(self) -> str | None:
        """Текст из буфера обмена (Win32, запасной путь — Tk). None, если прочитать не удалось."""
        text = sysclip.get_text()
        if text is None:
            try:
                text = self.clipboard_get()
            except Exception:
                log.warning("Не удалось прочитать буфер обмена")
                return None
        return text

    def _write_clipboard(self, text: str) -> None:
        if not sysclip.set_text(text):
            self.clipboard_clear()
            self.clipboard_append(text)

    def _copy_from_entry(self, entry, cut: bool):
        inner = entry._entry
        try:
            text = inner.selection_get()
            has_selection = True
        except tk.TclError:
            text, has_selection = entry.get(), False
        if text:
            self._write_clipboard(text)
        if cut and text:
            if has_selection:
                inner.delete("sel.first", "sel.last")
            else:
                entry.delete(0, "end")
            if entry is self.entry_url:
                self._on_url_changed()
            else:
                self._on_token_changed()

    def _warn_empty_clipboard(self, what: str = "ссылку"):
        self._clipboard_warned = True
        self.update_status(f"Буфер обмена пуст: сначала скопируйте {what} (Ctrl+C)", state="warning")

    def _clear_clipboard_warning(self):
        """Убирает предупреждение «буфер пуст», как только вставка удалась."""
        if getattr(self, "_clipboard_warned", False):
            self._clipboard_warned = False
            self.update_status("Готов к работе", state="idle")

    def paste_clipboard(self, entry_widget):
        text = (self._read_clipboard() or "").strip()
        if not text:
            self._warn_empty_clipboard()
            return
        self._clear_clipboard_warning()

        if entry_widget is self.entry_token:
            text = extract_token(text)
            self.settings.set_vk_token(self._token_kind, text)
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
