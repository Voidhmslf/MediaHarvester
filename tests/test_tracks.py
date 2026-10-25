import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

import src.core.track_search as ts
from src.utils.helpers import DownloadCancelledError


class ParseTests(unittest.TestCase):
    def test_formats_numbering_and_dedup(self):
        text = "# плейлист\n1. Linkin Park — Numb\n2) Кино - Группа крови\n- Muse – Hysteria\n\nLinkin Park — Numb\nПросто название\n"
        tracks = ts.parse_track_list(text)
        self.assertEqual([(t.artist, t.title) for t in tracks],
                         [("Linkin Park", "Numb"), ("Кино", "Группа крови"), ("Muse", "Hysteria"), ("", "")])
        self.assertEqual(tracks[0].file_stem, "Linkin Park - Numb")
        self.assertEqual(tracks[3].query, "Просто название")

    def test_empty(self):
        self.assertEqual(ts.parse_track_list(" \n# только комментарий\n"), [])


class RankingTests(unittest.TestCase):
    track = ts.Track(query="Linkin Park Numb", artist="Linkin Park", title="Numb")

    def entries(self):
        return [
            {"id": "live", "title": "Linkin Park - Numb (Live)", "channel": "x", "duration": 200},
            {"id": "topic", "title": "Numb", "channel": "Linkin Park - Topic", "duration": 186},
            {"id": "hour", "title": "Linkin Park Numb 1 hour", "channel": "loop", "duration": 3600},
            {"id": "cover", "title": "Numb cover", "channel": "Bob", "duration": 180},
        ]

    def test_original_beats_live_cover_and_loops(self):
        self.assertEqual(ts.pick_best(self.track, self.entries())["id"], "topic")

    def test_unrelated_results_give_none(self):
        other = ts.Track(query="Qwerty Zxcv", artist="Qwerty", title="Zxcv")
        self.assertIsNone(ts.pick_best(other, self.entries()))

    def test_live_is_allowed_when_requested(self):
        live = ts.Track(query="Linkin Park Numb Live", artist="Linkin Park", title="Numb Live")
        self.assertEqual(ts.pick_best(live, self.entries())["id"], "live")


class FakeYDL:
    """Подмена yt_dlp.YoutubeDL: поиск возвращает заготовленную выдачу, скачивание создаёт mp3."""
    searches: list[str] = []
    downloads: list[str] = []
    fail_for: set[str] = set()

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, query, download=False):
        FakeYDL.searches.append(query)
        text = query.split(":", 1)[1]
        if "Ghost Song" in text:
            return {"entries": [{"id": "z", "title": "Совсем другое", "channel": "q", "duration": 200}]}
        return {"entries": [{"id": text.replace(" ", "_"), "title": text, "channel": "Artist - Topic", "duration": 200}]}

    def download(self, urls):
        FakeYDL.downloads.append(urls[0])
        if any(bad in urls[0] for bad in FakeYDL.fail_for):
            raise RuntimeError("ERROR: Video unavailable")
        path = self.opts["outtmpl"].replace("%(ext)s", "mp3")
        with open(path, "wb") as f:
            f.write(b"ID3" + b"x" * 100)


class DownloadListTests(unittest.TestCase):
    def setUp(self):
        FakeYDL.searches, FakeYDL.downloads, FakeYDL.fail_for = [], [], set()
        patcher = mock.patch.object(ts.yt_dlp, "YoutubeDL", FakeYDL)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.messages = []

    def cb(self, *args):
        self.messages.append(args)

    def run_list(self, tmp, text, cancel=None):
        return ts.download_track_list(text, tmp, self.cb, "", cancel)

    def test_downloads_reports_missing_and_resumes(self):
        text = "Muse — Hysteria\nGhost — Ghost Song\nKino — Gruppa Krovi\n"
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.run_list(tmp, text)
            names = sorted(os.listdir(folder))
            self.assertIn("Muse - Hysteria.mp3", names)
            self.assertIn("Kino - Gruppa Krovi.mp3", names)
            self.assertNotIn("Ghost - Ghost Song.mp3", names)
            with open(os.path.join(folder, ts.NOT_FOUND_REPORT), encoding="utf-8") as f:
                self.assertIn("Ghost — Ghost Song", f.read())
            self.assertIn("не найдено/ошибок 1", self.messages[-1][0])
            self.assertEqual(self.messages[-1][1], "warning")

            FakeYDL.searches.clear(); FakeYDL.downloads.clear()
            self.run_list(tmp, text)
            self.assertEqual(len(FakeYDL.downloads), 0)               # скачанное пропущено
            self.assertEqual(len(FakeYDL.searches), 1)                # повторён только ненайденный
            self.assertIn("уже было 2", self.messages[-1][0])

    def test_download_error_is_listed_not_fatal(self):
        FakeYDL.fail_for = {"Bad_Song"}
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.run_list(tmp, "A — Good Song\nA — Bad Song\n")
            self.assertIn("A - Good Song.mp3", os.listdir(folder))
            with open(os.path.join(folder, ts.NOT_FOUND_REPORT), encoding="utf-8") as f:
                self.assertIn("Bad Song", f.read())

    def test_all_failed_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                self.run_list(tmp, "Ghost — Ghost Song\n")

    def test_empty_list_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                self.run_list(tmp, "\n\n")

    def test_cancel(self):
        ev = threading.Event()
        ev.set()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(DownloadCancelledError):
                self.run_list(tmp, "A — B\n", ev)


@unittest.skipUnless(sys.platform == "win32" and not os.environ.get("MH_SKIP_GUI"), "нужен рабочий стол Windows")
class TrackModeUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp()
        cls._env = mock.patch.dict(os.environ, {"LOCALAPPDATA": cls._tmp})
        cls._env.start()
        import src.ui.app as app_module
        cls.m = app_module
        cls._patches = [
            mock.patch.object(app_module, "check_ffmpeg", lambda: (True, "7")),
            mock.patch.object(app_module, "check_for_update",
                              lambda: type("R", (), {"status": "current", "latest": "", "message": ""})()),
        ]
        for p in cls._patches:
            p.start()
        cls.app = app_module.MediaHarvesterApp()
        cls.app.settings.save = lambda: None
        cls.app.update()

    @classmethod
    def tearDownClass(cls):
        cls.app.destroy()
        for p in cls._patches:
            p.stop()
        cls._env.stop()

    def mode(self, fragment):
        name = next(m for m in self.m.CONTENT_MODES if fragment in m)
        self.app.combo_mode.set(name)
        self.app.on_mode_change(name)
        self.app.update()

    def test_switching_to_list_mode_swaps_cards(self):
        app = self.app
        self.mode("по списку")
        self.assertTrue(app.card_tracklist.winfo_ismapped())
        self.assertFalse(app.card_url.winfo_ismapped())
        self.assertFalse(app.card_token.winfo_ismapped())
        app.txt_tracks.insert("1.0", "Muse — Hysteria\nKino — Gruppa Krovi\n")
        app._on_tracks_changed()
        self.assertEqual(app.lbl_tracks_count.cget("text"), "Треков: 2")
        self.mode("Видео")
        self.assertFalse(app.card_tracklist.winfo_ismapped())
        self.assertTrue(app.card_url.winfo_ismapped())

    def test_empty_list_gives_error_and_filled_list_launches(self):
        app = self.app
        self.mode("по списку")
        app._clear_tracks()
        with mock.patch.object(app, "_launch_download") as launch:
            app.start_download_thread()
            launch.assert_not_called()
            app.txt_tracks.insert("1.0", "Muse — Hysteria\n")
            app.start_download_thread()
            items, use_queue, text = launch.call_args[0]
            self.assertEqual((len(items), use_queue), (1, False))
            self.assertIn("Muse", text)

    def test_experimental_login_requires_confirmation_and_can_be_reverted(self):
        app = self.app
        self.mode("Музыка")
        self.assertEqual(app._token_kind, "music")
        self.assertTrue(app.btn_experiment.winfo_ismapped())
        self.assertIn("⚠", app.btn_experiment.cget("text"))
        with mock.patch.object(app, "_confirm_experiment", return_value=False), \
                mock.patch.object(app, "start_browser_login") as login:
            app.toggle_experimental_client()
            login.assert_not_called()
            self.assertEqual(app._token_kind, "music")
        with mock.patch.object(app, "_confirm_experiment", return_value=True), \
                mock.patch.object(app, "start_browser_login") as login:
            app.toggle_experimental_client()
            login.assert_called_once()
        self.assertEqual(app._token_kind, "music_android")
        self.assertIn("2274003", app._auth_url)
        self.assertIn("ЭКСПЕРИМЕНТ", app.lbl_token_hint.cget("text"))
        self.assertIn("нарушает правила VK", app.lbl_experiment_warning.cget("text"))
        app.toggle_experimental_client()           # возврат без подтверждения
        self.assertEqual(app._token_kind, "music")
        self.assertIn("2685278", app._auth_url)
        self.assertEqual(app.settings.get("music_client"), "kate")

    def test_experiment_hidden_for_photos(self):
        self.mode("Фотографии")
        self.assertFalse(self.app.btn_experiment.winfo_ismapped())


if __name__ == "__main__":
    unittest.main()
