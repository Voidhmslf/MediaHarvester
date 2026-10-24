import unittest
from unittest import mock

from src.core import vk_diag


def res(ok, text="OK", code=None, data=None):
    return vk_diag.CallResult(ok, text, code=code, data=data, details="http=200 0.1s")


class DiagnosticsTests(unittest.TestCase):
    def run_with(self, responder):
        with mock.patch.object(vk_diag, "_call", side_effect=responder), \
                mock.patch.object(vk_diag, "REQUEST_PAUSE", 0), \
                mock.patch.object(vk_diag, "HOSTS", ("api.vk.com",)), \
                mock.patch.object(vk_diag, "VERSIONS", ("5.131",)):
            return vk_diag.run_diagnostics("SECRET-TOKEN-VALUE", "music", {"kate": "UA1", "none": ""})

    def test_working_token(self):
        def responder(host, method, params, ua, transport="curl", timeout=15.0):
            if method == "users.get":
                return res(True, data=[{"id": 7}])
            return res(True, data={"count": 1})
        summary, lines = self.run_with(responder)
        self.assertTrue(summary.startswith("Токен рабочий"))
        self.assertTrue(any("[этап 2]" in line for line in lines))

    def test_audio_unknown_method_is_reported_with_users_ok(self):
        def responder(host, method, params, ua, transport="curl", timeout=15.0):
            if method in ("users.get", "account.getProfileInfo"):
                return res(True, data=[{"id": 7}])
            return res(False, "ошибка 3: Unknown method passed", code=3)
        summary, _ = self.run_with(responder)
        self.assertIn("users.get OK", summary)
        self.assertIn("ошибка 3", summary)

    def test_flood_is_not_reported_as_bad_token_and_stops_early(self):
        calls = []

        def responder(host, method, params, ua, transport="curl", timeout=15.0):
            calls.append(method)
            return res(False, "ошибка 9: Flood control", code=9)
        summary, lines = self.run_with(responder)
        self.assertIn("ограничение частоты", summary)
        self.assertNotIn("войдите заново", summary)
        self.assertFalse(any("[этап 2]" in line for line in lines))
        self.assertLessEqual(len(calls), 6)

    def test_rejected_token(self):
        summary, _ = self.run_with(lambda *a, **k: res(False, "ошибка 5: User authorization failed", code=5))
        self.assertIn("войдите заново", summary)

    def test_token_never_appears_in_report(self):
        _, lines = self.run_with(lambda *a, **k: res(False, "ошибка 3", code=3))
        self.assertNotIn("SECRET-TOKEN-VALUE", "\n".join(lines))


if __name__ == "__main__":
    unittest.main()
