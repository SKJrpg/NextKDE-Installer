"""Options -> local checkout: detection, the path prompt and the Review plan.

Offline: the checkouts are small temporary git repositories, so nothing here
talks to GitHub or looks at the developer's own home.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
_VENDOR = ROOT / "vendor"
if _VENDOR.is_dir():
    sys.path.insert(0, str(_VENDOR))
HAS_TEXTUAL = importlib.util.find_spec("textual") is not None

if HAS_TEXTUAL:
    from textual.widgets import Input

    from installer.detect import OsInfo, Probe, System
    from installer.paths import Paths
    from installer.plan import Options
    from installer.strings import Strings
    from installer.ui.app import KosApp
    from installer.ui.screens.options import OptionsScreen
    from installer.ui.screens.review import ReviewScreen
    from installer.ui.widgets.help import HelpScreen
    from installer.ui.widgets.local_path import LocalPathDialog


IDENTITY = ("-c", "user.name=test", "-c", "user.email=test@example.com")


def git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=None if cwd is None else str(cwd),
                          capture_output=True, text=True, check=True)


def make_checkout(path: Path, *, kosctl: bool = True) -> Path:
    """A tiny NextKDE-looking checkout; returns its commit."""
    git("init", "-q", "-b", "main", str(path))
    (path / "README.md").write_text("NextKDE\n", encoding="utf-8")
    if kosctl:
        (path / "tools").mkdir()
        (path / "tools" / "kosctl").write_text("#!/bin/sh\n", encoding="utf-8")
    git("add", "-A", cwd=path)
    git(*IDENTITY, "commit", "-q", "-m", "first", cwd=path)
    return path


def fake_system() -> "System":
    return System(
        os=OsInfo(id="cachyos", version="", like=("arch",), pretty="CachyOS"),
        family="arch", method="kosctl", arch="x86_64",
        probes=[Probe("probe_os", "PASS", "CachyOS")])


def foot(app) -> str:
    return str(app.screen.query_one("#footer").render())


@unittest.skipUnless(HAS_TEXTUAL, "textual is not vendored (run tools/vendor.py)")
class LocalSourceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        # ~ is the dialog's business: give it a home of its own.
        self.home = self.base / "home"
        self.home.mkdir()
        home = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        home.start()
        self.addCleanup(home.stop)
        self.empty = self.base / "empty"
        self.empty.mkdir()

    def make_paths(self, root: Path | None = None, *, explicit: bool = True) -> "Paths":
        return Paths(installer_root=ROOT, source_root=root or self.empty,
                     build_root=self.base / "build",
                     state_root=self.base / "state",
                     data_home=self.base / "data",
                     source_root_explicit=explicit)

    def make_app(self, paths=None, **kwargs) -> "KosApp":
        return KosApp(lang="en", system=fake_system(),
                      paths=paths or self.make_paths(), **kwargs)

    async def to_options(self, pilot) -> None:
        await pilot.press("tab")      # Welcome -> Checks
        await pilot.pause()
        await pilot.press("tab")      # Checks -> Options
        await pilot.pause()

    async def settle(self, pilot, predicate) -> None:
        for _ in range(300):
            await asyncio.sleep(0.01)
            if predicate():
                return
        self.fail("the worker never finished")

    async def detected(self, pilot, app) -> None:
        await self.settle(pilot, lambda: not app.screen._detecting)

    async def to_local(self, pilot) -> None:
        await pilot.press("down")     # main -> local; stable is sealed
        await pilot.pause()

    # -- detection -------------------------------------------------------
    async def test_the_explicit_root_is_detected_and_shown(self) -> None:
        work = make_checkout(self.base / "chosen")
        commit = git("rev-parse", "HEAD", cwd=work).stdout.strip()
        app = self.make_app(self.make_paths(work))
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_options(pilot)
            await self.detected(pilot, app)
            self.assertEqual(app.opts.local_path, work.resolve())

            await self.to_local(pilot)
            self.assertIn(str(work), str(app.screen.query_one("#local_state").render()))
            detail = str(app.screen.query_one("#option_detail_text").render())
            self.assertIn(f"main @ {commit[:8]}", detail)
            self.assertIn(Strings("en")("review_clean"), detail)
            self.assertIn("ctrl+e path", foot(app))

    async def test_a_dirty_checkout_says_so(self) -> None:
        work = make_checkout(self.base / "chosen")
        (work / "README.md").write_text("changed\n", encoding="utf-8")
        app = self.make_app(self.make_paths(work))
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_options(pilot)
            await self.detected(pilot, app)
            await self.to_local(pilot)
            detail = str(app.screen.query_one("#option_detail_text").render())
            self.assertIn(Strings("en")("review_dirty"), detail)

    async def test_nothing_found_leaves_the_path_empty(self) -> None:
        with mock.patch("installer.source.manager.detect_local",
                        return_value=(None, [])):
            app = self.make_app()
            async with app.run_test(size=(100, 30)) as pilot:
                await self.to_options(pilot)
                await self.detected(pilot, app)
                await self.to_local(pilot)
                self.assertIsNone(app.opts.local_path)
                self.assertEqual(
                    str(app.screen.query_one("#local_state").render()),
                    Strings("en")("local_not_found"))
                self.assertIn(Strings("en")("local_not_found"),
                              str(app.screen.query_one("#option_detail_text").render()))
                # The prompt is the way out of this state.
                await pilot.press("ctrl+e")
                await pilot.pause()
                self.assertIsInstance(app.screen, LocalPathDialog)

    async def test_ctrl_e_is_only_offered_for_a_local_source(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_options(pilot)
            await self.detected(pilot, app)
            self.assertNotIn("ctrl+e", foot(app))
            await pilot.press("ctrl+e")
            await pilot.pause()
            self.assertIsInstance(app.screen, OptionsScreen)   # inert for stable

    # -- the path prompt -------------------------------------------------
    async def test_the_prompt_rejects_then_accepts_a_typed_path(self) -> None:
        home_checkout = make_checkout(self.home / "Projects" / "NextKde")
        plain = self.base / "plain"
        (plain / "tools").mkdir(parents=True)
        (plain / "tools" / "kosctl").write_text("", encoding="utf-8")
        with mock.patch("installer.source.manager.detect_local",
                        return_value=(None, [])):
            app = self.make_app()
            async with app.run_test(size=(100, 30)) as pilot:
                await self.to_options(pilot)
                await self.detected(pilot, app)
                await self.to_local(pilot)
                await pilot.press("ctrl+e")
                await pilot.pause()
                self.assertIsInstance(app.screen, LocalPathDialog)

                field = app.screen.query_one("#path_input", Input)
                field.value = str(plain)
                await pilot.press("enter")
                await self.settle(pilot, lambda: not app.screen._checking)
                self.assertIsInstance(app.screen, LocalPathDialog)  # kept open
                self.assertTrue(str(app.screen.query_one("#path_error").render()))

                field.value = "  "
                await pilot.press("enter")
                await pilot.pause()
                self.assertEqual(str(app.screen.query_one("#path_error").render()),
                                 Strings("en")("local_path_empty"))

                field.value = "~/Projects/NextKde"
                await pilot.press("enter")
                await self.settle(pilot, lambda: isinstance(app.screen, OptionsScreen))
                self.assertEqual(app.opts.local_path, home_checkout.resolve())
                self.assertIn("~/Projects/NextKde",
                              str(app.screen.query_one("#local_state").render()))

                # Esc leaves the accepted path alone.
                await pilot.press("ctrl+e")
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()
                self.assertIsInstance(app.screen, OptionsScreen)
                self.assertEqual(app.opts.local_path, home_checkout.resolve())

    # -- what Review then uses ------------------------------------------
    async def test_the_chosen_path_reaches_review_and_its_plan(self) -> None:
        work = make_checkout(self.base / "chosen")
        commit = git("rev-parse", "HEAD", cwd=work).stdout.strip()
        app = self.make_app(opts=Options(source="local", local_path=work))
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_options(pilot)
            await pilot.press("tab")      # Options -> Review
            await pilot.pause()
            self.assertIsInstance(app.screen, ReviewScreen)
            await self.settle(pilot, lambda: app.screen._resolved)
            self.assertEqual(app.screen._source.path, work.resolve())
            self.assertEqual(app.screen._source.commit, commit)
            self.assertIn(str(work), str(app.screen.query_one("#steps").render()))
            steps = app.screen._plan_steps()
            self.assertTrue(steps)
            self.assertTrue(steps[0].argv)
            self.assertTrue(steps[0].argv[0].startswith(str(work)),
                            steps[0].argv[0])

    # -- narrow terminal -------------------------------------------------
    async def test_66_columns_drops_the_hint_but_help_keeps_it(self) -> None:
        work = make_checkout(self.base / "chosen")
        app = self.make_app(self.make_paths(work))
        async with app.run_test(size=(66, 20)) as pilot:
            await self.to_options(pilot)
            await self.detected(pilot, app)
            await self.to_local(pilot)
            self.assertEqual(foot(app), "⏎ options below  Tab next  "
                                        "Shift+Tab back  ctrl+k help")
            await pilot.press("ctrl+k")
            await pilot.pause()
            self.assertIsInstance(app.screen, HelpScreen)
            self.assertIn(("ctrl+e", Strings("en")("key_path")),
                          [tuple(row) for row in app.screen.rows])
