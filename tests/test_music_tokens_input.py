import json
import os
import sys
import tempfile
import unittest
from unittest import mock

from src.config import AUTH_URL_MUSIC, AUTH_URL_PHOTOS, VK_MUSIC_USER_AGENT, SettingsManager
from src.core.vk_engine import extract_music_target
from src.utils import clipboard
from src.utils.errors import explain_error


class MusicTargetTests(unittest.TestCase):
    def test_single_track_links(self):
        t = extract_music_target("https://vk.ru/audio-2001516980_92516980")
        self.assertEqual((t["type"], t["owner_id"], t["audio_id"], t["access_key"]),
                         ("track", -2001516980, 92516980, ""))
        t = extract_music_target("https://vk.com/wall1_2?z=audio-5_6_abc123")
        self.assertEqual((t["type"], t["access_key"]), ("track", "abc123"))

    def test_playlists_and_profiles_on_both_domains(self):
        t = extract_music_target("https://vk.ru/music/playlist/381633909_90_904d5e7d70aa8be55f")
        self.assertEqual((t["type"], t["owner_id"], t["playlist_id"], t["access_key"]),
                         ("playlist", 381633909, 90, "904d5e7d70aa8be55f"))
        self.assertEqual(extract_music_target("https://vk.ru/id123")["user_id"], 123)
        self.assertEqual(extract_music_target("https://vk.com/audios77")["user_id"], 77)

    def test_garbage_is_rejected(self):
        self.assertIsNone(extract_music_target("https://youtu.be/x"))


class MusicAuthTests(unittest.TestCase):
    def test_music_uses_kate_mobile_client_matching_user_agent(self):
        self.assertIn("client_id=2685278", AUTH_URL_MUSIC)
        self.assertIn("KateMobileAndroid", VK_MUSIC_USER_AGENT)
        self.assertNotIn("client_id=2685278", AUTH_URL_PHOTOS)


class SettingsTokenTests(unittest.TestCase):
    def make(self, data=None):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "settings.json")
        if data is not None:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        return SettingsManager(path), path

    def test_tokens_are_stored_per_kind(self):
        s, path = self.make()
        s.set_vk_token("photos", " PH ")
        s.set_vk_token("music", "MU")
        s2 = SettingsManager(path)
        self.assertEqual((s2.get_vk_token("photos"), s2.get_vk_token("music")), ("PH", "MU"))

    def test_legacy_single_token_counts_as_photos_only(self):
        s, _ = self.make({"vk_token": "OLD"})
        self.assertEqual((s.get_vk_token("photos"), s.get_vk_token("music"), s.vk_token), ("OLD", "", "OLD"))


class VkErrorTests(unittest.TestCase):
    def test_error_15_explains_scope_problem(self):
        info = explain_error(RuntimeError(
            "VK API Error 15: Access denied: no access to call this method. It cannot be called with current scopes."))
        self.assertEqual(info.kind, "vk_scope")
        self.assertIn("Музыка", info.hint)

    def test_other_vk_errors(self):
        self.assertEqual(explain_error(RuntimeError("VK API Error 5: User authorization failed")).kind, "vk_token")
        self.assertEqual(explain_error(RuntimeError("VK API Error 6: Too many requests per second")).kind, "vk_flood")
        self.assertEqual(explain_error(RuntimeError("VK API Error 30: This profile is private")).kind, "vk_private")


@unittest.skipUnless(sys.platform == "win32", "Win32 clipboard")
class ClipboardTests(unittest.TestCase):
    def test_roundtrip_clear_and_unicode(self):
        previous = clipboard.get_text()
        try:
            self.assertTrue(clipboard.set_text("Привет https://vk.com/audio-1_2 😀"))
            self.assertEqual(clipboard.get_text(), "Привет https://vk.com/audio-1_2 😀")
            self.assertTrue(clipboard.clear())
            self.assertEqual(clipboard.get_text(), "")
        finally:
            if previous:
                clipboard.set_text(previous)


@unittest.skipUnless(sys.platform == "win32" and not os.environ.get("MH_SKIP_GUI"), "нужен рабочий стол Windows")
class InputFieldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp()
        cls._env = mock.patch.dict(os.environ, {"LOCALAPPDATA": cls._tmp})
        cls._env.start()
        import src.ui.app as app_module
        cls.app_module = app_module
        cls._patches = [
            mock.patch.object(app_module, "check_ffmpeg", lambda: (True, "7")),
            mock.patch.object(app_module, "check_for_update",
                              lambda: type("R", (), {"status": "current", "latest": "", "message": ""})()),
        ]
        for p in cls._patches:
            p.start()
        cls.app = app_module.MediaHarvesterApp()
        cls.app.settings.save = lambda: None
        cls._saved_clip = clipboard.get_text()
        cls.app.update()

    @classmethod
    def tearDownClass(cls):
        cls.app.destroy()
        for p in cls._patches:
            p.stop()
        cls._env.stop()
        if cls._saved_clip:
            clipboard.set_text(cls._saved_clip)

    def press(self, entry, keycode):
        widget = entry._entry
        widget.focus_force()
        self.app.update()
        widget.event_generate("<Control-KeyPress>", keycode=keycode)
        self.app.update()

    def test_hotkeys_by_keycode_work_in_any_layout(self):
        entry = self.app.entry_url
        clipboard.set_text("https://vk.ru/audio-1_2")
        self.press(entry, 86)                                    # Ctrl+V
        self.assertEqual(entry.get(), "https://vk.ru/audio-1_2")
        self.press(entry, 65)                                    # Ctrl+A
        self.press(entry, 88)                                    # Ctrl+X
        self.assertEqual(entry.get(), "")
        self.assertEqual(clipboard.get_text(), "https://vk.ru/audio-1_2")

    def test_paste_button_works_after_clipboard_was_cleared_and_refilled(self):
        entry = self.app.entry_url
        clipboard.clear()
        self.app.paste_clipboard(entry)          # пустой буфер: понятное сообщение, поле не ломается
        clipboard.set_text("https://vk.com/music/playlist/-5_6")
        self.app.paste_clipboard(entry)
        self.assertEqual(entry.get(), "https://vk.com/music/playlist/-5_6")
        self.app._clear_url()
        clipboard.set_text("https://vk.com/music/playlist/-7_8")
        self.app.paste_clipboard(entry)
        self.assertEqual(entry.get(), "https://vk.com/music/playlist/-7_8")

    def test_token_field_follows_mode(self):
        app = self.app
        app.settings.set_vk_token("photos", "PHOTOTOKEN1234567890")
        app.settings.set_vk_token("music", "MUSICTOKEN1234567890")
        app._token_kind = "none"                  # заставить переключение перечитать токен
        app._set_token_kind("music")
        self.assertEqual(app.entry_token.get(), "MUSICTOKEN1234567890")
        self.assertIn("2685278", app._auth_url)
        app._set_token_kind("photos")
        self.assertEqual(app.entry_token.get(), "PHOTOTOKEN1234567890")


if __name__ == "__main__":
    unittest.main()
