"""Stage T1: the appearance mode decides how secondary text is drawn.

The palette is the terminal's own; only the mode is detected, so a terminal
that does not report one falls back to dark and `--theme` overrides it.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_VENDOR = ROOT / "vendor"
if _VENDOR.is_dir():
    sys.path.insert(0, str(_VENDOR))
HAS_TEXTUAL = importlib.util.find_spec("textual") is not None

from installer.ui.theme import resolve_mode  # noqa: E402

if HAS_TEXTUAL:
    from installer.detect import OsInfo, Probe, System
    from installer.paths import Paths
    from installer.ui.app import KosApp


def fake_system() -> "System":
    return System(
        os=OsInfo(id="cachyos", version="", like=("arch",), pretty="CachyOS"),
        family="arch",
        method="kosctl",
        arch="x86_64",
        probes=[Probe("probe_os", "PASS", "CachyOS")],
    )


class ResolveModeTest(unittest.TestCase):
    def test_a_terminal_that_reports_nothing_is_dark(self) -> None:
        self.assertEqual(resolve_mode(None, {}), "dark")

    def test_colorfgbg_background_decides(self) -> None:
        self.assertEqual(resolve_mode(None, {"COLORFGBG": "15;0"}), "dark")
        self.assertEqual(resolve_mode(None, {"COLORFGBG": "0;8"}), "dark")
        self.assertEqual(resolve_mode(None, {"COLORFGBG": "0;7"}), "light")
        self.assertEqual(resolve_mode(None, {"COLORFGBG": "0;15"}), "light")

    def test_explicit_wins_over_everything(self) -> None:
        env = {"KOS_THEME": "dark", "COLORFGBG": "0;15"}
        self.assertEqual(resolve_mode("dark", env), "dark")
        self.assertEqual(resolve_mode("light", env), "light")

    def test_kos_theme_wins_over_colorfgbg(self) -> None:
        self.assertEqual(resolve_mode(None, {"KOS_THEME": "dark", "COLORFGBG": "0;15"}),
                         "dark")
        self.assertEqual(resolve_mode(None, {"KOS_THEME": "light", "COLORFGBG": "15;0"}),
                         "light")

    def test_system_and_unknown_values_detect(self) -> None:
        self.assertEqual(resolve_mode("system", {"COLORFGBG": "0;15"}), "light")
        self.assertEqual(resolve_mode("bogus", {"KOS_THEME": "nope"}), "dark")


@unittest.skipUnless(HAS_TEXTUAL, "textual is not vendored (run tools/vendor.py)")
class AppModeTest(unittest.IsolatedAsyncioTestCase):
    def make_app(self, mode: str | None) -> "KosApp":
        return KosApp(lang="en", system=fake_system(), mode=mode,
                      paths=Paths.resolve(source_root=ROOT))

    def test_mode_sets_dark_and_the_secondary_style(self) -> None:
        light = self.make_app("light")
        self.assertIs(light.dark, False)
        self.assertEqual(light.theme_mode, "light")
        self.assertEqual(light.secondary_style, "bright_black")
        dark = self.make_app("dark")
        self.assertIs(dark.dark, True)
        self.assertEqual(dark.theme_mode, "dark")
        self.assertEqual(dark.secondary_style, "dim")

    async def test_secondary_line_is_styled_by_mode(self) -> None:
        # The rendered span carries the terminal's own ANSI 8 on light, so the
        # secondary text is a grey the palette owns rather than a dimmed body.
        for mode, expected in (("dark", "dim"), ("light", "ansi_bright_black")):
            app = self.make_app(mode)
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                # The Welcome fact labels are secondary text.
                text = app.screen.query_one("#facts").render()
                styles = {str(span.style) for span in text.spans}
                self.assertIn(expected, styles)
