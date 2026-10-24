import unittest
from unittest import mock

from src.core import vk_diag


class DiagnosticsTests(unittest.TestCase):
    def run_with(self, responder):
        with mock.patch.object(vk_diag, "_call", side_effect=responder), \
                mock.patch.object(vk_diag, "REQUEST_PAUSE", 0), \
                mock.patch.object(vk_diag, "HOSTS", ("api.vk.com",)), \
                mock.patch.object(vk_diag, "VERSIONS", ("5.131",)):
            return vk_diag.run_diagnostics("SECRET-TOKEN-VALUE", "music", {"kate": "UA1", "none": ""})

    def test_working_token(self):
        def responder(host, method, params, ua, timeout=15.0):
            return (True, "OK", [{"id": 7}]) if method == "users.get" else (True, "OK", {"count": 1})
        summary, lines = self.run_with(responder)
        self.assertTrue(summary.startswith("Токен рабочий"))
        self.assertTrue(all("OK" in l for l in lines))

    def test_audio_unknown_method_is_reported_with_users_ok(self):
        def responder(host, method, params, ua, timeout=15.0):
            if method == "users.get":
                return True, "OK", [{"id": 7}]
            return False, "ошибка 3: Unknown method passed", None
        summary, _ = self.run_with(responder)
        self.assertIn("users.get OK", summary)
        self.assertIn("ошибка 3", summary)

    def test_rejected_token(self):
        summary, _ = self.run_with(lambda *a, **k: (False, "ошибка 5: User authorization failed", None))
        self.assertIn("войдите заново", summary)

    def test_token_never_appears_in_report(self):
        _, lines = self.run_with(lambda host, method, params, ua, timeout=15.0: (False, "ошибка 3", None))
        self.assertNotIn("SECRET-TOKEN-VALUE", "\n".join(lines))


if __name__ == "__main__":
    unittest.main()
