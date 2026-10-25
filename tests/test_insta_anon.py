import http.server
import os
import socketserver
import tempfile
import threading
import unittest
from unittest import mock

import src.core.http_download as hd
import src.core.insta_anon as ia
import src.core.insta_engine as ie
from src.utils.helpers import DownloadCancelledError


class UrlTests(unittest.TestCase):
    def test_post_urls(self):
        for url in ("https://www.instagram.com/p/De5MhrPqQV5/", "https://instagram.com/p/AbC-_1/?utm_source=x",
                    "https://www.instagram.com/someone/p/De5MhrPqQV5/"):
            self.assertTrue(ia.is_post_url(url), url)
        for url in ("https://www.instagram.com/reel/AB/", "https://www.instagram.com/stories/u/1/",
                    "https://www.instagram.com/someone/", "https://youtu.be/x"):
            self.assertFalse(ia.is_post_url(url), url)
        self.assertEqual(ia.shortcode("https://www.instagram.com/p/De5MhrPqQV5/?x=1"), "De5MhrPqQV5")


class ExtractMediaTests(unittest.TestCase):
    def test_single_photo_picks_largest_candidate(self):
        product = {"image_versions2": {"candidates": [
            {"url": "https://cdn/small.jpg", "width": 320, "height": 320},
            {"url": "https://cdn/big.jpg?x=1", "width": 1080, "height": 1350}]}}
        items = ia.extract_media(product)
        self.assertEqual([(i.url, i.is_video, i.extension) for i in items], [("https://cdn/big.jpg?x=1", False, "jpg")])
        self.assertEqual(items[0].fallbacks, ("https://cdn/small.jpg",))

    def test_carousel_mixes_photos_and_videos_and_handles_missing_sizes(self):
        product = {"carousel_media": [
            {"image_versions2": {"candidates": [{"url": "https://cdn/a.jpg"}, {"url": "https://cdn/a2.jpg"}]}},
            {"video_versions": [{"url": "https://cdn/v_small.mp4", "width": 480, "height": 640},
                                {"url": "https://cdn/v_big.mp4", "width": 1080, "height": 1920}],
             "image_versions2": {"candidates": [{"url": "https://cdn/cover.jpg"}]}},
            {"display_uri": "https://cdn/display.webp"},
            {"nothing": True},
        ]}
        items = ia.extract_media(product)
        self.assertEqual([(i.url, i.is_video) for i in items], [
            ("https://cdn/a.jpg", False), ("https://cdn/v_big.mp4", True), ("https://cdn/display.webp", False)])
        self.assertEqual([i.extension for i in items], ["jpg", "mp4", "webp"])


class FakeExtractor:
    """Подмена экстрактора yt-dlp: кладёт данные поста и бросает ту же ошибку «нет видео»."""
    product_to_set = None
    error = None

    def __init__(self):
        self.product = None

    def set_downloader(self, ydl):
        pass

    def extract(self, url):
        self.product = FakeExtractor.product_to_set
        if FakeExtractor.error:
            raise FakeExtractor.error


class FetchProductTests(unittest.TestCase):
    def test_no_video_error_is_fine_when_data_was_captured(self):
        from yt_dlp.utils import ExtractorError
        FakeExtractor.product_to_set = {"code": "AB"}
        FakeExtractor.error = ExtractorError("[Instagram] AB: There is no video in this post", expected=True)
        self.assertEqual(ia.fetch_product("https://www.instagram.com/p/AB/", FakeExtractor), {"code": "AB"})

    def test_error_without_data_becomes_access_error(self):
        from yt_dlp.utils import ExtractorError
        FakeExtractor.product_to_set = None
        FakeExtractor.error = ExtractorError("[Instagram] AB: login required", expected=True)
        with self.assertRaises(ia.AnonymousAccessError) as ctx:
            ia.fetch_product("https://www.instagram.com/p/AB/", FakeExtractor)
        self.assertIn("login required", str(ctx.exception))

    def test_unexpected_crash_becomes_access_error(self):
        FakeExtractor.product_to_set = None
        FakeExtractor.error = KeyError("changed format")
        with self.assertRaises(ia.AnonymousAccessError):
            ia.fetch_product("https://www.instagram.com/p/AB/", FakeExtractor)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if "gone" in self.path:
            self.send_response(404)
            self.end_headers()
            return
        body = b"\xff\xd8\xff" + b"x" * 3000
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class DownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        patcher = mock.patch.object(hd.time, "sleep", lambda s: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.messages = []

    def product(self, *paths):
        return {"code": "ABC", "carousel_media": [
            {"image_versions2": {"candidates": [{"url": f"{self.base}{p}", "width": 100, "height": 100}]}} for p in paths]}

    def run_download(self, tmp, product, cancel=None):
        return ia.download_post_anonymously(
            "https://www.instagram.com/p/ABC/", tmp, lambda *a: self.messages.append(a), cancel, fetch=lambda url: product)

    def test_carousel_is_saved_and_rerun_skips_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.run_download(tmp, self.product("/1.jpg", "/2.jpg", "/3.jpg"))
            self.assertEqual(sorted(os.listdir(folder)),
                             ["instagram_ABC_01.jpg", "instagram_ABC_02.jpg", "instagram_ABC_03.jpg"])
            self.assertIn("скачано файлов: 3", self.messages[-1][0])
            self.assertEqual(self.messages[-1][1], "success")
            self.run_download(tmp, self.product("/1.jpg", "/2.jpg", "/3.jpg"))
            self.assertIn("скачано файлов: 3", self.messages[-1][0])

    def test_partial_failure_is_reported_as_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.run_download(tmp, self.product("/1.jpg", "/gone.jpg"))
            self.assertEqual(os.listdir(folder), ["instagram_ABC_01.jpg"])
            self.assertEqual(self.messages[-1][1], "warning")

    def test_everything_failing_raises_so_the_caller_can_fall_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ia.AnonymousAccessError):
                self.run_download(tmp, self.product("/gone.jpg"))

    def test_empty_post_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ia.AnonymousAccessError):
                self.run_download(tmp, {"code": "ABC"})

    def test_cancel(self):
        ev = threading.Event()
        ev.set()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(DownloadCancelledError):
                self.run_download(tmp, self.product("/1.jpg"), ev)


class WrapperRoutingTests(unittest.TestCase):
    POST = "https://www.instagram.com/p/AB/"

    def run_wrapper(self, url, anon_result="anon_dir", **kwargs):
        with mock.patch.object(ie, "download_post_anonymously", side_effect=(
                anon_result if isinstance(anon_result, Exception) else None) or (lambda *a, **k: anon_result)) as anon, \
                mock.patch.object(ie, "download_gallery", return_value="gallery_dir") as gallery:
            result = ie.download_instagram(url, "dl", status_callback=lambda *a: None, **kwargs)
        return result, anon, gallery

    def test_public_post_without_login_goes_anonymous(self):
        result, anon, gallery = self.run_wrapper(self.POST)
        self.assertEqual(result, "anon_dir")
        gallery.assert_not_called()

    def test_login_configured_skips_anonymous_path(self):
        result, anon, gallery = self.run_wrapper(self.POST, cookies_browser="Firefox")
        self.assertEqual(result, "gallery_dir")
        anon.assert_not_called()
        with tempfile.TemporaryDirectory() as tmp:
            cookie_file = os.path.join(tmp, "c.txt")
            open(cookie_file, "w").close()
            result, anon, gallery = self.run_wrapper(self.POST, cookies_path=cookie_file)
        self.assertEqual(result, "gallery_dir")
        anon.assert_not_called()

    def test_anonymous_failure_falls_back_to_gallery_dl(self):
        result, anon, gallery = self.run_wrapper(self.POST, anon_result=ia.AnonymousAccessError("closed"))
        self.assertEqual(result, "gallery_dir")
        anon.assert_called_once()

    def test_reels_and_stories_never_use_the_anonymous_post_path(self):
        for url in ("https://www.instagram.com/reel/AB/", "https://www.instagram.com/stories/u/1/"):
            result, anon, gallery = self.run_wrapper(url)
            self.assertEqual(result, "gallery_dir")
            anon.assert_not_called()


if __name__ == "__main__":
    unittest.main()
