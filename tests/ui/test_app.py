"""Stage T1: the Textual shell boots, navigates, and survives a re-probe.

Skipped when textual is not on sys.path (a checkout without vendor/).
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# The vendored tree is how the app runs in production (install.sh prepends it);
# use the same path here so the suite exercises the UI once it is built.
_VENDOR = ROOT / "vendor"
if _VENDOR.is_dir():
    import sys

    sys.path.insert(0, str(_VENDOR))
HAS_TEXTUAL = importlib.util.find_spec("textual") is not None

if HAS_TEXTUAL:
    from textual.widgets import Checkbox
    from textual.widgets._footer import FooterKey

    from installer.detect import OsInfo, Probe, System
    from installer.paths import Paths
    from installer.strings import Strings
    from installer.ui.app import KosApp
    from installer.ui.screens.options import OptionsScreen
    from installer.ui.screens.system import SystemScreen
    from installer.ui.screens.welcome import WelcomeScreen


def footer_text(app) -> str:
    """What the footer currently says, as text."""
    return " ".join(key.description for key in app.screen.query(FooterKey))


def fake_system() -> "System":
    return System(
        os=OsInfo(id="cachyos", version="", like=("arch",), pretty="CachyOS"),
        family="arch",
        method="kosctl",
        arch="x86_64",
        probes=[Probe("probe_os", "PASS", "CachyOS"),
                Probe("probe_disk", "WARN", "4.2 GiB free",
                      "At least 6 GiB is needed for the build tree.")],
    )


@unittest.skipUnless(HAS_TEXTUAL, "textual is not vendored (run tools/vendor.py)")
class AppShellTest(unittest.IsolatedAsyncioTestCase):
    def make_app(self, lang: str = "en") -> "KosApp":
        return KosApp(lang=lang, system=fake_system(),
                      paths=Paths.resolve(source_root=ROOT))

    async def test_boots_to_welcome(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            self.assertIsInstance(app.screen, WelcomeScreen)
            self.assertIn("Welcome", str(app.screen.query_one("#sidebar").render()))
            self.assertIn("CachyOS", str(app.screen.query_one("#facts").render()))

    async def test_enter_opens_system(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("enter")
            await pilot.pause()
            self.assertIsInstance(app.screen, SystemScreen)
            self.assertIn("Checks", str(app.screen.query_one("#sidebar").render()))

    async def test_probe_rows_show_the_status_word(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("enter")
            await pilot.pause()
            rows = app.screen.query_one("#probes").children
            text = " ".join(str(row.render()) for row in rows)
            self.assertIn("PASS", text)
            self.assertIn("WARN", text)
            self.assertIn("Disk space", text)

    async def test_zh_status_words(self) -> None:
        app = self.make_app(lang="zh")
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("enter")
            await pilot.pause()
            text = " ".join(str(row.render()) for row in app.screen.query_one("#probes").children)
            self.assertIn("通过", text)
            self.assertIn("注意", text)

    async def test_f5_reprobes_without_crashing(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("f5")
            await pilot.pause()
            self.assertIsInstance(app.screen, SystemScreen)
            self.assertTrue(app.screen.query_one("#probes").children)

    async def test_escape_returns_to_welcome(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            self.assertIsInstance(app.screen, WelcomeScreen)

    async def test_language_switch_rewrites_the_page_and_the_footer(self) -> None:
        app = self.make_app(lang="zh")
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            self.assertIn("发行版", str(app.screen.query_one("#facts").render()))
            self.assertIn("进入", footer_text(app))

            await pilot.press("right")
            await pilot.pause()
            self.assertEqual(app.lang, "en")
            self.assertIn("Distribution", str(app.screen.query_one("#facts").render()))
            self.assertIn("open", footer_text(app))
            self.assertIn("Language", str(app.screen.query_one("#language").render()))

            await pilot.press("left")
            await pilot.pause()
            self.assertEqual(app.lang, "zh")
            self.assertIn("发行版", str(app.screen.query_one("#facts").render()))

    async def test_footer_offers_no_command_palette(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            self.assertFalse(app.ENABLE_COMMAND_PALETTE)
            self.assertNotIn("palette", footer_text(app).lower())

    async def test_probe_detail_follows_the_focused_row(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()
            detail = str(app.screen.query_one("#probe_detail_text").render())
            self.assertIn("Why it matters", detail)
            self.assertIn(Strings("en")("why_probe_disk"), detail)
            self.assertIn("4.2 GiB free", detail)
            self.assertIn("WARN", detail)

    async def test_probe_detail_is_reachable_on_a_small_terminal(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(66, 20)) as pilot:
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()
            self.assertEqual(app.screen.row, 1)
            # Below 110 columns the detail stacks under the list, scrollable.
            self.assertFalse(app.screen.query_one("#probe_detail").has_class("-wide"))
            detail = str(app.screen.query_one("#probe_detail_text").render())
            self.assertIn(Strings("en")("why_probe_disk"), detail)
            self.assertGreater(app.screen.query_one("#probe_detail").max_scroll_y, 0)

    async def test_wide_options_explain_the_source(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            self.assertIsInstance(app.screen, OptionsScreen)
            self.assertTrue(app.screen.query_one("#option_detail").has_class("-wide"))
            detail = str(app.screen.query_one("#option_detail_text").render())
            self.assertIn(Strings("en")("detail_source"), detail)

    async def test_wide_options_detail_follows_focus(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            def detail() -> str:
                return str(app.screen.query_one("#option_detail_text").render())

            app.screen.query_one("#spatial", Checkbox).focus()
            await pilot.pause()
            self.assertIn(Strings("en")("opt_spatial_hint"), detail())

            app.screen.query_one("#app_todo", Checkbox).focus()
            await pilot.pause()
            self.assertIn(Strings("en")("detail_apps"), detail())


class InstallShTest(unittest.TestCase):
    """install.sh only touches PYTHONPATH when vendor/ exists."""

    def run_installer(self, vendor: bool) -> tuple[Path, list[str]]:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        shutil.copy(ROOT / "install.sh", tmp / "install.sh")
        if vendor:
            (tmp / "vendor").mkdir()
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        shim = bin_dir / "python3"
        shim.write_text('#!/bin/sh\ncase "$1" in -c) exit 0;; esac\necho "$PYTHONPATH"\n')
        shim.chmod(0o755)
        env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        result = subprocess.run(["bash", str(tmp / "install.sh")], capture_output=True,
                                text=True, env=env, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return tmp, result.stdout.strip().split(":")

    def test_vendor_is_prepended_when_present(self) -> None:
        tmp, entries = self.run_installer(vendor=True)
        self.assertEqual(entries[0], str(tmp / "vendor"))
        self.assertEqual(entries[1], str(tmp))

    def test_pythonpath_is_unchanged_without_vendor(self) -> None:
        tmp, entries = self.run_installer(vendor=False)
        self.assertEqual(entries, [str(tmp)])
