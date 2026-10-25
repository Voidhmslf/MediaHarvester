import http.server
import os
import socketserver
import threading
import unittest

from src.core.vk_auth import (BLANK_PREFIX, _is_success_url, _message_shape,
                              _url_shape, find_auth_result, find_token_in_message, login_in_window,
                              parse_auth_url)

try:
    import webview  # noqa: F401
    HAVE_WEBVIEW = True
except Exception:
    HAVE_WEBVIEW = False


class ParseTests(unittest.TestCase):
    def test_token_in_fragment(self):
        r = parse_auth_url(BLANK_PREFIX + "#access_token=vk1.a.TOKEN&expires_in=0&user_id=123")
        self.assertEqual((r.token, r.user_id, r.expires_in), ("vk1.a.TOKEN", "123", "0"))

    def test_error_in_fragment(self):
        r = parse_auth_url(BLANK_PREFIX + "#error=access_denied&error_description=User+denied+access")
        self.assertEqual((r.token, r.error, r.error_description), ("", "access_denied", "User denied access"))

    def test_plain_pages_are_ignored(self):
        self.assertIsNone(parse_auth_url("https://oauth.vk.com/authorize?client_id=1"))
        self.assertIsNone(parse_auth_url(""))

    def test_find_in_clipboard_text(self):
        text = "что-то\n" + BLANK_PREFIX + "#access_token=TOK123456&expires_in=0&user_id=7  хвост"
        self.assertEqual(find_auth_result(text).token, "TOK123456")
        self.assertIsNone(find_auth_result("https://evil.test/blank.html#access_token=TOK"))
        self.assertIsNone(find_auth_result("просто текст"))


class SuccessUrlTests(unittest.TestCase):
    def test_vk_hosts_with_token_are_accepted_even_if_domain_changes(self):
        for host in ("oauth.vk.com", "oauth.vk.ru", "id.vk.com"):
            url = f"https://{host}/blank.html#access_token=TOK&user_id=1"
            self.assertTrue(_is_success_url(url, BLANK_PREFIX), url)

    def test_plain_vk_pages_and_foreign_hosts_are_rejected(self):
        self.assertFalse(_is_success_url("https://oauth.vk.com/authorize?client_id=1", BLANK_PREFIX))
        self.assertFalse(_is_success_url("https://evil.test/blank.html#access_token=TOK", BLANK_PREFIX))
        self.assertFalse(_is_success_url("https://notvk.com/x#access_token=TOK", BLANK_PREFIX))

    def test_diagnostic_shape_hides_values(self):
        shape = _url_shape("https://oauth.vk.com/blank.html#access_token=SECRET&user_id=5")
        self.assertNotIn("SECRET", shape)
        self.assertIn("access_token", shape)


class MessageTests(unittest.TestCase):
    def test_token_found_in_nested_json_message(self):
        msg = '{"type":"VKWebAppOAuthResult","payload":{"access_token":"vk1.a.ABCDEFGHIJKLMNOPQRSTUV","user_id":1}}'
        self.assertEqual(find_token_in_message(msg), "vk1.a.ABCDEFGHIJKLMNOPQRSTUV")

    def test_token_found_in_url_string_message(self):
        msg = '"' + BLANK_PREFIX + '#access_token=vk1.a.ABCDEFGHIJKLMNOPQRSTUV&user_id=1"'
        self.assertEqual(find_token_in_message(msg), "vk1.a.ABCDEFGHIJKLMNOPQRSTUV")

    def test_unrelated_or_short_values_are_ignored(self):
        self.assertIsNone(find_token_in_message('{"type":"ready","token":"short"}'))
        self.assertIsNone(find_token_in_message("hello"))
        self.assertIsNone(find_token_in_message("[1,2,3]"))

    def test_shape_hides_values(self):
        shape = _message_shape('{"access_token":"SECRETVALUE","n":5}')
        self.assertNotIn("SECRETVALUE", shape)
        self.assertIn("access_token", shape)


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if self.path.startswith("/ok"):
            body = ("<script>setTimeout(()=>location.href='/blank.html#access_token=TESTTOKEN123456"
                    "&expires_in=0&user_id=42',500)</script>")
        elif self.path.startswith("/msg"):
            body = ("<script>setTimeout(()=>{window.chrome.webview.postMessage({payload:{access_token:"
                    "'TESTMSGTOKEN1234567890XYZ'}});setTimeout(()=>location.href='/blank.html',400)},500)</script>")
        elif self.path.startswith("/bridge"):
            body = ("<script>setTimeout(()=>{ if(window.chrome&&window.chrome.webview){location.href='/blank.html'}"
                    "else{location.href='/blank.html#access_token=NOBRIDGETOKEN1234567890&user_id=3'} },500)</script>")
        elif self.path.startswith("/never"):
            body = "<script>setTimeout(()=>location.href='/blank.html',500)</script>"
        elif self.path.startswith("/deny"):
            body = ("<script>setTimeout(()=>location.href='/blank.html#error=access_denied"
                    "&error_description=User+denied',500)</script>")
        else:
            body = "page"
        self.wfile.write(body.encode())


@unittest.skipUnless(HAVE_WEBVIEW and os.name == "nt" and not os.environ.get("MH_SKIP_GUI"),
                     "нужны pywebview и Windows (окно открывается на несколько секунд)")
class LoginWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def login(self, path, **kw):
        return login_in_window(self.base + path, success_prefix=self.base + "/blank.html", **kw)

    def test_token_is_captured_from_redirect(self):
        out = self.login("/ok", timeout=90)
        self.assertEqual(out.status, "ok")
        self.assertEqual((out.result.token, out.result.user_id), ("TESTTOKEN123456", "42"))

    def test_denied(self):
        out = self.login("/deny", timeout=90)
        self.assertEqual((out.status, out.detail), ("denied", "User denied"))

    def test_token_delivered_as_page_message(self):
        out = self.login("/msg", timeout=90)
        self.assertEqual((out.status, out.result.token), ("ok", "TESTMSGTOKEN1234567890XYZ"))

    def test_retry_without_webview_bridge_gets_redirect_token(self):
        out = self.login("/bridge", timeout=90)
        self.assertEqual((out.status, out.result.token), ("ok", "NOBRIDGETOKEN1234567890"))

    def test_no_token_anywhere_falls_back_to_browser(self):
        self.assertEqual(self.login("/never", timeout=90).status, "unavailable")

    def test_cancel_closes_window(self):
        ev = threading.Event()
        threading.Timer(4, ev.set).start()
        self.assertEqual(self.login("/stay", cancel_event=ev, timeout=90).status, "cancelled")


if __name__ == "__main__":
    unittest.main()
