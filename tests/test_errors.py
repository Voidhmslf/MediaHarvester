import errno
import os
import tempfile
import threading
import unittest
from unittest import mock

from src.core.download_queue import QueueItem, run_queue, ERROR, DONE
from src.utils import logger as lg
from src.utils.errors import explain_error
from src.utils.report import build_report


def kind(exc):
    return explain_error(exc).kind


class ExplainTests(unittest.TestCase):
    def test_ytdlp_messages(self):
        cases = {
            "ERROR: [youtube] abc: Sign in to confirm you’re not a bot. Use --cookies": "bot_check",
            "ERROR: [youtube] abc: Sign in to confirm your age. This video may be inappropriate": "age",
            "ERROR: [youtube] abc: Private video. Sign in if you've been granted access": "login",
            "ERROR: [youtube] abc: Join this channel to get access to members-only content": "members",
            "ERROR: [youtube] abc: Video unavailable": "unavailable",
            "ERROR: [youtube] abc: The uploader has not made this video available in your country": "geo",
            "ERROR: Requested format is not available. Use --list-formats": "format",
            "ERROR: Unsupported URL: https://example.com/x": "unsupported",
            "ERROR: [youtube] abc: This live event will begin in 2 hours": "live",
            "ERROR: unable to download video data: HTTP Error 403: Forbidden": "forbidden",
            "ERROR: [youtube] abc: Unable to extract nsig function": "broken_extractor",
            "ERROR: unable to download video data: HTTP Error 429: Too Many Requests": "rate_limit",
            "ERROR: [generic] Unable to download webpage: <urlopen error [Errno 11001] getaddrinfo failed>": "network",
            "ERROR: [youtube] abc: SSL: CERTIFICATE_VERIFY_FAILED": "ssl",
            "ERROR: Postprocessing: ffprobe and ffmpeg not found": "ffmpeg",
        }
        for text, expected in cases.items():
            self.assertEqual(kind(RuntimeError(text)), expected, text)

    def test_every_known_error_has_message_and_hint(self):
        for text in ("Video unavailable", "HTTP Error 403: Forbidden", "getaddrinfo failed"):
            info = explain_error(RuntimeError(text))
            self.assertTrue(info.message and info.hint)

    def test_os_errors(self):
        self.assertEqual(kind(OSError(errno.ENOSPC, "No space left on device")), "disk_full")
        self.assertEqual(kind(PermissionError(errno.EACCES, "denied")), "permission")
        self.assertEqual(kind(OSError(errno.ENAMETOOLONG, "File name too long")), "path_too_long")

    def test_os_error_wrapped_as_cause(self):
        try:
            try:
                raise OSError(errno.ENOSPC, "No space left on device")
            except OSError as e:
                raise RuntimeError("download failed") from e
        except RuntimeError as exc:
            self.assertEqual(kind(exc), "disk_full")

    def test_friendly_engine_messages_are_kept(self):
        info = explain_error(RuntimeError("Альбом закрыт настройками приватности."))
        self.assertEqual(info.message, "Альбом закрыт настройками приватности.")
        info = explain_error(RuntimeError("Instagram временно ограничил запросы (429). Укажите cookies.txt"))
        self.assertIn("Instagram", info.message)

    def test_unknown_error_is_generic_and_points_to_details(self):
        info = explain_error(ValueError("zzz strange"))
        self.assertEqual(info.kind, "unknown")
        self.assertIn("Подробнее", info.hint)
        self.assertIn("ValueError", info.technical)

    def test_technical_text_is_redacted(self):
        info = explain_error(RuntimeError("fail https://x.test/a?access_token=abcdef123456&x=1"))
        self.assertNotIn("abcdef123456", info.technical)


class LoggerTests(unittest.TestCase):
    def test_redaction(self):
        lg.register_secret("vk1.a.SECRETTOKENVALUE")
        text = lg.redact("url=https://api/x?access_token=zzz111&v=5 raw vk1.a.SECRETTOKENVALUE end")
        self.assertNotIn("zzz111", text)
        self.assertNotIn("SECRETTOKENVALUE", text)
        self.assertIn("v=5", text)

    def test_log_file_written_and_masked(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(lg, "get_app_data_dir", lambda: tmp):
            lg._configured = False
            logger = lg.setup_logging()
            try:
                lg.get_logger("t").info("token=supersecretvalue ok")
                for h in logger.handlers:
                    h.flush()
                with open(lg.get_log_path(), encoding="utf-8") as fh:
                    content = fh.read()
                self.assertIn("ok", content)
                self.assertNotIn("supersecretvalue", content)
            finally:
                for h in list(logger.handlers):
                    h.close()
                    logger.removeHandler(h)
                lg._configured = False


class QueueErrorTests(unittest.TestCase):
    def test_failed_item_gets_explanation(self):
        items = [QueueItem("https://youtu.be/a"), QueueItem("https://youtu.be/b")]

        def run_one(item, n, total):
            if item.url.endswith("a"):
                raise RuntimeError("ERROR: [youtube] a: Video unavailable")
            return "/ok"

        summary = run_queue(items, run_one, threading.Event(), lambda: None)
        self.assertEqual((summary["done"], summary["failed"]), (1, 1))
        bad = items[0]
        self.assertEqual(bad.status, ERROR)
        self.assertIn("недоступн", bad.message)
        self.assertTrue(bad.hint)
        self.assertIn("Video unavailable", bad.technical)
        self.assertEqual(items[1].status, DONE)

    def test_report_contains_errors_without_secrets(self):
        item = QueueItem("https://x.test/?access_token=leakme123", message="m", hint="h", technical="t")
        report = build_report([item], {"ytdlp": "2026.01.01", "ffmpeg": (True, "7.1")})
        self.assertIn("2026.01.01", report)
        self.assertIn("Что делать: h", report)
        self.assertNotIn("leakme123", report)


if __name__ == "__main__":
    unittest.main()
