import http.server
import os
import socketserver
import tempfile
import threading
import unittest
from unittest import mock

import src.core.vk_engine as ve

hits: dict[str, int] = {}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        hits[self.path] = hits.get(self.path, 0) + 1
        if self.path.startswith("/gone"):
            self.send_response(404)
            self.end_headers()
            return
        if self.path.startswith("/flaky") and hits[self.path] < 3:
            self.send_response(500)
            self.end_headers()
            return
        body = b"x" * 4000
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class SizeOrderTests(unittest.TestCase):
    def test_largest_first_and_deduplicated(self):
        sizes = [
            {"type": "s", "width": 75, "height": 50, "url": "u_small"},
            {"type": "w", "width": 1469, "height": 1000, "url": "u_big"},
            {"type": "x", "width": 604, "height": 411, "url": "u_mid"},
            {"type": "y", "width": 604, "height": 411, "url": "u_mid"},
        ]
        self.assertEqual(ve.photo_size_urls(sizes), ["u_big", "u_mid", "u_small"])

    def test_old_photos_without_dimensions_use_type_priority(self):
        sizes = [{"type": "m", "url": "u_m"}, {"type": "z", "url": "u_z"}, {"type": "s", "url": "u_s"}]
        self.assertEqual(ve.photo_size_urls(sizes), ["u_z", "u_m", "u_s"])

    def test_limit(self):
        sizes = [{"width": i, "height": i, "url": f"u{i}"} for i in range(1, 10)]
        self.assertEqual(len(ve.photo_size_urls(sizes, limit=3)), 3)


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
        hits.clear()
        patcher = mock.patch.object(ve.time, "sleep", lambda s: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def album(self):
        def sizes(*paths):
            return [{"type": "x", "width": 1000 - 100 * i, "height": 1000 - 100 * i, "url": f"{self.base}{p}"}
                    for i, p in enumerate(paths)]
        return [
            {"id": 1, "sizes": sizes("/ok1.jpg")},
            {"id": 2, "sizes": sizes("/gone2.jpg", "/ok2.jpg")},           # крупный 404 -> берём следующий
            {"id": 3, "sizes": sizes("/gone3a.jpg", "/gone3b.jpg")},        # недоступны все варианты
            {"id": 4, "sizes": sizes("/flaky4.jpg")},                      # временный сбой 500 -> повтор
        ]

    def run_download(self, tmp, cancel=None):
        fake = mock.MagicMock()
        fake.photos.get.return_value = {"items": self.album()}
        fake.photos.getAlbums.return_value = {"items": [{"title": "t"}]}
        messages = []
        with mock.patch("vk_api.VkApi") as vk:
            vk.return_value.get_api.return_value = fake
            folder = ve.download_vk_photos("tok", "https://vk.com/album-1_2", tmp,
                                           lambda *a: messages.append(a), cancel)
        return folder, messages

    def test_falls_back_to_smaller_size_and_reports_the_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder, messages = self.run_download(tmp)
            names = sorted(os.listdir(folder))
            self.assertTrue(any(n.startswith("photo_0001_1") for n in names))
            self.assertTrue(any(n.startswith("photo_0002_2") for n in names), names)   # благодаря запасному размеру
            self.assertTrue(any(n.startswith("photo_0004_4") for n in names), names)   # благодаря повтору
            self.assertFalse(any(n.startswith("photo_0003_3") for n in names))
            self.assertIn("_failed.txt", names)
            with open(os.path.join(folder, "_failed.txt"), encoding="utf-8") as f:
                report = f.read()
            self.assertIn("#3", report)
            self.assertIn("пробовали вариантов: 2", report)
            self.assertIn("ошибок 1", messages[-1][0])
            # постоянный 404 не повторяется: каждый адрес запрошен один раз
            self.assertEqual(hits["/gone2.jpg"], 1)
            self.assertEqual(hits["/gone3a.jpg"], 1)

    def test_rerun_skips_downloaded_and_retries_only_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_download(tmp)
            hits.clear()
            _, messages = self.run_download(tmp)
            self.assertIn("уже было 3", messages[-1][0])
            self.assertNotIn("/ok1.jpg", hits)
            self.assertIn("/gone3a.jpg", hits)


if __name__ == "__main__":
    unittest.main()
