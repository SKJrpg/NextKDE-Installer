from __future__ import annotations

import unittest
from pathlib import Path

from installer.ui.screens.review import compact_path


class CompactPathTest(unittest.TestCase):
    def test_managed_checkout_id_is_elided(self) -> None:
        root = Path.home() / ".local/share/nextkde/sources"
        command = root / "NextKde.NextKde" / ("a" * 40) / "tools/kosctl"
        self.assertEqual(compact_path(str(command), root),
                         "~/.local/share/nextkde/sources/…/tools/kosctl")


if __name__ == "__main__":
    unittest.main()
