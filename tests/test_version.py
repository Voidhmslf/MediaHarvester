import os
import re
import unittest

from src.version import APP_NAME, __version__
from tests.gui_helpers import GUI_AVAILABLE, AppHarness

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name: str) -> str:
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


class VersionConsistencyTests(unittest.TestCase):
    def test_version_is_semver(self):
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")

    def test_readme_badge_uses_current_version(self):
        readme = read("README.md")
        self.assertIn(f"Release-v{__version__}-", readme)
        self.assertNotRegex(readme, r"Release-v(?!%s-)" % re.escape(__version__))

    def test_changelog_top_section_is_current_version(self):
        sections = re.findall(r"^## \[([^\]]+)\]", read("CHANGELOG.md"), flags=re.M)
        self.assertEqual(sections[0], __version__)
        self.assertEqual(len(sections), len(set(sections)), "версии в CHANGELOG не должны повторяться")

    def test_spec_takes_version_from_single_source(self):
        spec = read("MediaHarvester.spec")
        self.assertIn("src', 'version.py'", spec)
        self.assertNotIn(f"'{__version__}'", spec)  # версия не прописана вручную

    def test_changelog_mentions_no_unreleased_placeholders(self):
        self.assertNotIn("TODO", read("CHANGELOG.md"))


@unittest.skipUnless(GUI_AVAILABLE, "нужен рабочий стол Windows")
class VersionInWindowTests(unittest.TestCase):
    def test_title_shows_version(self):
        harness = AppHarness()
        try:
            self.assertEqual(harness.app.title(), f"{APP_NAME} {__version__}")
        finally:
            harness.close()


if __name__ == "__main__":
    unittest.main()
