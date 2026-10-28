import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from src import cli, mcp_server
from src.core import headless, media_tools
from src.utils.helpers import FFMPEG_PATH

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def make_video(folder: str, seconds: int = 4) -> str:
    """Короткое тестовое видео (цветная таблица ffmpeg) без сети."""
    path = os.path.join(folder, "clip.mp4")
    subprocess.run([FFMPEG_PATH, "-loglevel", "error", "-f", "lavfi", "-i",
                    f"testsrc=duration={seconds}:size=320x240:rate=10", "-pix_fmt", "yuv420p", "-y", path],
                   check=True, capture_output=True)
    return path


class ArgumentTests(unittest.TestCase):
    def test_gui_or_cli(self):
        self.assertFalse(cli.wants_cli(["mediaharvester"]))
        # Ярлык передаёт ссылку (%U): это окно, а не командная строка
        self.assertFalse(cli.wants_cli(["mediaharvester", "https://youtu.be/x"]))
        for arg in ("download", "mcp", "--help", "--version", "frames"):
            self.assertTrue(cli.wants_cli(["mediaharvester", arg]), arg)

    def test_time_formats(self):
        self.assertEqual(cli.parse_time("90"), 90)
        self.assertEqual(cli.parse_time("1:30"), 90)
        self.assertEqual(cli.parse_time("1:02:03.5"), 3723.5)
        with self.assertRaises(Exception):
            cli.parse_time("1:xx")

    def test_quality_aliases(self):
        self.assertEqual(headless.quality_choice("best"), "Максимальное (Авто)")
        self.assertEqual(headless.quality_choice("720p"), "HD (720p)")
        self.assertEqual(headless.quality_choice("4K"), "4K (2160p)")
        self.assertIn("Только аудио", headless.quality_choice("audio"))
        with self.assertRaises(ValueError):
            headless.quality_choice("999")

    def test_download_options_parse(self):
        args = cli.build_parser().parse_args(
            ["download", "-q", "480", "--subs", "ru,en", "--no-playlist", "--limit", "3", "URL"])
        self.assertEqual((args.quality, args.subs, args.playlist, args.limit), ("480", ["ru", "en"], False, 3))
        self.assertIsNone(cli.build_parser().parse_args(["download", "URL"]).playlist)

    def test_no_command_prints_help(self):
        with mock.patch("sys.stdout") as out:
            self.assertEqual(cli.main([]), cli.EXIT_USAGE)
        self.assertTrue(out.write.called)


class TranscriptTests(unittest.TestCase):
    def test_rolling_auto_captions_are_deduplicated(self):
        vtt = ("WEBVTT\nKind: captions\nLanguage: en\n\n"
               "00:00:01.000 --> 00:00:03.000\nhello <c>world</c>\n\n"
               "00:00:03.000 --> 00:00:05.000\nhello world\nhow are you\n\n"
               "00:01:05.500 --> 00:01:07.000\nhow are you\nfine &amp; you\n")
        self.assertEqual(media_tools.subtitles_to_text(vtt),
                         "[00:01] hello world\n[00:03] how are you\n[01:05] fine & you")
        self.assertEqual(media_tools.subtitles_to_text(vtt, timestamps=False).splitlines()[0], "hello world")

    def test_srt(self):
        srt = "1\n00:00:02,000 --> 00:00:04,000\nПривет\n\n2\n01:00:00,000 --> 01:00:01,000\nПока\n"
        self.assertEqual(media_tools.subtitles_to_text(srt), "[00:02] Привет\n[1:00:00] Пока")

    def test_track_choice(self):
        info = {
            "language": "en",
            "subtitles": {"de": [{"ext": "vtt", "url": "de"}], "live_chat": [{"ext": "json", "url": "x"}]},
            "automatic_captions": {"en-orig": [{"ext": "vtt", "url": "en-orig"}],
                                   "en": [{"ext": "vtt", "url": "en"}], "ru": [{"ext": "srt", "url": "ru"}]},
        }
        self.assertEqual(media_tools._pick_track(info, ["ru"]), ("ru", True, {"ext": "srt", "url": "ru"}))
        # Без пожеланий: настоящие субтитры важнее автоматических
        self.assertEqual(media_tools._pick_track(info, [])[0], "de")
        self.assertEqual(media_tools._pick_track(info, ["en"])[0], "en-orig")
        self.assertIsNone(media_tools._pick_track(info, ["fr"]))

    def test_local_file_uses_subtitles_next_to_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "Clip.webm")
            open(video, "wb").close()
            with open(os.path.join(tmp, "Clip.en.srt"), "w", encoding="utf-8") as f:
                f.write("1\n00:00:01,000 --> 00:00:02,000\nhi\n")
            data = media_tools.fetch_transcript(video)
            self.assertEqual((data["language"], data["text"]), ("en", "[00:01] hi"))
            os.remove(os.path.join(tmp, "Clip.en.srt"))
            with self.assertRaises(RuntimeError):
                media_tools.fetch_transcript(video)


@unittest.skipUnless(FFMPEG_PATH, "нужен ffmpeg")
class FramesTests(unittest.TestCase):
    def test_even_frames_and_exact_moments(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = make_video(tmp)
            self.assertAlmostEqual(media_tools.media_duration(video), 4.0, delta=0.2)
            data = media_tools.extract_frames(video, count=4, width=160, out_dir=os.path.join(tmp, "f"))
            self.assertEqual([f["time"] for f in data["frames"]], [0.5, 1.5, 2.5, 3.5])
            for frame in data["frames"]:
                with open(frame["path"], "rb") as f:
                    self.assertEqual(f.read(2), b"\xff\xd8")  # JPEG
            data = media_tools.extract_frames(video, timestamps=[1, 100], out_dir=os.path.join(tmp, "g"))
            self.assertEqual(len(data["frames"]), 2)
            self.assertLess(data["frames"][1]["time"], 4.0)  # дальше конца — последний кадр

    def test_missing_file(self):
        with self.assertRaises(RuntimeError):
            media_tools.extract_frames("/no/such/file.mp4")


class HeadlessTests(unittest.TestCase):
    def test_new_and_changed_files_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.path.join(tmp, "old.mp4")
            open(old, "wb").close()
            before = headless._snapshot(tmp)
            os.makedirs(os.path.join(tmp, "album"))
            new = os.path.join(tmp, "album", "1.jpg")
            open(new, "wb").close()
            open(os.path.join(tmp, "x.mp4.part"), "wb").close()
            self.assertEqual(headless._changed_files(tmp, before), [new])

    def test_errors_do_not_mention_window_buttons(self):
        message, hint = headless.explain(KeyError("boom"))
        self.assertTrue(message)
        self.assertNotIn("Подробнее", hint)


class McpTests(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.server = mcp_server.Server(self.sent.append)

    def call(self, method, params=None, msg_id=1):
        return self.server.handle({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}})

    def test_handshake_and_tools(self):
        result = self.call("initialize", {"protocolVersion": "2025-03-26"})["result"]
        self.assertEqual(result["protocolVersion"], "2025-03-26")
        self.assertIn("tools", result["capabilities"])
        self.assertEqual(self.call("initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"],
                         mcp_server.SUPPORTED_VERSIONS[0])
        names = [t["name"] for t in self.call("tools/list")["result"]["tools"]]
        self.assertEqual(names, ["download", "media_info", "get_transcript", "get_frames"])
        self.assertIsNone(self.server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual(self.call("nope")["error"]["code"], -32601)
        self.assertEqual(self.call("tools/call", {"name": "nope"})["error"]["code"], -32602)

    def test_tool_errors_are_results(self):
        result = self.call("tools/call", {"name": "get_frames", "arguments": {"source": "/no/such.mp4"}})["result"]
        self.assertTrue(result["isError"])
        self.assertIn("/no/such.mp4", result["content"][0]["text"])
        result = self.call("tools/call", {"name": "download", "arguments": {"urls": ["x"], "quality": "9"}})
        self.assertTrue(result["result"]["isError"])

    @unittest.skipUnless(FFMPEG_PATH, "нужен ffmpeg")
    def test_frames_are_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = make_video(tmp)
            with mock.patch.object(media_tools, "frames_dir_for", return_value=os.path.join(tmp, "f")):
                result = self.call("tools/call", {"name": "get_frames",
                                                  "arguments": {"source": video, "count": 2}})["result"]
            self.assertFalse(result["isError"])
            images = [c for c in result["content"] if c["type"] == "image"]
            self.assertEqual(len(images), 2)
            self.assertEqual(images[0]["mimeType"], "image/jpeg")

    def test_stdio_server_keeps_stdout_clean(self):
        """Процесс `main.py mcp`: в stdout только JSON-RPC, по строке на сообщение."""
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "main.py"), "mcp"],
            input=(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
                   + "not json\n"
                   + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n").encode(),
            capture_output=True, timeout=120, env=env, cwd=ROOT)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace")[-500:])
        messages = [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines()]
        by_id = {m.get("id"): m for m in messages}
        self.assertEqual(len(messages), 3)
        self.assertEqual(by_id[1]["result"]["serverInfo"]["name"], "mediaharvester")
        self.assertEqual(by_id[None]["error"]["code"], -32700)  # строку «not json» отвергает поток чтения
        self.assertEqual(len(by_id[2]["result"]["tools"]), 4)


if __name__ == "__main__":
    unittest.main()
