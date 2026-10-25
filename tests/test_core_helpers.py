import io
import json
import os
import tempfile
import threading
import unittest
from unittest import mock

import src.core.gallery_engine as ge
import src.core.insta_engine as ie
import src.core.ytdlp_engine as ye
from src.config import SettingsManager
from src.core.vk_engine import extract_album_ids, extract_token, get_best_photo_size
from src.utils import helpers


class HelpersTests(unittest.TestCase):
    def test_sanitize_filename(self):
        self.assertEqual(helpers.sanitize_filename('a/b\\c:d*e?f"g<h>i|j'), "a_b_c_d_e_f_g_h_i_j")
        self.assertEqual(helpers.sanitize_filename("  .. name. "), "name")
        self.assertEqual(helpers.sanitize_filename("..."), "media_file")
        self.assertEqual(helpers.sanitize_filename("Кино — Группа крови"), "Кино — Группа крови")

    def test_app_data_dir_is_created_under_localappdata(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"LOCALAPPDATA": tmp}), \
                mock.patch.object(helpers.sys, "platform", "win32"):
            path = helpers.get_app_data_dir()
            self.assertEqual(path, os.path.join(tmp, "MediaHarvester"))
            self.assertTrue(os.path.isdir(path))

    def test_check_ffmpeg_reports_missing_and_broken(self):
        with mock.patch.object(helpers, "FFMPEG_PATH", None):
            self.assertEqual(helpers.check_ffmpeg(), (False, "не найден"))
        with mock.patch.object(helpers, "FFMPEG_PATH", os.path.join(tempfile.gettempdir(), "no_such_ffmpeg.exe")):
            self.assertEqual(helpers.check_ffmpeg(), (False, "файл не найден"))

    def test_check_ffmpeg_parses_version(self):
        done = mock.Mock(returncode=0, stdout="ffmpeg version 7.1-essentials Copyright\nmore")
        with mock.patch.object(helpers, "FFMPEG_PATH", __file__), mock.patch.object(helpers.subprocess, "run", return_value=done):
            self.assertEqual(helpers.check_ffmpeg(), (True, "7.1-essentials"))

    def test_open_folder_rejects_missing_path(self):
        self.assertFalse(helpers.open_folder(""))
        self.assertFalse(helpers.open_folder(os.path.join(tempfile.gettempdir(), "definitely_missing_dir_123")))


class SettingsTests(unittest.TestCase):
    def make(self, content=None):
        path = os.path.join(tempfile.mkdtemp(), "settings.json")
        if content is not None:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        return SettingsManager(path), path

    def test_defaults(self):
        s, _ = self.make()
        self.assertEqual((s.cookies_path, s.vk_token), ("", ""))
        self.assertTrue(s.get("auto_update_ytdlp"))
        self.assertTrue(os.path.isdir(s.download_path))

    def test_roundtrip_and_path_normalization(self):
        s, path = self.make()
        folder = tempfile.mkdtemp()
        s.download_path = folder.replace("\\", "/")
        s.cookies_path = "  C:/x/cookies.txt "
        s.set("music_client", "android")
        s2 = SettingsManager(path)
        self.assertEqual(s2.download_path, os.path.normpath(folder))
        self.assertEqual((s2.cookies_path, s2.get("music_client")), ("C:/x/cookies.txt", "android"))

    def test_missing_download_folder_falls_back_to_default(self):
        s, _ = self.make(json.dumps({"download_path": os.path.join(tempfile.gettempdir(), "gone_folder_xyz")}))
        self.assertTrue(os.path.isdir(s.download_path))

    def test_corrupted_file_is_ignored(self):
        s, _ = self.make("{ не json")
        self.assertEqual(s.vk_token, "")
        s.set("k", "v")  # и дальше можно сохранять
        self.assertEqual(s.get("k"), "v")


class YtdlpFormatTests(unittest.TestCase):
    def test_quality_presets(self):
        cases = {
            "4K (2160p)": "height<=2160", "2K (1440p)": "height<=1440", "Full HD (1080p)": "height<=1080",
            "HD (720p)": "height<=720", "SD (480p)": "height<=480", "360p": "height<=360",
        }
        for choice, expected in cases.items():
            fmt, post = ye.get_video_format_spec(choice)
            self.assertIn(expected, fmt)
            self.assertEqual(post, [])
        self.assertEqual(ye.get_video_format_spec("Максимальное (Авто)")[0], "bestvideo+bestaudio/best")

    def test_audio_only_uses_mp3_320_with_ffmpeg(self):
        with mock.patch.object(ye, "FFMPEG_PATH", "ffmpeg.exe"):
            fmt, post = ye.get_video_format_spec("Только аудио (MP3)")
        self.assertEqual(fmt, "bestaudio/best")
        self.assertEqual(post[0]["preferredcodec"], "mp3")
        self.assertEqual(post[0]["preferredquality"], "320")

    def test_audio_only_without_ffmpeg_skips_conversion(self):
        with mock.patch.object(ye, "FFMPEG_PATH", None):
            self.assertEqual(ye.get_video_format_spec("Только аудио (MP3)")[1], [])


class VkHelpersTests(unittest.TestCase):
    def test_extract_token(self):
        self.assertEqual(extract_token("https://oauth.vk.com/blank.html#access_token=abc123&expires_in=0"), "abc123")
        self.assertEqual(extract_token("  rawtoken  "), "rawtoken")

    def test_album_ids_and_system_albums(self):
        self.assertEqual(extract_album_ids("https://vk.com/album-185_300"), ("-185", "300"))
        self.assertEqual(extract_album_ids("https://vk.com/album1_0"), ("1", "profile"))
        self.assertEqual(extract_album_ids("https://vk.com/album1_00"), ("1", "wall"))
        self.assertEqual(extract_album_ids("https://vk.com/album1_000"), ("1", "saved"))
        self.assertEqual(extract_album_ids("https://vk.com/id1"), (None, None))

    def test_best_photo_size(self):
        sizes = [{"type": "m", "width": 130, "height": 87, "url": "m"}, {"type": "w", "width": 2000, "height": 1000, "url": "w"}]
        self.assertEqual(get_best_photo_size(sizes)["url"], "w")
        old = [{"type": "m", "url": "m"}, {"type": "x", "url": "x"}]
        self.assertEqual(get_best_photo_size(old)["url"], "x")
        self.assertIsNone(get_best_photo_size([]))


class FakeProcess:
    """Подмена процесса gallery-dl: stdout — строки путей, stderr — текст ошибки, при необходимости создаёт файл."""
    commands: list[list[str]] = []

    def __init__(self, cmd, stdout_lines="", stderr="", create_file=False, returncode=0):
        FakeProcess.commands.append(cmd)
        self.stdout = io.StringIO(stdout_lines)
        self._stderr, self.returncode = stderr, returncode
        if create_file:
            directory = cmd[cmd.index("--directory") + 1]
            with open(os.path.join(directory, "pic.jpg"), "w") as f:
                f.write("x")

    def communicate(self):
        return "", self._stderr


class GalleryEngineTests(unittest.TestCase):
    def run_gallery(self, tmp, url="https://x.com/a/status/1", cookies="", **proc_kwargs):
        FakeProcess.commands.clear()
        messages = []
        with mock.patch.object(ge.subprocess, "Popen", lambda cmd, **kw: FakeProcess(cmd, **proc_kwargs)):
            result = ge.download_gallery(url, tmp, "X", cookies, lambda *a: messages.append(a), ytdlp_fallback=False,
                                         **({"listing": True} if "listing" in url else {}))
        return result, messages

    def test_success_returns_platform_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder, messages = self.run_gallery(tmp, create_file=True)
            self.assertEqual(folder, os.path.join(tmp, "X_Downloads"))
            self.assertIn("скачано медиа-файлов: 1", messages[-1][0])

    def test_cookies_are_passed_only_if_file_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            cookies = os.path.join(tmp, "cookies.txt")
            open(cookies, "w").close()
            self.run_gallery(tmp, cookies=cookies, create_file=True)
            self.assertIn("--cookies", FakeProcess.commands[-1])
        with tempfile.TemporaryDirectory() as tmp2:
            self.run_gallery(tmp2, cookies=os.path.join(tmp2, "nope.txt"), create_file=True)
            self.assertNotIn("--cookies", FakeProcess.commands[-1])

    def test_listing_is_capped(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_gallery(tmp, url="https://x.com/user?listing", create_file=True)
            cmd = FakeProcess.commands[-1]
            self.assertEqual(cmd[cmd.index("--range") + 1], f"1-{ge.LISTING_LIMIT}")

    def test_friendly_errors_when_nothing_downloaded(self):
        cases = {
            "login required": "Требуется авторизация X",
            "HTTP Error 429 too many requests": "временно ограничил запросы",
            "404 not found": "Контент не найден",
        }
        for stderr, expected in cases.items():
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(RuntimeError) as ctx:
                    self.run_gallery(tmp, stderr=stderr, returncode=1)
                self.assertIn(expected, str(ctx.exception))

    def test_cancel_is_respected(self):
        ev = threading.Event()
        ev.set()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
                ge.subprocess, "Popen", lambda cmd, **kw: FakeProcess(cmd, stdout_lines="a.jpg\n")):
            with self.assertRaises(helpers.DownloadCancelledError):
                ge.download_gallery("https://x.com/a", tmp, "X", cancel_event=ev)


class InstagramWrapperTests(unittest.TestCase):
    def fallback_flag(self, url):
        with mock.patch.object(ie, "download_gallery", return_value="dir") as gallery:
            ie.download_instagram(url, "dl")
        return gallery.call_args.kwargs["ytdlp_fallback"], gallery.call_args.kwargs["platform_name"]

    def test_yt_dlp_fallback_only_for_video_links(self):
        self.assertEqual(self.fallback_flag("https://www.instagram.com/reel/AB/"), (True, "Instagram"))
        self.assertEqual(self.fallback_flag("https://www.instagram.com/tv/AB/"), (True, "Instagram"))
        self.assertEqual(self.fallback_flag("https://www.instagram.com/p/AB/"), (False, "Instagram"))


if __name__ == "__main__":
    unittest.main()
