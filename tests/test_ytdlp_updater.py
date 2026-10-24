import hashlib
import http.server
import os
import re
import socketserver
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from unittest import mock

import yt_dlp

from src.utils import ytdlp_updater as up

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAKE_VERSION = "2099.01.01"


def build_fake_release(path: str, version: str = FAKE_VERSION) -> None:
    """Собирает zip как у официального релиза: пакет yt_dlp в корне архива."""
    pkg_dir = os.path.dirname(yt_dlp.__file__)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for base, dirs, files in os.walk(pkg_dir):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in files:
                full = os.path.join(base, name)
                arc = os.path.join("yt_dlp", os.path.relpath(full, pkg_dir)).replace("\\", "/")
                if arc == "yt_dlp/version.py":
                    with open(full, encoding="utf-8") as src:
                        text = src.read()
                    text = re.sub(r"__version__\s*=\s*'[^']*'", f"__version__ = '{version}'", text)
                    zf.writestr(arc, text)
                else:
                    zf.write(full, arc)


class VersionTests(unittest.TestCase):
    def test_ordering(self):
        self.assertLess(up.version_key("2026.08.19"), up.version_key("2026.10.01"))
        self.assertLess(up.version_key("2026.10.01"), up.version_key("2026.10.01.123456"))
        self.assertEqual(up.version_key("2026.10.01"), up.version_key("2026.10.01"))


class ActivationTests(unittest.TestCase):
    def run_probe(self, appdata: str) -> list[str]:
        code = (
            "from src.utils.ytdlp_updater import activate_override\n"
            "print(activate_override())\n"
            "import yt_dlp, yt_dlp.version as v\n"
            "from yt_dlp.extractor import gen_extractors\n"
            "print(v.__version__)\n"
            "print('zip' if '.zip' in yt_dlp.__file__ else 'bundled')\n"
        )
        env = dict(os.environ, LOCALAPPDATA=appdata, XDG_DATA_HOME=appdata, HOME=appdata)
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.split()

    def appdata_with(self, tmp: str) -> str:
        zip_dir = os.path.join(tmp, "MediaHarvester", "yt-dlp")
        os.makedirs(zip_dir, exist_ok=True)
        return zip_dir

    def test_override_wins_over_bundled(self):
        with tempfile.TemporaryDirectory() as tmp:
            build_fake_release(os.path.join(self.appdata_with(tmp), "yt-dlp.zip"))
            active, version, source = self.run_probe(tmp)
            self.assertEqual((active, version, source), (FAKE_VERSION, FAKE_VERSION, "zip"))

    def test_corrupt_override_falls_back_and_is_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(self.appdata_with(tmp), "yt-dlp.zip")
            with open(path, "wb") as f:
                f.write(b"not a zip")
            active, version, source = self.run_probe(tmp)
            self.assertEqual((active, source), ("None", "bundled"))
            self.assertFalse(os.path.exists(path))

    def test_older_override_is_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(self.appdata_with(tmp), "yt-dlp.zip")
            build_fake_release(path, version="2000.01.01")
            active, version, source = self.run_probe(tmp)
            self.assertEqual((active, source), ("None", "bundled"))
            self.assertFalse(os.path.exists(path))


class _Handler(http.server.BaseHTTPRequestHandler):
    payload = b""
    sums = ""

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/releases/latest":
            self.send_response(302)
            self.send_header("Location", f"/releases/tag/{FAKE_VERSION}")
            self.end_headers()
        elif self.path == f"/releases/tag/{FAKE_VERSION}":
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
        elif self.path.endswith("/yt-dlp"):
            self.send_response(200); self.end_headers(); self.wfile.write(_Handler.payload)
        elif self.path.endswith("/SHA2-256SUMS"):
            self.send_response(200); self.end_headers(); self.wfile.write(_Handler.sums.encode())
        else:
            self.send_response(404); self.end_headers()


class UpdateFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        release = os.path.join(cls.tmp, "release.zip")
        build_fake_release(release)
        with open(release, "rb") as f:
            cls.payload = f.read()
        cls.good_sum = hashlib.sha256(cls.payload).hexdigest()
        cls.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.appdata = tempfile.mkdtemp()
        patches = [
            mock.patch.object(up, "get_app_data_dir", lambda: self.appdata),
            mock.patch.object(up, "RELEASES_LATEST_URL", self.base + "/releases/latest"),
            mock.patch.object(up, "DOWNLOAD_URL_TEMPLATE", self.base + "/releases/download/{tag}/{name}"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        _Handler.payload = self.payload
        _Handler.sums = f"{self.good_sum}  yt-dlp\n{'0' * 64}  yt-dlp.exe\n"

    def test_downloads_verified_release(self):
        result = up.check_for_update(force=True)
        self.assertEqual((result.status, result.latest), ("updated", FAKE_VERSION), result.message)
        self.assertEqual(up.read_zip_version(up.override_path()), FAKE_VERSION)

    def test_second_check_is_throttled(self):
        up.check_for_update(force=True)
        self.assertEqual(up.check_for_update().status, "skipped")

    def test_bad_checksum_is_rejected(self):
        _Handler.sums = f"{'f' * 64}  yt-dlp\n"
        result = up.check_for_update(force=True)
        self.assertEqual(result.status, "error")
        self.assertFalse(os.path.exists(up.override_path()))
        self.assertFalse(os.path.exists(up.override_path() + ".download"))

    def test_up_to_date_does_nothing(self):
        with mock.patch.object(up, "current_version", lambda: FAKE_VERSION):
            result = up.check_for_update(force=True)
        self.assertEqual(result.status, "current")
        self.assertFalse(os.path.exists(up.override_path()))

    def test_network_failure_is_not_fatal(self):
        with mock.patch.object(up, "RELEASES_LATEST_URL", "http://127.0.0.1:9/nope"):
            self.assertEqual(up.check_for_update(force=True).status, "error")


if __name__ == "__main__":
    unittest.main()
