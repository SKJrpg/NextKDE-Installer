"""Stage T3: the management area, offline.

``manage`` is faked and the session is a stub that records the argv it was
handed, so nothing here shells out to kosctl. Skipped when textual is not
vendored.
"""

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
    from textual.app import App
    from textual.widgets import Button, Input, OptionList, RichLog

    from installer import manage
    from installer.core.events import Event
    from installer.detect import OsInfo, Probe, System
    from installer.paths import Paths
    from installer.strings import Strings
    from installer.ui.app import KosApp
    from installer.ui.screens.logs import LogViewerScreen, LogsScreen
    from installer.ui.screens.management import ManagementScreen
    from installer.ui.screens.snapshots import SnapshotsScreen
    from installer.ui.screens.units import UnitsScreen
    from installer.ui.widgets.confirm import ConfirmDialog


def fake_system() -> "System":
    return System(
        os=OsInfo(id="cachyos", version="", like=("arch",), pretty="CachyOS"),
        family="arch", method="kosctl", arch="x86_64",
        probes=[Probe("probe_os", "PASS", "CachyOS")])


UNITS = [manage.Unit("core", "1.0", "dirs", 4, "2026-01-01T00:00:00"),
         manage.Unit("apps", "1.0", "files", 2, "")]
SNAPSHOTS = [manage.Snapshot("s1", "2026-01-01T00:00:00", "before", "config")]


class FakeSession:
    """Records what it was asked to run; emits the same events an install does."""

    def __init__(self, steps, log_path, root, mode: str = "ok") -> None:
        self.steps = list(steps)
        self.ran = [list(step.argv) for step in steps]
        self.log_path, self.root = log_path, root
        self.mode = mode
        self.result = ""
        self.exit_code = 0
        self.failed_index = None
        self.tail: list[tuple[str, str]] = []

    def run(self, emit, cancel) -> int:
        if self.mode == "cancel":
            emit(Event("stage", text="working", key="fake", index=1, total=1))
            emit(Event("log", text="waiting for cancel", level="INFO"))
            cancel.wait(60)
            self.result, self.exit_code = "cancelled", 130
            emit(Event("cancelled", index=1, total=1))
            return 130
        if self.mode == "fail":
            emit(Event("stage", text="working", key="fake", index=1, total=1))
            emit(Event("log", text="boom: kosctl refused", level="ERROR"))
            self.result, self.exit_code, self.failed_index = "failed", 1, 1
            self.tail = [("ERROR", "boom: kosctl refused")]
            emit(Event("failed", text="boom: kosctl refused", index=1, total=1))
            return 1
        for index, step in enumerate(self.steps, 1):
            emit(Event("stage", text=step.title, key=step.key, index=index,
                       total=len(self.steps)))
            emit(Event("log", text="ran " + " ".join(step.argv), level="OK"))
        self.result = "ok"
        emit(Event("done", index=len(self.steps), total=len(self.steps)))
        return 0


@unittest.skipUnless(HAS_TEXTUAL, "textual is not vendored (run tools/vendor.py)")
class ManageTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.mode = "ok"
        for name, value in (("units", lambda root: list(UNITS)),
                            ("snapshots", lambda root: list(SNAPSHOTS)),
                            ("logs", lambda log_dir: [])):
            patcher = mock.patch(f"installer.manage.{name}", side_effect=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.sessions: list[FakeSession] = []

    def make_app(self) -> "KosApp":
        def factory(steps, log_path, root):
            session = FakeSession(steps, log_path, root, self.mode)
            self.sessions.append(session)
            return session
        return KosApp(lang="en", system=fake_system(),
                      paths=Paths.resolve(source_root=ROOT),
                      prepare=lambda mode, opts, paths: None,
                      session_factory=factory)

    async def wait_for(self, pilot, predicate) -> None:
        for _ in range(300):
            await asyncio.sleep(0.01)
            await pilot.pause()
            if predicate():
                return
        self.fail("condition was never met")

    async def open_manage(self, pilot, app) -> None:
        """Open management directly; Ctrl+P is Textual's palette now."""
        app.screen._open_management()
        await self.wait_for(
            pilot, lambda: isinstance(app.screen, ManagementScreen)
            and app.screen.query_one("#manage_list", OptionList).option_count == 6)

    def rows(self, app, screen=None) -> list[str]:
        list_ = (screen or app.screen).query_one("#manage_list", OptionList)
        return [str(option.prompt) for option in list_.options]

    async def test_management_is_a_numbered_menu_with_counts(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.open_manage(pilot, app)
            rows = self.rows(app)
            self.assertEqual(len(rows), 6)
            self.assertTrue(rows[0].startswith("[1] "), rows[0])
            self.assertIn("Units", rows[0])
            self.assertIn(str(len(UNITS)), rows[0])
            self.assertTrue(rows[1].startswith("[2] "), rows[1])
            self.assertIn("Snapshots", rows[1])
            self.assertIn(str(len(SNAPSHOTS)), rows[1])
            self.assertIn("Doctor", rows[2])
            self.assertIn("Logs", rows[3])
            self.assertIn("Uninstall", rows[4])
            self.assertTrue(rows[5].startswith("[6] "), rows[5])
            self.assertIn("Back", rows[5])

            await pilot.press("escape")
            await pilot.pause()
            self.assertNotIsInstance(app.screen, ManagementScreen)

    async def test_space_toggles_through_the_session(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.open_manage(pilot, app)
            await pilot.press("enter")            # Units
            await self.wait_for(
                pilot, lambda: isinstance(app.screen, UnitsScreen)
                and app.screen.query_one("#manage_list", OptionList).option_count == 2)
            await pilot.press("down")             # apps: not installed
            await pilot.press("space")
            await self.wait_for(pilot, lambda: bool(self.sessions))
            self.assertEqual(self.sessions[0].ran,
                             [[str(app.paths.source_root / "tools" / "kosctl"),
                               "on", "apps"]])
            # A successful toggle reloads the list it changed.
            await self.wait_for(
                pilot, lambda: len(self.sessions) == 1
                and not app.screen.busy)

    async def test_core_cannot_be_switched_off(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.open_manage(pilot, app)
            await pilot.press("enter")
            await self.wait_for(
                pilot, lambda: isinstance(app.screen, UnitsScreen)
                and app.screen.query_one("#manage_list", OptionList).option_count == 2)
            await pilot.press("home")
            await pilot.press("space")
            await pilot.pause()
            self.assertEqual(self.sessions, [])   # the backend was never called
            status = str(app.screen.query_one("#action_status").render())
            self.assertIn("cannot be switched off", status)

    async def test_snapshots_need_confirmation_before_rollback(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.open_manage(pilot, app)
            await pilot.press("down")             # Snapshots
            await pilot.press("enter")
            await self.wait_for(
                pilot, lambda: isinstance(app.screen, SnapshotsScreen)
                and app.screen.query_one("#manage_list", OptionList).option_count == 1)
            await pilot.press("enter")
            await pilot.pause()
            self.assertIsInstance(app.screen, ConfirmDialog)
            self.assertEqual(self.sessions, [])   # nothing ran without a yes

            await pilot.click("#confirm_ok")
            await self.wait_for(pilot, lambda: bool(self.sessions))
            self.assertEqual(self.sessions[0].ran,
                             [[str(app.paths.source_root / "tools" / "kosctl"),
                               "rollback", "s1"]])

    async def test_uninstall_needs_the_typed_word(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.open_manage(pilot, app)
            await pilot.press("5")                # Uninstall
            await pilot.pause()
            await pilot.pause()
            self.assertIsInstance(app.screen, ConfirmDialog)
            self.assertTrue(app.screen.query_one("#confirm_ok", Button).disabled)
            await pilot.press("enter")            # no word, no action
            await pilot.pause()
            self.assertEqual(self.sessions, [])
            self.assertIsInstance(app.screen, ConfirmDialog)

            app.screen.query_one("#confirm_word", Input).value = "uninstall"
            await pilot.pause()
            self.assertFalse(app.screen.query_one("#confirm_ok", Button).disabled)
            await pilot.click("#confirm_ok")
            await self.wait_for(pilot, lambda: bool(self.sessions))
            self.assertEqual(self.sessions[0].ran,
                             [[str(app.paths.source_root / "tools" / "kosctl"),
                               "uninstall"]])

    async def test_a_failed_action_keeps_the_row_and_shows_the_tail(self) -> None:
        self.mode = "fail"
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.open_manage(pilot, app)
            await pilot.press("enter")            # Units
            await self.wait_for(
                pilot, lambda: isinstance(app.screen, UnitsScreen)
                and app.screen.query_one("#manage_list", OptionList).option_count == 2)
            await pilot.press("down")
            await pilot.press("space")
            await self.wait_for(pilot, lambda: bool(self.sessions))
            await self.wait_for(pilot, lambda: not app.screen.busy)
            status = str(app.screen.query_one("#action_status").render())
            self.assertIn("failed", status.lower())
            self.assertEqual(app.screen.query_one("#manage_list", OptionList).option_count,
                             2)                # the row is still there
            log = "\n".join(strip.text for strip in
                            app.screen.query_one("#action_log", RichLog).lines)
            self.assertIn("boom: kosctl refused", log)

    async def test_ctrl_z_cancels_a_running_action(self) -> None:
        self.mode = "cancel"
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.open_manage(pilot, app)
            await pilot.press("enter")
            await self.wait_for(
                pilot, lambda: isinstance(app.screen, UnitsScreen)
                and app.screen.query_one("#manage_list", OptionList).option_count == 2)
            await pilot.press("down")
            await pilot.press("space")
            await self.wait_for(pilot, lambda: bool(self.sessions))
            self.assertTrue(app.screen.busy)
            await pilot.press("ctrl+c")       # swallowed: no quit, no abort
            await pilot.pause()
            self.assertFalse(app._exit)
            self.assertTrue(app.screen.busy)

            await pilot.press("ctrl+z")       # no question: it just stops
            await self.wait_for(pilot, lambda: not app.screen.busy)
            status = str(app.screen.query_one("#action_status").render())
            self.assertIn("cancelled", status.lower())
            self.assertEqual(self.sessions[0].result, "cancelled")

    async def test_logs_open_a_viewer_with_the_file_content(self) -> None:
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: [p.unlink(missing_ok=True) for p in directory.iterdir()]
                        and directory.rmdir())
        log = directory / "install-20260101-000000.log"
        log.write_text("hello log line\nsecond line\n", encoding="utf-8")
        with mock.patch("installer.manage.logs", side_effect=lambda log_dir: [log]):
            app = self.make_app()
            async with app.run_test(size=(100, 30)) as pilot:
                await self.open_manage(pilot, app)
                await pilot.press("down")
                await pilot.press("down")
                await pilot.press("down")     # Logs
                await pilot.press("enter")
                await self.wait_for(pilot, lambda: isinstance(app.screen, LogsScreen)
                                    and app.screen.query_one(
                                        "#manage_list", OptionList).option_count == 1)
                await pilot.press("enter")
                await self.wait_for(
                    pilot, lambda: isinstance(app.screen, LogViewerScreen)
                    and bool(app.screen.query_one("#log_view", RichLog).lines))
                text = "\n".join(strip.text for strip in
                                 app.screen.query_one("#log_view", RichLog).lines)
                self.assertIn("hello log line", text)

                await pilot.press("escape")
                await pilot.pause()
                self.assertIsInstance(app.screen, LogsScreen)


@unittest.skipUnless(HAS_TEXTUAL, "textual is not vendored (run tools/vendor.py)")
class ConfirmDialogTest(unittest.IsolatedAsyncioTestCase):
    async def test_uninstall_word_is_required(self) -> None:
        app = App()
        async with app.run_test(size=(80, 24)) as pilot:
            app.push_screen(ConfirmDialog(Strings("en"), "Uninstall", "body text",
                                          word="uninstall"))
            await pilot.pause()
            dialog = app.screen
            self.assertIsInstance(dialog, ConfirmDialog)
            self.assertTrue(dialog.query_one("#confirm_ok", Button).disabled)
            await pilot.press("enter")
            await pilot.pause()
            self.assertIs(app.screen, dialog)     # still open, not confirmed

            dialog.query_one("#confirm_word", Input).value = "uninstall"
            await pilot.pause()
            self.assertFalse(dialog.query_one("#confirm_ok", Button).disabled)
            await pilot.press("enter")
            await pilot.pause()
            self.assertIsNot(app.screen, dialog)

    async def test_escape_cancels(self) -> None:
        app = App()
        results = []
        async with app.run_test(size=(80, 24)) as pilot:
            app.push_screen(ConfirmDialog(Strings("en"), "Uninstall", "body"),
                            callback=results.append)
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            self.assertEqual(results, [False])

    async def test_text_is_localized(self) -> None:
        app = App()
        async with app.run_test(size=(80, 24)) as pilot:
            app.push_screen(ConfirmDialog(Strings("zh"), "卸载", "确认吗"))
            await pilot.pause()
            label = app.screen.query_one("#confirm_ok", Button).label
            self.assertIn("确认", str(label))
