"""The command menu: what it offers, what it disables, and what it runs."""

from __future__ import annotations

import asyncio
import importlib.util
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
    from textual.widgets import OptionList

    from installer import VERSION, manage
    from installer.core.events import Event
    from installer.detect import OsInfo, Probe, System
    from installer.paths import Paths
    from installer.plan import Options
    from installer.strings import Strings
    from installer.ui.app import KosApp
    from installer.ui.screens.confirm import ConfirmScreen
    from installer.ui.screens.installation import InstallationScreen
    from installer.ui.screens.logs import LogViewerScreen
    from installer.ui.screens.management import ManagementScreen
    from installer.ui.screens.options import OptionsScreen
    from installer.ui.screens.result import ResultScreen
    from installer.ui.screens.review import ReviewScreen
    from installer.ui.screens.system import SystemScreen
    from installer.ui.screens.units import UnitsScreen
    from installer.ui.theme import resolve_mode
    from installer.ui.widgets.about import AboutScreen
    from installer.ui.widgets.commands import CommandMenu
    from installer.ui.widgets.help import HelpScreen
    from installer.ui.widgets.local_path import LocalPathDialog


def fake_system() -> "System":
    return System(
        os=OsInfo(id="cachyos", version="", like=("arch",), pretty="CachyOS"),
        family="arch", method="kosctl", arch="x86_64",
        probes=[Probe("probe_os", "PASS", "CachyOS")])


def fake_source() -> "PreparedSource":
    from installer.source.models import PreparedSource

    return PreparedSource(mode="stable", repository="https://example.invalid/r.git",
                          ref="v1.0", commit="a" * 40,
                          path=Path("/tmp/nextkde-fake"), dirty=False, managed=True)


def fake_prepare(mode, opts, paths):
    from installer import workflow

    return workflow.Preparation(paths, prepared=fake_source())


def fake_identity(mode, opts, paths):
    return fake_source()


class FakeSession:
    def __init__(self, steps, log_path, root, mode: str = "ok") -> None:
        self.steps, self.log_path, self.root = list(steps), log_path, root
        self.mode = mode
        self.result, self.exit_code, self.failed_index = "", 0, None
        self.tail: list[tuple[str, str]] = []

    def run(self, emit, cancel) -> int:
        if self.mode == "cancel":
            emit(Event("stage", text="working", key="fake", index=1, total=1))
            cancel.wait(60)
            self.result, self.exit_code = "cancelled", 130
            return 130
        self.result = "ok"
        return 0


UNITS = [manage.Unit("core", "1.0", "dirs", 4, "2026-01-01T00:00:00"),
         manage.Unit("apps", "1.0", "files", 2, "")]
SNAPSHOTS = [manage.Snapshot("s1", "2026-01-01T00:00:00", "before", "config")]


def foot(app) -> str:
    return str(app.screen.query_one("#footer").render())


@unittest.skipUnless(HAS_TEXTUAL, "textual is not vendored (run tools/vendor.py)")
class CommandMenuTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        patcher = mock.patch("installer.workflow.identity", side_effect=fake_identity)
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_app(self, **kwargs) -> "KosApp":
        return KosApp(lang="en", system=fake_system(),
                      paths=Paths.resolve(source_root=ROOT),
                      prepare=fake_prepare, **kwargs)

    async def wait_for(self, pilot, predicate) -> None:
        for _ in range(300):
            await asyncio.sleep(0.01)
            await pilot.pause()
            if predicate():
                return
        self.fail("condition was never met")

    async def open_menu(self, pilot, app) -> None:
        await pilot.press("ctrl+p")
        await self.wait_for(pilot, lambda: isinstance(app.screen, CommandMenu))

    def options(self, app) -> list:
        return list(app.screen.query_one("#command_list", OptionList).options)

    def labels(self, app) -> list[str]:
        return [option.prompt.plain for option in self.options(app)]

    def row(self, app, needle: str):
        return next(option for option in self.options(app)
                    if needle in option.prompt.plain)

    async def choose(self, pilot, app, needle: str) -> None:
        listing = app.screen.query_one("#command_list", OptionList)
        for index, option in enumerate(listing.options):
            if needle in option.prompt.plain:
                self.assertFalse(option.disabled, option.prompt.plain)
                listing.highlighted = index
                await pilot.press("enter")
                await pilot.pause()
                return
        self.fail(f"{needle!r} is not in {self.labels(app)}")

    async def open_management(self, pilot, app) -> None:
        await self.open_menu(pilot, app)
        await self.choose(pilot, app, "Manage")
        await self.wait_for(pilot, lambda: isinstance(app.screen, ManagementScreen)
                            and app.screen.query_one("#manage_list",
                                                     OptionList).option_count == 6)

    # -- where it opens ---------------------------------------------------
    async def test_the_menu_opens_on_every_non_run_page(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            for expected in (None, SystemScreen, OptionsScreen, ReviewScreen):
                if expected is not None:
                    self.assertIsInstance(app.screen, expected)
                await self.open_menu(pilot, app)
                await pilot.press("escape")
                await pilot.pause()
                self.assertNotIsInstance(app.screen, CommandMenu)
                await pilot.press("tab")
                await pilot.pause()
            # Result
            app.push_screen(ResultScreen(Strings("en"), "ok"))
            await pilot.pause()
            await self.open_menu(pilot, app)
            await pilot.press("escape")
            await pilot.pause()
            # Management
            await self.open_management(pilot, app)
            await self.open_menu(pilot, app)
            self.assertIsInstance(app.screen, CommandMenu)

    async def test_a_run_page_and_the_confirm_page_have_no_menu(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            app.push_screen(InstallationScreen(Strings("en"), (),
                                               app.paths.log_dir / "x.log"))
            await pilot.pause()
            await pilot.press("ctrl+p")
            await pilot.pause()
            self.assertIsInstance(app.screen, InstallationScreen)
            app.pop_screen()
            await pilot.pause()
            for _ in range(3):
                await pilot.press("tab")
                await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            self.assertIsInstance(app.screen, ConfirmScreen)
            await pilot.press("ctrl+p")
            await pilot.pause()
            self.assertIsInstance(app.screen, ConfirmScreen)

    # -- context rows -----------------------------------------------------
    async def test_checks_offers_a_recheck_with_its_shortcut(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("tab")
            await pilot.pause()
            await self.open_menu(pilot, app)
            self.assertIn("Re-check  ctrl+r", " ".join(self.labels(app)))

    async def test_the_local_path_row_follows_the_chosen_source(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("tab")
            await pilot.press("tab")
            await pilot.pause()
            await self.open_menu(pilot, app)
            row = self.row(app, "Local checkout path")
            self.assertTrue(row.disabled)
            self.assertIn("local checkout only", row.prompt.plain)
            await pilot.press("escape")
            await pilot.pause()

            await pilot.press("down")          # main
            await pilot.press("down")          # local
            await pilot.pause()
            await self.open_menu(pilot, app)
            row = self.row(app, "Local checkout path")
            self.assertFalse(row.disabled)
            self.assertIn("ctrl+e", row.prompt.plain)
            await self.choose(pilot, app, "Local checkout path")
            await self.wait_for(pilot, lambda: isinstance(app.screen, LocalPathDialog))
            await pilot.press("escape")
            await pilot.pause()

    async def test_review_rows_follow_the_preparation_failure(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            for _ in range(3):
                await pilot.press("tab")
                await pilot.pause()
            self.assertIsInstance(app.screen, ReviewScreen)
            await self.open_menu(pilot, app)
            log = self.row(app, "Current log")
            details = self.row(app, "Plan / command details")
            self.assertTrue(log.disabled)
            self.assertIn("no log yet", log.prompt.plain)
            self.assertFalse(details.disabled)
            await pilot.press("escape")
            await pilot.pause()

            app.prepare_error = "boom"
            app.screen.reload()
            await pilot.pause()
            await self.open_menu(pilot, app)
            log = self.row(app, "Current log")
            details = self.row(app, "Plan / command details")
            self.assertFalse(log.disabled)
            self.assertTrue(details.disabled)
            self.assertIn("plan unavailable", details.prompt.plain)

    async def test_result_log_row_needs_a_log_path(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            app.push_screen(ResultScreen(Strings("en"), "ok"))
            await pilot.pause()
            await self.open_menu(pilot, app)
            self.assertTrue(self.row(app, "Current log").disabled)
            await pilot.press("escape")
            await pilot.pause()
            app.pop_screen()
            await pilot.pause()

            app.push_screen(ResultScreen(Strings("en"), "ok",
                                         log_path=app.paths.log_dir / "one.log"))
            await pilot.pause()
            await self.open_menu(pilot, app)
            self.assertFalse(self.row(app, "Current log").disabled)

    async def test_management_row_is_the_current_page_there(self) -> None:
        app = self.make_app()
        with mock.patch("installer.manage.units", return_value=UNITS), \
                mock.patch("installer.manage.snapshots", return_value=SNAPSHOTS), \
                mock.patch("installer.manage.logs", return_value=[]):
            async with app.run_test(size=(100, 30)) as pilot:
                await self.open_menu(pilot, app)
                self.assertFalse(self.row(app, "Manage").disabled)
                await pilot.press("escape")
                await pilot.pause()
                await self.open_management(pilot, app)
                await self.open_menu(pilot, app)
                row = self.row(app, "Manage")
                self.assertTrue(row.disabled)
                self.assertIn("current page", row.prompt.plain)

    # -- keys -------------------------------------------------------------
    async def test_arrows_vim_and_escape(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await self.open_menu(pilot, app)
            listing = app.screen.query_one("#command_list", OptionList)
            self.assertEqual(listing.highlighted, 0)   # Manage
            await pilot.press("down")
            self.assertEqual(listing.highlighted, 1)
            await pilot.press("j")
            self.assertEqual(listing.highlighted, 2)
            await pilot.press("k")
            self.assertEqual(listing.highlighted, 1)
            await pilot.press("up")
            self.assertEqual(listing.highlighted, 0)
            await pilot.press("escape")
            await pilot.pause()
            self.assertNotIsInstance(app.screen, CommandMenu)

    async def test_disabled_rows_are_skipped_by_the_cursor(self) -> None:
        app = self.make_app()
        with mock.patch("installer.manage.units", return_value=UNITS), \
                mock.patch("installer.manage.snapshots", return_value=SNAPSHOTS), \
                mock.patch("installer.manage.logs", return_value=[]):
            async with app.run_test(size=(100, 30)) as pilot:
                await self.open_management(pilot, app)
                await self.open_menu(pilot, app)
                listing = app.screen.query_one("#command_list", OptionList)
                self.assertEqual(listing.highlighted, 1)   # Manage is disabled
                await pilot.press("up")                    # wraps, never lands on 0
                self.assertNotEqual(listing.highlighted, 0)
                self.assertFalse(listing.options[listing.highlighted].disabled)

    # -- running them -----------------------------------------------------
    async def test_management_opens_its_screen(self) -> None:
        app = self.make_app()
        with mock.patch("installer.manage.units", return_value=UNITS), \
                mock.patch("installer.manage.snapshots", return_value=SNAPSHOTS), \
                mock.patch("installer.manage.logs", return_value=[]):
            async with app.run_test(size=(100, 30)) as pilot:
                await self.open_management(pilot, app)
                self.assertIsInstance(app.screen, ManagementScreen)

    async def test_the_current_log_opens_the_viewer(self) -> None:
        app = self.make_app()
        log = app.paths.log_dir / "one.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("hello\n", encoding="utf-8")
        async with app.run_test(size=(100, 30)) as pilot:
            app.push_screen(ResultScreen(Strings("en"), "failed", exit_code=1,
                                         log_path=log))
            await pilot.pause()
            await self.open_menu(pilot, app)
            await self.choose(pilot, app, "Current log")
            await self.wait_for(pilot, lambda: isinstance(app.screen, LogViewerScreen))
            self.assertEqual(app.screen.path, log)

    async def test_recheck_runs_the_screens_own_refresh(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("tab")
            await pilot.pause()
            await self.open_menu(pilot, app)
            with mock.patch("installer.ui.screens.system.detect",
                            return_value=fake_system()) as detect:
                await self.choose(pilot, app, "Re-check")
                await self.wait_for(pilot, lambda: detect.called)
                self.assertIsInstance(app.screen, SystemScreen)

    async def test_details_toggles_the_plan(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            for _ in range(3):
                await pilot.press("tab")
                await pilot.pause()
            await self.open_menu(pilot, app)
            await self.choose(pilot, app, "Plan / command details")
            self.assertTrue(app.screen.details)
            await self.open_menu(pilot, app)
            await self.choose(pilot, app, "Plan / command details")
            self.assertFalse(app.screen.details)

    async def test_theme_switches_and_marks_the_choice(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await self.open_menu(pilot, app)
            await self.choose(pilot, app, "Theme: light")
            await self.wait_for(pilot, lambda: app.theme_mode == "light")
            self.assertFalse(app.dark)
            self.assertEqual(app.secondary_style, "bright_black")

            await self.open_menu(pilot, app)
            self.assertIn("(•) Theme: light", self.labels(app))
            await self.choose(pilot, app, "Theme: dark")
            await self.wait_for(pilot, lambda: app.theme_mode == "dark")
            self.assertTrue(app.dark)
            self.assertEqual(app.secondary_style, "dim")

            await self.open_menu(pilot, app)
            await self.choose(pilot, app, "Theme: system")
            await self.wait_for(pilot, lambda: app.theme_mode == "system")
            self.assertEqual(app.dark, resolve_mode("system") == "dark")

    async def test_language_switches_and_closes_the_menu(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await self.open_menu(pilot, app)
            await self.choose(pilot, app, "Language: 中文")
            await self.wait_for(pilot, lambda: app.lang == "zh")
            self.assertNotIsInstance(app.screen, CommandMenu)
            self.assertIn("ctrl+p 命令", foot(app))
            self.assertEqual(app.strings("cmd_title"), "命令")

    async def test_help_and_about_open(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await self.open_menu(pilot, app)
            await self.choose(pilot, app, "Help")
            await self.wait_for(pilot, lambda: isinstance(app.screen, HelpScreen))
            await pilot.press("x")
            await pilot.pause()
            self.assertNotIsInstance(app.screen, HelpScreen)

            await self.open_menu(pilot, app)
            await self.choose(pilot, app, "About")
            await self.wait_for(pilot, lambda: isinstance(app.screen, AboutScreen))
            body = str(app.screen.query_one("#about_body").render())
            self.assertIn(VERSION, body)
            self.assertIn(str(app.paths.installer_root), body)
            self.assertIn(str(app.paths.source_root), body)

    async def test_quit_is_a_command(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await self.open_menu(pilot, app)
            await self.choose(pilot, app, "Quit")
            await self.wait_for(pilot, lambda: bool(app._exit))

    async def test_no_menu_while_a_management_action_runs(self) -> None:
        sessions = []

        def factory(steps, log_path, root):
            session = FakeSession(steps, log_path, root, "cancel")
            sessions.append(session)
            return session

        app = KosApp(lang="en", system=fake_system(),
                     paths=Paths.resolve(source_root=ROOT),
                     prepare=fake_prepare, session_factory=factory)
        with mock.patch("installer.manage.units", return_value=UNITS), \
                mock.patch("installer.manage.snapshots", return_value=SNAPSHOTS), \
                mock.patch("installer.manage.logs", return_value=[]):
            async with app.run_test(size=(100, 30)) as pilot:
                await self.open_management(pilot, app)
                await pilot.press("1")
                await self.wait_for(pilot, lambda: isinstance(app.screen, UnitsScreen)
                                    and app.screen.query_one(
                                        "#manage_list", OptionList).option_count == 2)
                await pilot.press("down")
                await pilot.press("space")
                await self.wait_for(pilot, lambda: app.screen.busy)
                self.assertNotIn("ctrl+p", foot(app))
                await pilot.press("ctrl+p")
                await pilot.pause()
                self.assertNotIsInstance(app.screen, CommandMenu)
                await pilot.press("ctrl+z")
                await self.wait_for(pilot, lambda: not app.screen.busy)

    # -- narrow terminal --------------------------------------------------
    async def test_66_columns_keeps_the_menu_and_help_lists_it(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(66, 20)) as pilot:
            await pilot.pause()
            self.assertIn("ctrl+p commands", foot(app))
            await self.open_menu(pilot, app)
            self.assertLessEqual(app.screen.query_one("#command_box").size.width, 66)
            labels = self.labels(app)
            for name in ("Manage", "Theme: system", "Language: English",
                         "Help", "About", "Quit"):
                self.assertTrue(any(name in label for label in labels), name)
            await pilot.press("escape")
            await pilot.pause()

            await pilot.press("tab")          # Checks: the hint is dropped
            await pilot.pause()
            self.assertNotIn("ctrl+p", foot(app))
            await pilot.press("ctrl+k")
            await pilot.pause()
            self.assertIsInstance(app.screen, HelpScreen)
            self.assertIn(("ctrl+p", Strings("en")("key_commands")),
                          [tuple(row) for row in app.screen.rows])
