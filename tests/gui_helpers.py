"""Общая подготовка окна для GUI-тестов: временный профиль, без сети и без проверки ffmpeg."""
import os
import sys
import tempfile
from unittest import mock

GUI_AVAILABLE = sys.platform == "win32" and not os.environ.get("MH_SKIP_GUI")


class AppHarness:
    """Создаёт MediaHarvesterApp в изолированном профиле. Использовать в setUpClass / tearDownClass."""

    def __init__(self):
        self._env = mock.patch.dict(os.environ, {"LOCALAPPDATA": tempfile.mkdtemp()})
        self._env.start()
        import src.ui.engine_status as engine_status
        self._patches = [
            mock.patch.object(engine_status, "check_ffmpeg", lambda: (True, "7")),
            mock.patch.object(engine_status, "check_for_update",
                              lambda: type("R", (), {"status": "current", "latest": "", "message": ""})()),
        ]
        for patch in self._patches:
            patch.start()
        from src.ui.app import MediaHarvesterApp
        self.app = MediaHarvesterApp()
        self.app.settings.save = lambda: None  # настройки в тестах на диск не пишем
        self.app.update()

    def close(self):
        self.app.destroy()
        for patch in self._patches:
            patch.stop()
        self._env.stop()

    def select_mode(self, fragment: str):
        """Выбирает режим по фрагменту названия и применяет его, как при выборе в списке."""
        from src.config import CONTENT_MODES
        name = next(m for m in CONTENT_MODES if fragment in m)
        self.app.combo_mode.set(name)
        self.app.on_mode_change(name)
        self.app.update()
        return name
