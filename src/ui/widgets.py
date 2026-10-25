"""Свои виджеты поверх customtkinter."""
import sys

import customtkinter as ctk


class ScrollFrame(ctk.CTkScrollableFrame):
    """Прокручиваемая область, которая надёжно реагирует на колесо мыши и тачпад.

    Штатный CTkScrollableFrame решает, прокручивать ли область, по виджету события (event.widget) и по
    флагу «Shift нажат». Из-за этого прокрутка пропадала: событие колеса приходит виджету с фокусом
    (например, кнопке вне области), а флаг Shift «залипает», если отпускание клавиши перехватил переключатель
    раскладки (Alt+Shift, Ctrl+Shift). Здесь область определяется по положению указателя, Shift не учитывается,
    а мелкие шаги тачпада накапливаются, а не округляются до нуля.
    """

    PIXELS_PER_NOTCH = 72   # сдвиг за один «щелчок» колеса (delta = 120)

    def __init__(self, *args, **kwargs):
        self._wheel_remainder = 0.0
        super().__init__(*args, **kwargs)

    def _set_scroll_increments(self):
        # Единица прокрутки — 2 px: шаги получаются плавными (штатное значение делало щелчок колеса слишком мелким)
        self._parent_canvas.configure(xscrollincrement=2, yscrollincrement=2)

    def _pointer_inside(self, x_root: int, y_root: int):
        """Виджет под указателем, если он находится внутри этой области; иначе None."""
        try:
            widget = self.winfo_containing(x_root, y_root)
        except (KeyError, Exception):  # окно закрывается или указатель над меню
            return None
        node = widget
        while node is not None:
            if node is self._parent_canvas:
                return widget
            node = getattr(node, "master", None)
        return None

    @staticmethod
    def _owning_textbox(widget):
        node = widget
        while node is not None:
            if isinstance(node, ctk.CTkTextbox):
                return node
            node = getattr(node, "master", None)
        return None

    def _mouse_wheel_all(self, event):
        if not self._parent_canvas.winfo_ismapped():
            return
        widget = self._pointer_inside(event.x_root, event.y_root)
        if widget is None:
            return
        # Текстовое поле с прокруткой листает себя само, пока в нём есть что листать
        textbox = self._owning_textbox(widget)
        if textbox is not None and textbox.yview() != (0.0, 1.0):
            return
        if self._parent_canvas.yview() == (0.0, 1.0):
            return  # всё помещается, прокручивать нечего

        if sys.platform.startswith("linux"):
            delta = 120 if getattr(event, "num", 0) == 4 else -120
        else:
            delta = event.delta
        self._wheel_remainder += -delta / 120 * self.PIXELS_PER_NOTCH / 2
        units = int(self._wheel_remainder)
        if units:
            self._wheel_remainder -= units
            self._parent_canvas.yview("scroll", units, "units")
