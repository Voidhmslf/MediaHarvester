"""Тема интерфейса: палитра бренда для светлой и тёмной тем, шрифт Inter, радиусы и готовые стили виджетов.

Цвета заданы парой (светлая, тёмная): customtkinter сам выбирает нужный при смене режима,
поэтому виджеты перекрашиваются без ручного обхода.
Основа — токены из MediaHarvester-brand/tokens (harvest #D9480F, ink, surface); остальное выведено из них.
"""
import ctypes
import os
import sys
from types import SimpleNamespace

import customtkinter as ctk
from PIL import Image, ImageDraw

from src.utils.helpers import get_resource_path, is_linux

# ─────────────────────────────────────────
# ЦВЕТА: (светлая тема, тёмная тема)
# ─────────────────────────────────────────
BG_MAIN              = ("#F4F2EE", "#121212")   # фон окна
SURFACE_CARD         = ("#FFFFFF", "#1A1A1D")   # карточки и строка статуса
SURFACE_CARD_BORDER  = ("#E8E4DE", "#2A2A2F")   # рамки карточек и разделители
SURFACE_INNER        = ("#F6F4F1", "#111113")   # поля ввода и плашки внутри карточки
SURFACE_INNER_BORDER = ("#D9D3CB", "#35353B")   # рамка поля ввода
BTN_SECONDARY        = ("#EFEBE6", "#2A2A2E")   # второстепенные кнопки, выпадающие списки
BTN_SECONDARY_HOVER  = ("#E4DED6", "#36363C")

ACCENT           = "#D9480F"                    # harvest — главный цвет бренда
ACCENT_HOVER     = "#BF3F0B"
ACCENT_TINT      = ("#FDE7DC", "#3A1E12")       # мягкая заливка под акцентный текст
ACCENT_TINT_TEXT = ("#9A3412", "#FFB38A")
TEXT_ON_ACCENT   = "#FFFFFF"

DANGER           = ("#B3261E", "#C0392E")       # кнопки с риском (остановка, эксперимент)
DANGER_HOVER     = ("#951F18", "#A83228")

# Статусные цвета подобраны под контраст ≥ 4.5:1 на карточке в своей теме
STATUS_GREEN = ("#1B7F4B", "#4CC287")
STATUS_RED   = ("#B3261E", "#F0746C")
STATUS_AMBER = ("#8A5A00", "#E3AE45")

TEXT_MAIN      = ("#1A1A1A", "#F2F2F2")
TEXT_SECONDARY = ("#4B4B52", "#B8B8C0")
TEXT_MUTED     = ("#6E6E76", "#8F8F98")

# ─────────────────────────────────────────
# ФОРМЫ И ОТСТУПЫ
# ─────────────────────────────────────────
R_CARD = 14     # карточки
R_CTRL = 10     # кнопки, поля ввода, списки
R_SMALL = 8     # маленькие кнопки
R_PILL = 11     # плашки-бейджи
PAD = 16        # внутренний отступ карточки

THEME_CHOICES = ("system", "light", "dark")
THEME_LABELS = {"system": "Как в системе", "light": "Светлая", "dark": "Тёмная"}
_APPEARANCE_NAMES = {"system": "System", "light": "Light", "dark": "Dark"}

# ─────────────────────────────────────────
# ШРИФТЫ
# ─────────────────────────────────────────
FONT_FILES = ("Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf", "Inter-Bold.ttf")
if is_linux():
    # Что есть почти в любом дистрибутиве: Noto / Cantarell (GNOME) / Ubuntu / DejaVu, последним — вечный запасной
    FALLBACK_UI_FAMILIES = ("Noto Sans", "Cantarell", "Ubuntu", "Roboto", "Open Sans", "DejaVu Sans")
    MONO_FAMILIES = ("JetBrains Mono", "Noto Sans Mono", "Ubuntu Mono", "Liberation Mono", "DejaVu Sans Mono")
else:
    FALLBACK_UI_FAMILIES = ("Segoe UI Variable Text", "Segoe UI")
    MONO_FAMILIES = ("Cascadia Mono", "Consolas")


def _load_fonts_fontconfig() -> bool:
    """Linux: добавляет шрифты в конфигурацию fontconfig этого процесса (Tk берёт шрифты оттуда через Xft)."""
    import ctypes.util
    name = ctypes.util.find_library("fontconfig") or "libfontconfig.so.1"
    try:
        fc = ctypes.CDLL(name)
        fc.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        fc.FcConfigAppFontAddFile.restype = ctypes.c_int
    except (OSError, AttributeError):
        return False
    loaded = False
    for font_name in FONT_FILES:
        path = get_resource_path(os.path.join("assets", "fonts", font_name))
        if os.path.isfile(path):
            loaded |= bool(fc.FcConfigAppFontAddFile(None, os.fsencode(path)))
    return loaded


def load_fonts() -> bool:
    """Подключает шрифты Inter из assets/fonts только для этого процесса (ничего не устанавливается в систему)."""
    if is_linux():
        return _load_fonts_fontconfig()
    if sys.platform != "win32":
        return False
    loaded = False
    for name in FONT_FILES:
        path = get_resource_path(os.path.join("assets", "fonts", name))
        if os.path.isfile(path):
            try:
                loaded |= bool(ctypes.windll.gdi32.AddFontResourceExW(path, 0x10, 0))  # FR_PRIVATE
            except Exception:
                pass
    return loaded


def _pick_family(candidates, available: set[str]) -> str:
    for family in candidates:
        if family in available:
            return family
    return candidates[-1]


def build_fonts() -> SimpleNamespace:
    """Создаёт набор шрифтов. Вызывать после создания корневого окна Tk."""
    from tkinter import font as tkfont
    load_fonts()
    available = set(tkfont.families())
    regular = "Inter" if "Inter" in available else _pick_family(FALLBACK_UI_FAMILIES, available)
    inter = regular == "Inter"
    medium = "Inter Medium" if inter and "Inter Medium" in available else regular
    semibold = "Inter SemiBold" if inter and "Inter SemiBold" in available else regular
    # Если в системе нет полужирных Inter, берём обычный шрифт с признаком bold
    semi_weight = "normal" if semibold != regular else "bold"
    mono = _pick_family(MONO_FAMILIES, available)

    def font(family, size, weight="normal"):
        return ctk.CTkFont(family=family, size=size, weight=weight)

    return SimpleNamespace(
        family=regular,
        title=font(semibold, 17, semi_weight),       # заголовки экранов и окон
        section=font(semibold, 13, semi_weight),     # заголовки карточек
        main=font(regular, 13),                      # основной текст и поля ввода
        medium=font(medium, 13),                     # подписи кнопок
        bold=font(semibold, 14, semi_weight),        # главная кнопка
        small=font(regular, 12),                     # вторичный текст, подсказки
        caption=font(medium, 11),                    # плашки и мелкие метки
        mono=font(mono, 12),                         # пути, проценты, отчёты
    )


# ─────────────────────────────────────────
# РЕЖИМ ТЕМЫ
# ─────────────────────────────────────────
def normalize_theme(value: str) -> str:
    return value if value in THEME_CHOICES else "system"


def apply_theme(choice: str) -> str:
    """Включает тему ("system" | "light" | "dark") и возвращает применённый вариант."""
    choice = normalize_theme(choice)
    ctk.set_appearance_mode(_APPEARANCE_NAMES[choice])
    return choice


def is_dark() -> bool:
    return ctk.get_appearance_mode() == "Dark"


def resolve(color):
    """Цвет для текущей темы: из пары (светлая, тёмная) берёт нужный. Нужен для чистых tk-виджетов (меню)."""
    if isinstance(color, (tuple, list)):
        return color[1] if is_dark() else color[0]
    return color


def apply_titlebar(window) -> None:
    """Красит заголовок окна Windows 11 в цвет фона приложения (на старых Windows ничего не делает)."""
    if sys.platform != "win32":
        return
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())

        def colorref(hex_color: str) -> ctypes.c_int:
            r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
            return ctypes.c_int(r | (g << 8) | (b << 16))

        for attr, color in ((35, BG_MAIN), (36, TEXT_MAIN), (34, BG_MAIN)):  # заголовок, текст, рамка
            value = colorref(resolve(color))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


# ─────────────────────────────────────────
# ГОТОВЫЕ СТИЛИ ВИДЖЕТОВ (передаются как **kwargs)
# ─────────────────────────────────────────
def primary_button() -> dict:
    return dict(fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=TEXT_ON_ACCENT, corner_radius=R_CTRL)


def secondary_button(muted: bool = False) -> dict:
    return dict(fg_color=BTN_SECONDARY, hover_color=BTN_SECONDARY_HOVER,
                text_color=TEXT_MUTED if muted else TEXT_SECONDARY, corner_radius=R_CTRL)


def ghost_button(color=TEXT_MUTED) -> dict:
    return dict(fg_color="transparent", hover_color=BTN_SECONDARY, text_color=color, corner_radius=R_SMALL)


def danger_button() -> dict:
    return dict(fg_color=DANGER, hover_color=DANGER_HOVER, text_color=TEXT_ON_ACCENT, corner_radius=R_CTRL)


def entry_style(readonly: bool = False) -> dict:
    return dict(fg_color=SURFACE_INNER, border_color=SURFACE_INNER_BORDER, border_width=1, corner_radius=R_CTRL,
                text_color=TEXT_SECONDARY if readonly else TEXT_MAIN, placeholder_text_color=TEXT_MUTED)


def option_menu_style() -> dict:
    return dict(fg_color=BTN_SECONDARY, button_color=BTN_SECONDARY, button_hover_color=BTN_SECONDARY_HOVER,
                text_color=TEXT_MAIN, dropdown_fg_color=SURFACE_CARD, dropdown_hover_color=BTN_SECONDARY,
                dropdown_text_color=TEXT_MAIN, corner_radius=R_CTRL, dynamic_resizing=False)


def checkbox_style() -> dict:
    return dict(fg_color=ACCENT, hover_color=ACCENT_HOVER, checkmark_color=TEXT_ON_ACCENT,
                border_color=SURFACE_INNER_BORDER, border_width=2, corner_radius=6, text_color=TEXT_SECONDARY)


def badge_style(kind: str = "muted") -> dict:
    """Плашка-статус: muted (серая), accent (платформа определена), ok / warn / bad (цветной текст)."""
    fg, text = {
        "muted": (SURFACE_INNER, TEXT_MUTED),
        "accent": (ACCENT_TINT, ACCENT_TINT_TEXT),
        "ok": (SURFACE_INNER, STATUS_GREEN),
        "warn": (SURFACE_INNER, STATUS_AMBER),
        "bad": (SURFACE_INNER, STATUS_RED),
    }[kind]
    return dict(fg_color=fg, text_color=text)


def scrollbar_style() -> dict:
    return dict(scrollbar_button_color=BTN_SECONDARY_HOVER, scrollbar_button_hover_color=TEXT_MUTED)


def bind_focus_ring(widget) -> None:
    """Подсвечивает рамку поля ввода акцентным цветом, пока в нём стоит курсор."""
    def on_in(_event=None):
        widget.configure(border_color=ACCENT)

    def on_out(_event=None):
        widget.configure(border_color=SURFACE_INNER_BORDER)

    target = getattr(widget, "_entry", None) or getattr(widget, "_textbox", None)
    if target is not None:
        target.bind("<FocusIn>", on_in, add="+")
        target.bind("<FocusOut>", on_out, add="+")


# ─────────────────────────────────────────
# ИКОНКИ (рисуются кодом, поэтому одинаково чёткие и в светлой, и в тёмной теме)
# ─────────────────────────────────────────
def _draw_theme_icon(kind: str, color: str, size: int = 18) -> Image.Image:
    scale = 8
    big = size * scale
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    c = big / 2
    if kind == "moon":
        r = big * 0.36
        draw.ellipse((c - r, c - r, c + r, c + r), fill=color)
        cut = big * 0.30
        draw.ellipse((c - r * 0.1 + cut * 0.35, c - r * 1.15, c - r * 0.1 + cut * 0.35 + r * 1.55, c - r * 1.15 + r * 1.55),
                     fill=(0, 0, 0, 0))
    else:  # sun
        r = big * 0.2
        draw.ellipse((c - r, c - r, c + r, c + r), fill=color)
        import math
        for i in range(8):
            a = math.radians(i * 45)
            x1, y1 = c + math.cos(a) * big * 0.32, c + math.sin(a) * big * 0.32
            x2, y2 = c + math.cos(a) * big * 0.44, c + math.sin(a) * big * 0.44
            draw.line((x1, y1, x2, y2), fill=color, width=int(big * 0.07))
    return img.resize((size * 2, size * 2), Image.Resampling.LANCZOS)


def theme_toggle_icon(size: int = 18) -> ctk.CTkImage:
    """Иконка кнопки темы: в светлой теме — луна (нажать = стать тёмной), в тёмной — солнце."""
    moon = _draw_theme_icon("moon", "#4B4B52", size)
    sun = _draw_theme_icon("sun", "#B8B8C0", size)
    return ctk.CTkImage(light_image=moon, dark_image=sun, size=(size, size))


def lockup_image(height: int = 32) -> ctk.CTkImage | None:
    """Логотип «знак + надпись» из брендбука: оранжевый, одинаково читается в обеих темах."""
    path = get_resource_path(os.path.join("assets", "brand", "mediaharvester-lockup-128h.png"))
    try:
        with Image.open(path) as source:
            img = source.convert("RGBA")
    except Exception:
        return None
    width = round(img.width * height / img.height)
    return ctk.CTkImage(light_image=img, dark_image=img, size=(width, height))


CARD_GAP = 12


def card_pack() -> dict:
    """Параметры pack() для карточки главного экрана (одинаковые отступы везде)."""
    return dict(fill="x", padx=2, pady=(0, CARD_GAP))


def init_scaling() -> float:
    """
    Linux: Tk не знает про HiDPI, поэтому масштаб берём из окружения: MH_SCALE (ручной), GDK_SCALE,
    Xft.dpi из xrdb. Вызывать до создания окна. На других системах customtkinter масштабирует сам.
    """
    if not is_linux():
        return 1.0
    scale = 1.0
    for var in ("MH_SCALE", "GDK_SCALE"):
        try:
            scale = float(os.environ.get(var, ""))
            break
        except ValueError:
            continue
    else:
        try:
            import re
            import subprocess
            out = subprocess.run(["xrdb", "-query"], capture_output=True, text=True, timeout=2).stdout
            match = re.search(r"Xft\.dpi:\s*([\d.]+)", out)
            if match:
                scale = float(match.group(1)) / 96
        except Exception:
            pass
    scale = round(min(max(scale, 1.0), 3.0), 2)
    if scale != 1.0:
        ctk.set_widget_scaling(scale)
        ctk.set_window_scaling(scale)
    return scale


def set_window_icon(window, delay: int = 0) -> None:
    """Иконка окна: .ico на Windows, PNG через iconphoto на Linux (iconbitmap понимает там только xbm)."""
    def apply():
        try:
            if is_linux():
                import tkinter as tk
                path = get_resource_path(os.path.join("assets", "brand", "mediaharvester-256.png"))
                if os.path.isfile(path):
                    window._mh_icon = tk.PhotoImage(master=window, file=path)  # ссылка, чтобы картинку не съел сборщик мусора
                    window.iconphoto(True, window._mh_icon)
            else:
                path = get_resource_path(os.path.join("assets", "logo.ico"))
                if os.path.isfile(path):
                    window.iconbitmap(path)
        except Exception as e:
            import logging
            logging.getLogger("mediaharvester.app").warning("Не удалось поставить иконку окна: %s", e)

    if delay:
        window.after(delay, apply)  # CTkToplevel на Windows перекрывает иконку своей, поэтому ставим с задержкой
    else:
        apply()


def fit_window_height(window, preferred: int, minimum: int) -> int:
    """Желаемая высота окна, но не больше рабочей области экрана (без панели задач), в логических пикселях."""
    if is_linux():
        # Рабочую область без панелей X11 напрямую не отдаёт — оставляем запас под панель и заголовок
        scaling = window._get_window_scaling() or 1.0
        return max(minimum, min(preferred, int(window.winfo_screenheight() / scaling) - 110))
    try:
        import ctypes.wintypes as wt
        rect = wt.RECT()
        ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0)  # SPI_GETWORKAREA, физические px
        work_height = rect.bottom - rect.top
        scaling = window._get_window_scaling() or 1.0
        return max(minimum, min(preferred, int((work_height - 70) / scaling)))
    except Exception:
        return preferred


def centered_geometry(window, width: int, height: int) -> str:
    """Строка geometry: окно заданного размера по центру рабочей области экрана (не под панелью задач)."""
    if is_linux():
        # Положение оставляем оконному менеджеру: на Wayland и в тайловых средах своё решение всё равно главнее
        return f"{width}x{height}"
    try:
        import ctypes.wintypes as wt
        rect = wt.RECT()
        ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0)  # SPI_GETWORKAREA
        scaling = window._get_window_scaling() or 1.0
        full_w, full_h = int(width * scaling) + 16, int(height * scaling) + 40  # + рамка и заголовок
        x = max(rect.left, rect.left + (rect.right - rect.left - full_w) // 2)
        y = max(rect.top, rect.top + (rect.bottom - rect.top - full_h) // 2)
        return f"{width}x{height}+{x}+{y}"
    except Exception:
        return f"{width}x{height}"
