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
        self.bridge._probe_enabled = False

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

    def test_cookies_path_reaches_every_engine(self):
        cookies = os.path.join(self.bridge._staging, "cookies.txt")
        with open(cookies, "w") as f:
            f.write("# Netscape HTTP Cookie File\n")
        self.bridge.set_cookies(cookies)
        cb = lambda *a: None
        import src.core.gallery_engine as ge
        import src.core.insta_engine as ie
        import src.core.ytdlp_engine as ye
        seen = {}

        def spy(name, result):
            def fake(**kw):
                seen[name] = kw["cookies_path"]
                return result
            return fake

        with mock.patch.object(ie, "download_instagram", spy("insta", "/o")), \
             mock.patch.object(ge, "download_gallery", spy("gallery", "/o")), \
             mock.patch.object(ye, "download_video", spy("video", "t")):
            self.bridge._download_one("https://www.instagram.com/p/AbC/", "q", cb)
            self.bridge._download_one("https://www.pinterest.com/pin/1/", "q", cb)
            self.bridge._download_one("https://youtu.be/xyz", "q", cb)
        self.assertEqual(seen, {"insta": cookies, "gallery": cookies, "video": cookies})
        self.bridge.set_cookies("/нет/такого/файла")
        self.assertEqual(self.bridge._cookies_path, "")

    def test_cookie_advice_replaces_desktop_hints(self):
        message, hint = self.bridge._android_text(
            "Требуется авторизация Instagram: укажите cookies.txt или выберите браузер в блоке Cookies (лимит)",
            "Укажите cookies.txt из браузера")
        self.assertEqual(message, "Требуется авторизация Instagram")
        self.assertIn("Аккаунты", hint)
        self.assertEqual(self.bridge._android_text("Видео недоступно", "Проверьте ссылку"),
                         ("Видео недоступно", "Проверьте ссылку"))
        self.assertIn("Аккаунты", self.bridge._android_text("Нужен вход в аккаунт или доступ закрыт",
                                                            "Укажите cookies.txt из браузера")[1])

    def test_engine_versions_and_update_report(self):
        info = json.loads(self.bridge.engine_versions())
        self.assertRegex(info["ytdlp"], r"^\d{4}\.\d{2}\.\d{2}")
        self.assertTrue(info["gallery_dl"])
        from src.utils import ytdlp_updater as up
        fake = up.UpdateResult("updated", current="2026.01.01", latest="2026.02.02")
        with mock.patch.object(up, "check_for_update", return_value=fake):
            res = json.loads(self.bridge.update_ytdlp())
        self.assertEqual((res["status"], res["latest"]), ("updated", "2026.02.02"))

    def test_probe_fills_title_thumbnail_and_quality_options(self):
        import src.core.ytdlp_engine as ye
        self.bridge._probe_enabled = True
        info = {"title": "Видео", "thumbnail": "https://i/x.jpg", "uploader": "Автор", "duration": 61,
                "heights": [1080, 720, 360], "playlist": False}
        with mock.patch.object(ye, "probe_media", return_value=info):
            self.bridge.add_links("https://youtu.be/abc")
            self.bridge._probe_pool.shutdown(wait=True)
        (item,) = self.snap()["items"]
        self.assertEqual((item["title"], item["thumbnail"], item["duration"]), ("Видео", "https://i/x.jpg", 61))
        self.assertFalse(item["probing"])
        self.assertEqual(item["quality_options"],
                         ["Максимальное (Авто)", "Full HD (1080p)", "HD (720p)", "SD (480p)", "360p", "Только аудио (MP3)"])

    def test_probe_failure_and_non_ytdlp_links_are_harmless(self):
        import src.core.ytdlp_engine as ye
        self.bridge._probe_enabled = True
        with mock.patch.object(ye, "probe_media", side_effect=RuntimeError("нет сети")):
            self.bridge.add_links("https://youtu.be/abc https://www.instagram.com/p/AbC/")
            self.bridge._probe_pool.shutdown(wait=True)
        yt, insta = self.snap()["items"]
        self.assertEqual((yt["title"], yt["probing"]), ("", False))
        self.assertIn("4K (2160p)", yt["quality_options"])  # неизвестно -> предлагаем всё
        self.assertEqual((insta["probing"], insta["quality_options"]), (False, []))

    def test_item_quality_overrides_queue_quality(self):
        import src.core.ytdlp_engine as ye
        self.bridge._probe_enabled = True
        with mock.patch.object(ye, "probe_media", return_value={
                "title": "", "thumbnail": "", "uploader": "", "duration": 0, "heights": [], "playlist": False}):
            self.bridge.add_links("https://youtu.be/a https://youtu.be/b")
            self.bridge._probe_pool.shutdown(wait=True)
        first = self.snap()["items"][0]["id"]
        self.bridge.set_item_quality(first, "Только аудио (MP3)")
        used = []

        def fake_one(url, quality, cb):
            used.append((url, quality))
            return self.bridge._staging

        with mock.patch.object(self.bridge, "_download_one", fake_one):
            self.bridge.start("HD (720p)")
            self.bridge._thread.join(10)
        self.assertEqual(used, [("https://youtu.be/a", "Только аудио (MP3)"), ("https://youtu.be/b", "HD (720p)")])

    def test_playlist_defaults_for_youtube_links(self):
        self.bridge.add_links(
            "https://www.youtube.com/playlist?list=PLabc "
            "https://www.youtube.com/@channel "
            "https://www.youtube.com/watch?v=abc&list=PLxyz "
            "https://www.youtube.com/watch?v=solo")
        pl, ch, inside, solo = self.snap()["items"]
        self.assertEqual((pl["playlist"], pl["take_playlist"], pl["playlist_optional"]), (True, True, False))
        self.assertEqual((ch["playlist"], ch["take_playlist"]), (True, True))
        self.assertEqual((inside["playlist"], inside["take_playlist"], inside["playlist_optional"]), (False, False, True))
        self.assertEqual((solo["playlist"], solo["playlist_optional"], solo["playlist_limit"]), (False, False, 0))
        self.assertEqual(pl["playlist_limit"], 25)

    def test_playlist_choice_reaches_the_engine(self):
        self.bridge.add_links("https://www.youtube.com/watch?v=abc&list=PLxyz https://youtu.be/solo")
        inside, solo = self.snap()["items"]
        self.bridge.set_item_playlist(inside["id"], True, 10)
        self.bridge.set_item_playlist(inside["id"], True, 7)  # недопустимый предел игнорируется
        calls = []

        def fake_one(url, quality, cb, **kw):
            calls.append((url, kw))
            return self.bridge._staging

        with mock.patch.object(self.bridge, "_download_one", fake_one):
            self.bridge.start("Максимальное (Авто)")
            self.bridge._thread.join(10)
        self.assertEqual(calls, [("https://www.youtube.com/watch?v=abc&list=PLxyz", {"playlist": True, "limit": 10}),
                                 ("https://youtu.be/solo", {})])

    def test_probe_marks_playlists_with_their_size(self):
        import src.core.ytdlp_engine as ye
        self.bridge._probe_enabled = True
        info = {"title": "Мой плейлист", "thumbnail": "", "uploader": "Автор", "duration": 0, "heights": [],
                "playlist": True, "playlist_count": 42}
        with mock.patch.object(ye, "probe_media", return_value=info):
            self.bridge.add_links("https://www.tiktok.com/@user https://vimeo.com/channels/x")
            self.bridge._probe_pool.shutdown(wait=True)
        tiktok, vimeo = self.snap()["items"]
        self.assertEqual((tiktok["playlist"], tiktok["playlist_count"]), (True, 42))
        self.assertEqual((vimeo["playlist"], vimeo["playlist_count"]), (True, 42))  # распознан по ответу yt-dlp

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


class PlaylistLimitTests(unittest.TestCase):
    def run_download(self, **kwargs):
        captured = {}

        class FakeYDL:
            def __init__(self, opts):
                captured.update(opts)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def extract_info(self, url, download=True):
                return {"title": "Список"}

        with mock.patch.object(ytdlp_engine.yt_dlp, "YoutubeDL", FakeYDL):
            ytdlp_engine.download_video("https://youtu.be/x", "dl", "Максимальное (Авто)", lambda *a: None, **kwargs)
        return captured

    def test_limit_applies_only_to_playlists(self):
        opts = self.run_download(allow_playlist=True, playlist_limit=5)
        self.assertEqual((opts["playlistend"], opts["noplaylist"]), (5, False))
        self.assertNotIn("playlistend", self.run_download(allow_playlist=True))
        self.assertNotIn("playlistend", self.run_download(allow_playlist=False, playlist_limit=5))


if __name__ == "__main__":
    unittest.main()
