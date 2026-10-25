import collections
import importlib
import os
import threading
import unittest
from unittest import mock

from tests.gui_helpers import GUI_AVAILABLE, AppHarness

MIXIN_MODULES = {
    "edit_keys": "EditKeysMixin", "shell": "ShellMixin", "info_view": "InfoViewMixin",
    "downloader_cards": "DownloaderCardsMixin", "queue_panel": "QueuePanelMixin",
    "tracklist_panel": "TracklistPanelMixin", "vk_token_panel": "VkTokenPanelMixin",
    "download_runner": "DownloadRunnerMixin", "engine_status": "EngineStatusMixin",
}
UI_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "ui")


def mixin_classes():
    return [getattr(importlib.import_module(f"src.ui.{module}"), name) for module, name in MIXIN_MODULES.items()]


class StructureTests(unittest.TestCase):
    def test_no_method_is_defined_in_two_mixins(self):
        counter = collections.Counter(
            name for cls in mixin_classes() for name in vars(cls) if not name.startswith("__"))
        self.assertEqual([n for n, c in counter.items() if c > 1], [])

    def test_app_is_composed_of_every_mixin(self):
        from src.ui.app import MediaHarvesterApp
        for cls in mixin_classes():
            self.assertTrue(issubclass(MediaHarvesterApp, cls), cls.__name__)

    def test_key_entry_points_exist(self):
        from src.ui.app import MediaHarvesterApp
        for name in ("start_download_thread", "_download_one", "update_status", "on_mode_change", "paste_clipboard",
                     "start_browser_login", "start_vk_login", "toggle_experimental_client", "add_entry_to_queue",
                     "show_error_details", "_background_checks", "_set_tracklist_mode", "create_info_view"):
            self.assertTrue(callable(getattr(MediaHarvesterApp, name, None)), name)

    def test_modules_stay_small_enough_to_read(self):
        for filename in os.listdir(UI_DIR):
            if filename.endswith(".py"):
                with open(os.path.join(UI_DIR, filename), encoding="utf-8") as f:
                    lines = sum(1 for _ in f)
                self.assertLess(lines, 650, f"{filename} вырос до {lines} строк — разделите его")


class StubRunner:
    """Минимальная «заглушка окна»: достаточно для проверки выбора движка без интерфейса."""
    def __init__(self):
        self.cancel_event = threading.Event()


def make_runner():
    from src.ui.download_runner import DownloadRunnerMixin
    return type("Runner", (DownloadRunnerMixin, StubRunner), {})()


def opts(mode, **extra):
    base = {
        "mode": mode, "tokens": {"photos": "PHOTO_TOKEN", "music": "KATE_TOKEN", "music_android": "ANDROID_TOKEN"},
        "music_client": "kate", "cookies_path": "cookies.txt", "cookies_browser": "Firefox", "quality": "HD (720p)",
        "allow_playlist": False, "download_path": "DL", "tracklist": "A — B",
    }
    base.update(extra)
    return base


SMART = "Автоопределение (Smart)"
MUSIC = "Музыка ВК (Плейлист / Профиль)"


class EngineDispatchTests(unittest.TestCase):
    """После разбиения app.py ссылка каждого типа должна по-прежнему попадать в свой движок."""

    def dispatch(self, url, mode_options):
        runner = make_runner()
        calls = {}

        def spy(name, result):
            def fn(**kwargs):
                calls[name] = kwargs
                return result
            return fn

        patches = [
            mock.patch("src.ui.download_runner.download_video", spy("video", "Название")),
            mock.patch("src.ui.download_runner.download_instagram", spy("insta", "dir_insta")),
            mock.patch("src.ui.download_runner.download_gallery", spy("gallery", "dir_gallery")),
            mock.patch("src.ui.download_runner.download_vk_photos", spy("photos", "dir_photos")),
            mock.patch("src.ui.download_runner.download_vk_music", spy("music", "dir_music")),
            mock.patch("src.ui.download_runner.download_track_list", spy("tracks", "dir_tracks")),
        ]
        statuses = []
        for p in patches:
            p.start()
        try:
            result = runner._download_one(url, mode_options, lambda *a: statuses.append(a))
        finally:
            for p in patches:
                p.stop()
        return result, calls, statuses

    def test_youtube_goes_to_ytdlp_with_selected_quality(self):
        result, calls, statuses = self.dispatch("https://youtu.be/abc", opts(SMART))
        self.assertEqual(result, "DL")
        self.assertEqual(calls["video"]["quality_choice"], "HD (720p)")
        self.assertEqual(calls["video"]["cookies_path"], "cookies.txt")
        self.assertEqual(calls["video"]["cookies_browser"], "Firefox")
        self.assertIn("Готово: Название", statuses[-1][0])

    def test_playlist_links_enable_playlist_download_automatically(self):
        _, calls, _ = self.dispatch("https://soundcloud.com/artist/sets/album", opts(SMART))
        self.assertTrue(calls["video"]["allow_playlist"])
        _, calls, _ = self.dispatch("https://soundcloud.com/artist/track", opts(SMART))
        self.assertFalse(calls["video"]["allow_playlist"])

    def test_vk_album_uses_photos_token(self):
        result, calls, _ = self.dispatch("https://vk.com/album-1_2", opts(SMART))
        self.assertEqual((result, calls["photos"]["token_raw"]), ("dir_photos", "PHOTO_TOKEN"))

    def test_vk_music_uses_kate_token_and_agent(self):
        from src.config import VK_MUSIC_USER_AGENT
        result, calls, _ = self.dispatch("https://vk.com/music/playlist/1_2_abc", opts(SMART))
        self.assertEqual(result, "dir_music")
        self.assertEqual((calls["music"]["token_raw"], calls["music"]["user_agent"]), ("KATE_TOKEN", VK_MUSIC_USER_AGENT))

    def test_experimental_android_client_switches_token_and_agent(self):
        from src.config import VK_ANDROID_USER_AGENT
        _, calls, _ = self.dispatch("https://vk.com/music/playlist/1_2_abc", opts(MUSIC, music_client="android"))
        self.assertEqual((calls["music"]["token_raw"], calls["music"]["user_agent"]),
                         ("ANDROID_TOKEN", VK_ANDROID_USER_AGENT))

    def test_instagram_post_and_gallery_platforms(self):
        _, calls, _ = self.dispatch("https://www.instagram.com/p/AB/", opts(SMART))
        self.assertIn("insta", calls)
        self.assertEqual(calls["insta"]["cookies_browser"], "Firefox")
        _, calls, _ = self.dispatch("https://www.pinterest.com/user/board/", opts(SMART))
        self.assertEqual((calls["gallery"]["platform_name"], calls["gallery"]["listing"]), ("Pinterest", True))
        self.assertEqual(calls["gallery"]["cookies_browser"], "Firefox")
        _, calls, _ = self.dispatch("https://www.pinterest.com/pin/1/", opts(SMART))
        self.assertFalse(calls["gallery"]["listing"])

    def test_track_list_mode_ignores_the_url(self):
        result, calls, _ = self.dispatch("Список треков: 1", opts("Треки по списку (поиск на YouTube)"))
        self.assertEqual((result, calls["tracks"]["text"]), ("dir_tracks", "A — B"))

    def test_forced_mode_overrides_detection(self):
        _, calls, _ = self.dispatch("https://youtu.be/abc", opts("Галереи и посты (Pinterest, X, Reddit, TikTok)"))
        self.assertIn("gallery", calls)
        self.assertNotIn("video", calls)


@unittest.skipUnless(GUI_AVAILABLE, "нужен рабочий стол Windows")
class MainWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.harness = AppHarness()
        cls.app = cls.harness.app

    @classmethod
    def tearDownClass(cls):
        cls.harness.close()

    def type_url(self, url):
        self.app.entry_url.delete(0, "end")
        self.app.entry_url.insert(0, url)
        self.app._on_url_changed()
        self.app.update()

    def test_smart_routing_shows_the_right_cards(self):
        app = self.app
        self.harness.select_mode("Автоопределение")
        self.type_url("https://youtu.be/abc")
        self.assertTrue(app.card_quality.winfo_ismapped())
        self.assertFalse(app.card_token.winfo_ismapped())

        self.type_url("https://vk.com/album-1_2")
        self.assertTrue(app.card_token.winfo_ismapped())
        self.assertFalse(app.card_quality.winfo_ismapped())
        self.assertEqual(app._token_kind, "photos")

        self.type_url("https://vk.com/music/playlist/1_2_abc")
        self.assertEqual(app._token_kind, "music")

        self.type_url("https://www.instagram.com/p/AB/")
        self.assertFalse(app.card_quality.winfo_ismapped())
        self.assertFalse(app.card_token.winfo_ismapped())
        self.app._clear_url()

    def test_queue_panel_deduplicates_and_cleans(self):
        from src.core.download_queue import DONE
        app = self.app
        self.harness.select_mode("Автоопределение")
        added = app._enqueue_text("https://a.com/x https://a.com/x https://b.com/y")
        app.update()
        self.assertEqual((added, len(app.queue), len(app.queue_rows.winfo_children())), (2, 2, 2))
        self.assertTrue(app.card_queue.winfo_ismapped())
        app.queue[0].status = DONE
        app.remove_done_from_queue()
        self.assertEqual(len(app.queue), 1)
        app.clear_queue()
        app.update()
        self.assertFalse(app.card_queue.winfo_ismapped())

    def test_engine_info_line_colors(self):
        from src.ui.theme import STATUS_AMBER, STATUS_RED, TEXT_MUTED
        app = self.app
        app._engine_state.update(ytdlp="2026.10.21", ffmpeg=(True, "7.1"), update="")
        app._render_engine_info()
        self.assertEqual(app.lbl_engine_info.cget("text"), "yt-dlp 2026.10.21 • ffmpeg 7.1")
        self.assertEqual(app.lbl_engine_info.cget("text_color"), TEXT_MUTED)
        app._engine_state.update(update="updated:2026.11.01")
        app._render_engine_info()
        self.assertIn("2026.11.01", app.lbl_engine_info.cget("text"))
        self.assertEqual(app.lbl_engine_info.cget("text_color"), STATUS_AMBER)
        app._engine_state.update(ffmpeg=(False, "не найден"), update="")
        app._render_engine_info()
        self.assertEqual(app.lbl_engine_info.cget("text_color"), STATUS_RED)

    def test_status_bar_states(self):
        app = self.app
        app.update_status("Ошибка тест", state="error")
        app.update()
        self.assertEqual(app.lbl_status_text.cget("text"), "Ошибка тест")
        app.update_status("Готово", state="success", progress=1.0)
        app.update()
        self.assertEqual(app.lbl_percentage.cget("text"), "100%")

    def test_clipboard_warning_disappears_after_a_successful_paste(self):
        from src.utils import clipboard
        app = self.app
        previous = clipboard.get_text()
        try:
            clipboard.clear()
            app.paste_clipboard(app.entry_url)
            app.update()
            self.assertIn("Буфер обмена пуст", app.lbl_status_text.cget("text"))
            clipboard.set_text("https://youtu.be/abc")
            app.paste_clipboard(app.entry_url)
            app.update()
            self.assertNotIn("Буфер обмена пуст", app.lbl_status_text.cget("text"))
            self.assertEqual(app.lbl_status_text.cget("text"), "Готов к работе")
        finally:
            app._clear_url()
            if previous:
                clipboard.set_text(previous)

    def test_cookies_browser_choice_is_saved_and_shown(self):
        app = self.app
        app._on_cookies_browser_changed("Firefox")
        self.assertEqual(app.settings.get("cookies_browser"), "Firefox")
        self.assertEqual(app.badge_cookies_status.cget("text"), "Firefox")
        app._on_cookies_browser_changed("Не использовать")
        self.assertEqual(app.settings.get("cookies_browser"), "")
        self.assertEqual(app.badge_cookies_status.cget("text"), "Не задан")

    def test_info_screen_toggle(self):
        app = self.app
        app.show_info_view()
        app.update()
        self.assertTrue(app.info_scroll.winfo_ismapped())
        app.toggle_view()
        app.update()
        self.assertTrue(app.main_scroll.winfo_ismapped())
        self.assertFalse(app.info_scroll.winfo_ismapped())


if __name__ == "__main__":
    unittest.main()
