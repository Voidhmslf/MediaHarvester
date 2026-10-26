import importlib.util
import json
import os
import tempfile
import unittest
from unittest import mock

from src.core import ytdlp_engine

BRIDGE = os.path.join(os.path.dirname(__file__), "..", "android", "app", "src", "main", "python", "mh_android.py")


def load_bridge():
    spec = importlib.util.spec_from_file_location("mh_android_under_test", BRIDGE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FormatWithoutFfmpegTests(unittest.TestCase):
    def spec(self, choice):
        with mock.patch.object(ytdlp_engine, "FFMPEG_PATH", None):
            return ytdlp_engine.get_video_format_spec(choice)

    def test_no_merging_without_ffmpeg(self):
        self.assertEqual(self.spec("Full HD (1080p)")[0], "best[height<=1080]/best")
        self.assertEqual(self.spec("Максимальное (Авто)")[0], "best")

    def test_audio_only_stays_single_stream(self):
        fmt, post = self.spec("Только аудио (MP3)")
        self.assertEqual((fmt, post), ("bestaudio/best", []))


class BridgeQueueTests(unittest.TestCase):
    def setUp(self):
        self.bridge = load_bridge()
        self.bridge._staging = tempfile.mkdtemp()

    def snap(self):
        return json.loads(self.bridge.snapshot())

    def test_add_links_extracts_and_dedups(self):
        n = self.bridge.add_links("смотри https://www.instagram.com/p/AbC/ и https://youtu.be/xyz, https://youtu.be/xyz")
        self.assertEqual(n, 2)
        self.assertEqual(self.bridge.add_links("https://youtu.be/xyz"), 0)
        items = self.snap()["items"]
        self.assertEqual([i["status"] for i in items], ["pending", "pending"])
        self.assertIn("Instagram", items[0]["label"])

    def test_remove_and_clear(self):
        self.bridge.add_links("https://youtu.be/a https://youtu.be/b")
        first = self.snap()["items"][0]["id"]
        self.bridge.remove(first)
        self.assertEqual(len(self.snap()["items"]), 1)
        self.bridge._items[0]["status"] = "done"
        self.bridge.clear_finished()
        self.assertEqual(self.snap()["items"], [])

    def test_run_collects_new_files_and_errors(self):
        self.bridge.add_links("https://youtu.be/ok https://vk.com/album-1_2")
        staging = self.bridge._staging

        def fake_one(url, quality, cb):
            if "vk.com" in url:
                raise RuntimeError("ВКонтакте пока доступен только в версии для компьютера")
            cb("Загрузка: 50%", "working", 0.5, "50%")
            with open(os.path.join(staging, "clip.mp4"), "w") as f:
                f.write("x")
            return staging

        with mock.patch.object(self.bridge, "_download_one", fake_one):
            self.assertTrue(self.bridge.start("Максимальное (Авто)"))
            self.bridge._thread.join(10)
        ok, bad = self.snap()["items"]
        self.assertEqual(ok["status"], "done")
        self.assertEqual([os.path.basename(f) for f in ok["files"]], ["clip.mp4"])
        self.assertEqual(bad["status"], "error")
        self.assertFalse(self.snap()["running"])
    def test_leftovers_from_cancelled_run_are_exported_with_next_item(self):
        self.bridge.add_links("https://youtu.be/ok")
        staging = self.bridge._staging
        leftover = os.path.join(staging, "old_track.mp3")
        with open(leftover, "w") as f:
            f.write("x")

        def fake_one(url, quality, cb):
            return staging

        with mock.patch.object(self.bridge, "_download_one", fake_one):
            self.bridge.start("Максимальное (Авто)")
            self.bridge._thread.join(10)
        self.assertEqual(self.snap()["items"][0]["files"], [leftover])

    def test_tracklist_becomes_single_queue_item(self):
        text = "1. Queen - Bohemian Rhapsody\n# коммент\nABBA — Waterloo\n"
        self.assertEqual(self.bridge.add_tracks(text), 2)
        self.assertEqual(self.bridge.add_tracks(text), 0)  # тот же список не дублируется
        self.assertEqual(self.bridge.add_tracks("   \n# ничего"), 0)
        (item,) = self.snap()["items"]
        self.assertEqual(item["kind"], "tracks")
        self.assertNotIn("payload", item)
        self.assertIn("2", item["url"])

    def test_tracklist_runs_through_track_engine(self):
        self.bridge.add_tracks("Queen - Bohemian Rhapsody")
        seen = []

        def fake_tracks(text, cb):
            seen.append(text)
            cb("Трек 1 из 1", "working", 0.5, "50%")
            return self.bridge._staging

        with mock.patch.object(self.bridge, "_download_tracks", fake_tracks):
            self.assertTrue(self.bridge.start("Максимальное (Авто)"))
            self.bridge._thread.join(10)
        self.assertEqual(seen, ["Queen - Bohemian Rhapsody"])
        self.assertEqual(self.snap()["items"][0]["status"], "done")

    def test_vk_login_accepts_redirect_url_and_bare_token(self):
        url = "https://oauth.vk.com/blank.html#access_token=vk1.a.ABCDEFGHIJKLMNOPQRSTUV&expires_in=0&user_id=1"
        with mock.patch("src.core.vk_auth.fetch_user_name", return_value="Иван Петров"):
            ok = json.loads(self.bridge.vk_login("вот " + url + " готово"))
            self.assertEqual((ok["ok"], ok["name"], ok["token"]), (True, "Иван Петров", "vk1.a.ABCDEFGHIJKLMNOPQRSTUV"))
            bare = json.loads(self.bridge.vk_login("vk1.a.ZYXWVUTSRQPONMLKJIHGFE"))
            self.assertTrue(bare["ok"])
            self.assertFalse(json.loads(self.bridge.vk_login("просто текст"))["ok"])
        self.assertEqual(self.bridge._vk_token, "vk1.a.ZYXWVUTSRQPONMLKJIHGFE")
        self.bridge.vk_logout()
        self.assertEqual(self.bridge._vk_token, "")

    def test_vk_login_rejects_expired_token(self):
        with mock.patch("src.core.vk_auth.fetch_user_name", side_effect=RuntimeError("code 5")):
            res = json.loads(self.bridge.vk_login("access_token=vk1.a.ABCDEFGHIJKLMNOPQRSTUV"))
        self.assertFalse(res["ok"])
        self.assertEqual(self.bridge._vk_token, "")

    def test_vk_photos_need_login_and_use_token(self):
        from src.core import vk_engine
        cb = lambda *a: None
        with self.assertRaises(RuntimeError) as ctx:
            self.bridge._download_one("https://vk.com/album-1_2", "x", cb)
        self.assertIn("войти", str(ctx.exception))
        self.bridge._vk_token = "tok"
        calls = []
        with mock.patch.object(vk_engine, "download_vk_photos", lambda **kw: calls.append(kw) or "/out"):
            self.assertEqual(self.bridge._download_one("https://vk.com/album-1_2", "x", cb), "/out")
        self.assertEqual((calls[0]["token_raw"], calls[0]["url"]), ("tok", "https://vk.com/album-1_2"))


class InProcessGalleryDlTests(unittest.TestCase):
    def test_captures_output_and_restores_streams(self):
        import sys
        from src.core.gallery_inproc import run_gallery_dl
        out, err = [], []
        before = sys.stdout, sys.stderr, list(sys.argv)
        code = run_gallery_dl(["--version"], out, err)
        self.assertEqual(code, 0)
        self.assertTrue(any(line[:1].isdigit() for line in out), out)
        self.assertEqual((sys.stdout, sys.stderr, list(sys.argv)), before)

    def test_cancel_interrupts(self):
        import threading
        from src.core.gallery_inproc import run_gallery_dl
        from src.utils.helpers import DownloadCancelledError
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(DownloadCancelledError):
            run_gallery_dl(["--version"], [], [], cancel)


if __name__ == "__main__":
    unittest.main()
