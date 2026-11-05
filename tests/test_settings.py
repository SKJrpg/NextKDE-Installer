"""Remembered language and source choices, independent of the install itself."""

from __future__ import annotations

import shutil
import tempfile
import unittest

from installer import settings
from installer.paths import Paths


class SettingsTest(unittest.TestCase):
    def paths(self) -> Paths:
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        return Paths.resolve(env={"XDG_STATE_HOME": directory})

    def test_a_choice_is_remembered_and_the_other_survives(self) -> None:
        paths = self.paths()
        settings.save(paths, lang="zh")
        self.assertEqual(settings.load(paths), {"lang": "zh"})
        settings.save(paths, source="main")
        self.assertEqual(settings.load(paths), {"lang": "zh", "source": "main"})

    def test_a_broken_file_and_unknown_values_are_ignored(self) -> None:
        paths = self.paths()
        paths.settings_file.parent.mkdir(parents=True)
        paths.settings_file.write_text("not json", encoding="utf-8")
        self.assertEqual(settings.load(paths), {})
        paths.settings_file.write_text(
            '{"lang": "fr", "source": "nope", "other": 1}', encoding="utf-8")
        self.assertEqual(settings.load(paths), {})

    def test_saving_only_unknown_values_creates_nothing(self) -> None:
        paths = self.paths()
        settings.save(paths, lang="fr", source="nope")
        self.assertFalse(paths.settings_file.exists())


if __name__ == "__main__":
    unittest.main()
