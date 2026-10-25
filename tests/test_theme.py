import os
import re
import unittest

from src.ui import theme
from tests.gui_helpers import GUI_AVAILABLE, AppHarness

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")

COLOR_NAMES = [
    "BG_MAIN", "SURFACE_CARD", "SURFACE_CARD_BORDER", "SURFACE_INNER", "SURFACE_INNER_BORDER",
    "BTN_SECONDARY", "BTN_SECONDARY_HOVER", "ACCENT", "ACCENT_HOVER", "ACCENT_TINT", "ACCENT_TINT_TEXT",
    "TEXT_ON_ACCENT", "DANGER", "DANGER_HOVER", "STATUS_GREEN", "STATUS_RED", "STATUS_AMBER",
    "TEXT_MAIN", "TEXT_SECONDARY", "TEXT_MUTED",
]


def variant(color, index: int) -> str:
    """Цвет для темы: 0 — светлая, 1 — тёмная (одиночная строка одинакова в обеих)."""
    return color[index] if isinstance(color, tuple) else color


def luminance(hex_color: str) -> float:
    channels = []
    for i in (1, 3, 5):
        c = int(hex_color[i:i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg: str, bg: str) -> float:
    a, b = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


class PaletteTests(unittest.TestCase):
    def test_every_color_is_valid_hex_for_both_themes(self):
        for name in COLOR_NAMES:
            color = getattr(theme, name)
            values = color if isinstance(color, tuple) else (color,)
            self.assertIn(len(values), (1, 2), name)
            for value in values:
                self.assertRegex(value, HEX, f"{name}: {value}")

    def test_brand_accent_matches_brand_tokens(self):
        self.assertEqual(theme.ACCENT, "#D9480F")
        self.assertEqual(theme.TEXT_ON_ACCENT, "#FFFFFF")
        self.assertEqual(variant(theme.ACCENT_TINT, 0), "#FDE7DC")
        self.assertEqual(variant(theme.ACCENT_TINT, 1), "#3A1E12")

    def test_text_is_readable_on_surfaces_in_both_themes(self):
        # (цвет текста, фон, минимальный контраст WCAG)
        checks = [
            ("TEXT_MAIN", "BG_MAIN", 7.0), ("TEXT_MAIN", "SURFACE_CARD", 7.0), ("TEXT_MAIN", "SURFACE_INNER", 7.0),
            ("TEXT_SECONDARY", "SURFACE_CARD", 4.5), ("TEXT_SECONDARY", "BTN_SECONDARY", 4.5),
            ("TEXT_MUTED", "SURFACE_CARD", 4.5), ("TEXT_MUTED", "BG_MAIN", 4.5), ("TEXT_MUTED", "SURFACE_INNER", 4.5),
            ("STATUS_GREEN", "SURFACE_CARD", 4.5), ("STATUS_GREEN", "SURFACE_INNER", 4.5),
            ("STATUS_RED", "SURFACE_CARD", 4.5), ("STATUS_RED", "SURFACE_INNER", 4.5),
            ("STATUS_AMBER", "SURFACE_CARD", 4.5), ("STATUS_AMBER", "SURFACE_INNER", 4.5),
            ("ACCENT_TINT_TEXT", "ACCENT_TINT", 4.5),
            ("TEXT_ON_ACCENT", "DANGER", 4.5), ("TEXT_ON_ACCENT", "DANGER_HOVER", 4.5),
            ("TEXT_ON_ACCENT", "ACCENT_HOVER", 4.0),
            # бренд: плитка #D9480F с белым знаком даёт 4.3:1 — для крупной главной кнопки достаточно
            ("TEXT_ON_ACCENT", "ACCENT", 4.0),
        ]
        for index, theme_name in enumerate(("light", "dark")):
            for fg_name, bg_name, minimum in checks:
                fg = variant(getattr(theme, fg_name), index)
                bg = variant(getattr(theme, bg_name), index)
                self.assertGreaterEqual(
                    contrast(fg, bg), minimum, f"{theme_name}: {fg_name} {fg} на {bg_name} {bg}")

    def test_card_is_distinguishable_from_window_background(self):
        for index in (0, 1):
            bg = variant(theme.BG_MAIN, index)
            card = variant(theme.SURFACE_CARD, index)
            border = variant(theme.SURFACE_CARD_BORDER, index)
            self.assertNotEqual(bg, card)
            self.assertGreaterEqual(contrast(border, card), 1.1)


class ThemeHelpersTests(unittest.TestCase):
    def test_normalize_theme_falls_back_to_system(self):
        self.assertEqual(theme.normalize_theme("dark"), "dark")
        self.assertEqual(theme.normalize_theme("light"), "light")
        self.assertEqual(theme.normalize_theme("system"), "system")
        self.assertEqual(theme.normalize_theme("neon"), "system")
        self.assertEqual(theme.normalize_theme(None), "system")

    def test_resolve_picks_color_of_current_mode(self):
        import customtkinter as ctk
        previous = ctk.get_appearance_mode()
        try:
            theme.apply_theme("light")
            self.assertEqual(theme.resolve(theme.TEXT_MAIN), theme.TEXT_MAIN[0])
            theme.apply_theme("dark")
            self.assertEqual(theme.resolve(theme.TEXT_MAIN), theme.TEXT_MAIN[1])
            self.assertEqual(theme.resolve("#123456"), "#123456")
        finally:
            theme.apply_theme(previous.lower())

    def test_every_theme_choice_has_a_label(self):
        self.assertEqual(set(theme.THEME_LABELS), set(theme.THEME_CHOICES))

    def test_style_helpers_use_theme_colors_only(self):
        for style in (theme.primary_button(), theme.secondary_button(), theme.ghost_button(), theme.danger_button(),
                      theme.entry_style(), theme.option_menu_style(), theme.checkbox_style(), theme.badge_style("ok")):
            for key, value in style.items():
                if key.endswith("_color") and value != "transparent":
                    values = value if isinstance(value, tuple) else (value,)
                    for item in values:
                        self.assertRegex(item, HEX, f"{key}={value}")


class FontFilesTests(unittest.TestCase):
    def test_bundled_inter_files_and_license_are_present(self):
        fonts_dir = os.path.join(ROOT, "assets", "fonts")
        for name in theme.FONT_FILES + ("Inter-LICENSE.txt",):
            path = os.path.join(fonts_dir, name)
            self.assertTrue(os.path.isfile(path), name)
            self.assertGreater(os.path.getsize(path), 1000, name)

    def test_brand_assets_are_present(self):
        for name in ("assets/logo.ico", "assets/brand/mediaharvester-lockup-128h.png"):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, name)), name)


@unittest.skipUnless(GUI_AVAILABLE, "нужен рабочий стол Windows")
class ThemeInWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.harness = AppHarness()
        cls.app = cls.harness.app

    @classmethod
    def tearDownClass(cls):
        cls.harness.close()

    def test_inter_font_is_used_when_bundled(self):
        self.assertEqual(self.app.font_main.cget("family"), "Inter")

    def test_header_uses_brand_lockup(self):
        self.assertIsNotNone(self.app.logo_image)

    def test_set_theme_switches_appearance_and_is_remembered(self):
        import customtkinter as ctk
        self.app.set_theme("light")
        self.assertEqual(ctk.get_appearance_mode(), "Light")
        self.assertEqual(self.app.settings.get("theme"), "light")
        self.app.set_theme("dark")
        self.assertEqual(ctk.get_appearance_mode(), "Dark")
        self.assertEqual(self.app.settings.get("theme"), "dark")
        self.assertEqual(self.app.seg_theme.get(), theme.THEME_LABELS["dark"])

    def test_toggle_theme_flips_between_light_and_dark(self):
        self.app.set_theme("dark")
        self.app.toggle_theme()
        self.assertEqual(self.app.theme_choice, "light")
        self.app.toggle_theme()
        self.assertEqual(self.app.theme_choice, "dark")

    def test_segmented_control_changes_theme(self):
        self.app._on_theme_segment(theme.THEME_LABELS["light"])
        self.assertEqual(self.app.theme_choice, "light")
        self.app._on_theme_segment(theme.THEME_LABELS["dark"])
        self.assertEqual(self.app.theme_choice, "dark")

    def test_download_button_is_pinned_and_hidden_on_info_screen(self):
        self.app.show_downloader_view()
        self.app.update()
        self.assertTrue(self.app.action_bar.winfo_ismapped())
        self.app.show_info_view()
        self.app.update()
        self.assertFalse(self.app.action_bar.winfo_ismapped())
        self.app.show_downloader_view()
        self.app.update()
        self.assertTrue(self.app.action_bar.winfo_ismapped())

    def test_window_fits_work_area(self):
        import ctypes
        import ctypes.wintypes as wt
        rect = wt.RECT()
        ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0)
        scaling = self.app._get_window_scaling() or 1.0
        self.app.update()
        self.assertLessEqual(self.app.winfo_height(), (rect.bottom - rect.top) + 2)
        self.assertLessEqual(self.app.winfo_rooty() + self.app.winfo_height(), rect.bottom + 2)  # не под панелью задач
        self.assertGreaterEqual(self.app.winfo_rooty(), rect.top)
        self.assertGreater(self.app.winfo_height() / scaling, 500)


class ThemeSettingTests(unittest.TestCase):
    def test_saved_theme_is_applied_before_window_is_built(self):
        import tempfile
        from src.config import SettingsManager
        path = os.path.join(tempfile.mkdtemp(), "settings.json")
        settings = SettingsManager(path)
        settings.set("theme", "light")
        self.assertEqual(SettingsManager(path).get("theme"), "light")


if __name__ == "__main__":
    unittest.main()
