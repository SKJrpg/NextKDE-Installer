"""The sudo prompt on demand: a blocked sudo call raises it, once at a time.

Offline: the helper is a real shell script in a temporary askpass tree, the
session is a stand-in, and nothing runs sudo.
"""

from __future__ import annotations

import asyncio
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
_VENDOR = ROOT / "vendor"
if _VENDOR.is_dir():
    sys.path.insert(0, str(_VENDOR))
HAS_TEXTUAL = importlib.util.find_spec("textual") is not None

if HAS_TEXTUAL:
    from textual.screen import ModalScreen
    from textual.widgets import Input, OptionList, RichLog

    from installer import manage, workflow
    from installer.core.events import Event
    from installer.detect import OsInfo, Probe, System
    from installer.paths import Paths
    from installer.plan import Step
    from installer.source.models import PreparedSource
    from installer.strings import Strings
    from installer.ui.app import KosApp
    from installer.ui.screens.installation import InstallationScreen
    from installer.ui.screens.management import ManagementScreen
    from installer.ui.screens.result import ResultScreen
    from installer.ui.screens.review import ReviewScreen
    from installer.ui.screens.units import UnitsScreen
    from installer.ui.widgets.help import HelpScreen

PASSWORD = "hunter2-s3cret"

UNITS = [manage.Unit("core", "1.0", "dirs", 4, "2026-01-01T00:00:00"),
         manage.Unit("apps", "1.0", "files", 2, "")]


def fake_system() -> "System":
    return System(
        os=OsInfo(id="cachyos", version="", like=("arch",), pretty="CachyOS"),
        family="arch",
        method="kosctl",
        arch="x86_64",
        probes=[Probe("probe_sudo", "WARN", "password required")],
    )


def fake_source(mode, opts, paths) -> "PreparedSource":
    return PreparedSource(mode=workflow.MODES["stable"],
                          repository="https://example.invalid/r.git",
                          ref="v1.0", commit="a" * 40, path=ROOT, dirty=False,
                          managed=True)


def fake_prepare(mode, opts, paths) -> "workflow.Preparation":
    return workflow.Preparation(paths, prepared=fake_source(mode, opts, paths))


class FakeSession:
    """Runs the plan without sudo: nothing ever asks for a password."""

    def __init__(self, steps, log_path, root) -> None:
        self.steps = list(steps)
        self.result = "ok"
        self.exit_code = 0
        self.failed_index = None
        self.tail: list[tuple[str, str]] = []

    def run(self, emit, cancel) -> int:
        for index, step in enumerate(self.steps, 1):
            emit(Event("stage", text=step.title, key=step.key, index=index,
                       total=len(self.steps)))
            emit(Event("log", text="ran " + step.key, level="OK", key=step.key,
                       index=index, total=len(self.steps)))
        emit(Event("done", index=len(self.steps), total=len(self.steps)))
        return 0


class WaitingSession(FakeSession):
    """Stands in for a step whose sudo call is blocked on the answer."""

    def run(self, emit, cancel) -> int:
        emit(Event("stage", text="kosctl install", key="core", index=1, total=1))
        while not cancel.is_set():
            time.sleep(0.02)
        self.result = "cancelled"
        emit(Event("cancelled", index=1, total=1))
        return 130


@unittest.skipUnless(HAS_TEXTUAL, "textual is not vendored (run tools/vendor.py)")
class SudoPromptTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        patchers = [
            mock.patch("installer.workflow.identity", side_effect=fake_source),
            # No backend probe: it would run the product's doctor for real.
            mock.patch("installer.ui.app.contract.read", return_value=None),
            mock.patch("installer.ui.app.probe.detect", return_value=None),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.helpers: list = []
        self.prompts_seen = 0
        self.answered: set[str] = set()

    def make_app(self, waiting: bool = False, real: bool = False) -> "KosApp":
        factory = None if real else WaitingSession if waiting else FakeSession
        return KosApp(lang="en", system=fake_system(),
                      paths=Paths.resolve(source_root=ROOT,
                                          env={"XDG_STATE_HOME": str(self.tmp)}),
                      prepare=fake_prepare, session_factory=factory)

    def ask_sudo(self, app) -> subprocess.Popen:
        """What a blocked sudo call does: start the helper, wait for an answer."""
        helper = subprocess.Popen([str(app.askpass.helper_path)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(helper.kill)
        self.helpers.append(helper)
        return helper

    async def to_installation(self, pilot) -> None:
        await pilot.press("tab")     # Welcome -> Checks
        await pilot.pause()
        await pilot.press("tab")     # Checks -> Options
        await pilot.pause()
        await pilot.press("tab")     # Options -> Review
        await pilot.pause()
        await pilot.press("enter")   # Review -> confirmation page
        await pilot.pause()
        await pilot.press("y")       # the confirmation itself

    async def wait_screen(self, app, kind) -> None:
        for _ in range(400):
            await asyncio.sleep(0.01)
            if isinstance(app.screen, kind):
                return
        self.fail(f"{kind.__name__} never became the active screen "
                  f"(on {type(app.screen).__name__})")

    async def settle(self, pilot) -> None:
        """Let a freshly pushed screen finish mounting before the app closes."""
        for _ in range(5):
            await pilot.pause()

    def bars(self, app) -> list:
        """Every visible sudo bar; there is never more than one."""
        found = []
        for screen in app._screen_stack:
            for bar in screen.query("#sudo_bar"):
                if bar.display:
                    found.append(bar)
        return found

    async def wait_bar(self, app, pilot=None):
        """Wait for the inline bar and for its layout: it appears first."""
        for _ in range(500):
            await asyncio.sleep(0.01)
            if self.bars(app):
                if pilot is not None:
                    for _ in range(3):
                        await pilot.pause()
                return self.bars(app)[0]
        self.fail(f"no sudo bar was raised (on {type(app.screen).__name__})")

    async def answer_bar(self, app, pilot) -> None:
        """Wait until a request raises the bar, then answer that request."""
        bar = await self.wait_bar(app, pilot)
        for _ in range(100):
            if app._sudo_token is not None and app._sudo_token not in self.answered:
                break
            await asyncio.sleep(0.01)
        self.assertEqual(len(self.bars(app)), 1)
        self.answered.add(app._sudo_token)
        self.prompts_seen += 1
        bar.screen.query_one("#sudo_input", Input).value = PASSWORD
        await pilot.press("enter")

    async def test_two_sudo_calls_two_prompts(self) -> None:
        # A full install: the package step asks, then the plugins after the build.
        # Both steps call the helper exactly the way sudo -A does.
        call = '"$SUDO_ASKPASS" >/dev/null && echo asked'
        steps = [Step("build", "build packages", ["sh", "-c", call]),
                 Step("plugins", "kwin system plugins", ["sh", "-c", call])]
        app = self.make_app(real=True)
        with mock.patch("installer.ui.app.build_plan", return_value=steps):
            async with app.run_test(size=(100, 30)) as pilot:
                await self.to_installation(pilot)
                await self.answer_bar(app, pilot)    # the build's sudo call
                await self.answer_bar(app, pilot)    # the plugins' sudo call
                await self.wait_screen(app, ResultScreen)
                await self.settle(pilot)

        self.assertEqual(self.prompts_seen, 2)
        log = app.log_path.read_text(encoding="utf-8")
        self.assertEqual(log.count("asked"), 2)     # two separate sudo invocations
        self.assertNotIn(PASSWORD, log)

    async def test_sudo_that_does_not_ask_never_prompts(self) -> None:
        # `sudo -n` would succeed here: no request, so no dialog at all.
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_installation(pilot)
            await self.wait_screen(app, ResultScreen)
            await self.settle(pilot)
            self.assertEqual(self.bars(app), [])
        self.assertIsNone(app.askpass)          # the tree is gone after the run

    async def test_a_blocked_sudo_call_raises_the_bar_and_is_answered(self) -> None:
        app = self.make_app(waiting=True)
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_installation(pilot)
            await self.wait_screen(app, InstallationScreen)
            # The plan is running and nothing has asked: no prompt at start.
            await asyncio.sleep(0.5)
            self.assertEqual(self.bars(app), [])
            self.assertEqual(self.prompts_seen, 0)

            helper = self.ask_sudo(app)
            bar = await self.wait_bar(app, pilot)
            self.assertEqual(len(self.bars(app)), 1)
            self.assertIsInstance(app.screen, InstallationScreen)
            self.assertNotIsInstance(app.screen, ModalScreen)
            field = bar.screen.query_one("#sudo_input", Input)
            self.assertIs(app.focused, field)

            field.value = PASSWORD
            self.assertEqual(field.value, PASSWORD)
            self.assertEqual(field._value.plain, "")      # no echo, not even dots
            await pilot.press("enter")
            # Off the event loop, as the bar never blocks it either.
            out, _err = await asyncio.to_thread(helper.communicate, 30)
            self.assertEqual(out.decode(), PASSWORD)   # the answer reached sudo
            self.assertIsNone(app.askpass.pending())
            self.assertNotIn(PASSWORD, "\n".join(app.log_tail))
            self.assertEqual(self.bars(app), [])       # the bar went away
            self.assertEqual(bar.screen.query_one("#sudo_input", Input).value, "")

            app.cancel_install()
            await self.wait_screen(app, ResultScreen)
            await self.settle(pilot)
        self.assertIsNone(app.askpass)

    async def test_one_bar_at_a_time_then_the_next_request(self) -> None:
        app = self.make_app(waiting=True)
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_installation(pilot)
            await self.wait_screen(app, InstallationScreen)

            first = self.ask_sudo(app)
            await self.wait_bar(app, pilot)
            second = self.ask_sudo(app)
            await asyncio.sleep(0.5)
            self.assertEqual(len(self.bars(app)), 1)   # it did not stack

            app.screen.query_one("#sudo_input", Input).value = PASSWORD
            await pilot.press("enter")
            await asyncio.to_thread(first.communicate, 30)
            # The request that arrived while the bar was up is asked next.
            await self.wait_bar(app, pilot)
            self.assertEqual(len(self.bars(app)), 1)
            app.screen.query_one("#sudo_input", Input).value = PASSWORD
            await pilot.press("enter")
            out, _err = await asyncio.to_thread(second.communicate, 30)
            self.assertEqual(out.decode(), PASSWORD)

            app.cancel_install()
            await self.wait_screen(app, ResultScreen)
            await self.settle(pilot)

    async def test_cancel_denies_and_stops_the_run(self) -> None:
        app = self.make_app(waiting=True)
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_installation(pilot)
            await self.wait_screen(app, InstallationScreen)
            helper = self.ask_sudo(app)
            await self.wait_bar(app, pilot)
            self.assertNotIsInstance(app.screen, ModalScreen)

            await pilot.press("escape")
            out, _err = await asyncio.to_thread(helper.communicate, 30)
            self.assertEqual(out, b"")          # denied, not answered
            await self.wait_screen(app, ResultScreen)
            self.assertTrue(app.cancel_event.is_set())
            self.assertIn(Strings("en")("sudo_password_missing"),
                          "\n".join(app.log_tail))
            self.assertNotIn(PASSWORD, "\n".join(app.log_tail))
            await self.settle(pilot)
        self.assertIsNone(app.askpass)
        self.assertEqual(app.exit_code, 130)

    async def start_units_action(self, app, pilot) -> None:
        """Management -> Units, with one action running and waiting on sudo."""
        app.screen._open_management()
        await self.wait_screen(app, ManagementScreen)
        for _ in range(200):
            if app.screen.query_one("#manage_list", OptionList).option_count == 6:
                break
            await asyncio.sleep(0.01)
        await pilot.press("1")
        await self.wait_screen(app, UnitsScreen)
        for _ in range(200):
            if app.screen.query_one("#manage_list", OptionList).option_count == len(UNITS):
                break
            await asyncio.sleep(0.01)
        app.start_action(app.screen, "test action", [])
        for _ in range(200):
            if app.screen.busy:
                break
            await asyncio.sleep(0.01)
        self.assertTrue(app.screen.busy)

    def manage_fakes(self) -> None:
        for target, value in (("installer.manage.units", UNITS),
                              ("installer.manage.snapshots", []),
                              ("installer.manage.logs", [])):
            patcher = mock.patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_the_bar_shows_on_a_management_action(self) -> None:
        self.manage_fakes()
        app = self.make_app(waiting=True)
        async with app.run_test(size=(100, 30)) as pilot:
            await self.start_units_action(app, pilot)
            helper = self.ask_sudo(app)
            bar = await self.wait_bar(app, pilot)
            self.assertIsInstance(app.screen, UnitsScreen)
            self.assertNotIsInstance(app.screen, ModalScreen)
            self.assertEqual(app.focused.id, "sudo_input")

            bar.screen.query_one("#sudo_input", Input).value = PASSWORD
            await pilot.press("enter")
            out, _err = await asyncio.to_thread(helper.communicate, 30)
            self.assertEqual(out.decode(), PASSWORD)
            self.assertEqual(self.bars(app), [])
            self.assertEqual(app.focused.id, "manage_list")   # focus came back
            app.cancel_action()
            for _ in range(300):
                if not app.screen.busy:
                    break
                await asyncio.sleep(0.01)
            self.assertFalse(app.screen.busy)

    async def test_escape_on_a_management_bar_stops_the_action_in_place(self) -> None:
        self.manage_fakes()
        app = self.make_app(waiting=True)
        async with app.run_test(size=(100, 30)) as pilot:
            await self.start_units_action(app, pilot)
            helper = self.ask_sudo(app)
            await self.wait_bar(app, pilot)
            await pilot.press("escape")
            out, _err = await asyncio.to_thread(helper.communicate, 30)
            self.assertEqual(out, b"")                 # denied, not answered
            for _ in range(300):
                if not app.screen.busy:
                    break
                await asyncio.sleep(0.01)
            self.assertIsInstance(app.screen, UnitsScreen)   # Esc did not pop
            self.assertFalse(app.screen.busy)
            self.assertEqual(self.bars(app), [])

    async def test_the_bar_waits_for_a_modal_to_close(self) -> None:
        app = self.make_app(waiting=True)
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_installation(pilot)
            await self.wait_screen(app, InstallationScreen)
            await pilot.press("ctrl+k")
            await pilot.pause()
            self.assertIsInstance(app.screen, HelpScreen)

            helper = self.ask_sudo(app)
            await asyncio.sleep(0.5)
            self.assertEqual(self.bars(app), [])       # no bar under the modal
            self.assertIsNone(app._sudo_token)

            await pilot.press("escape")
            await pilot.pause()
            await self.wait_bar(app, pilot)            # shown once help closes
            self.assertIsInstance(app.screen, InstallationScreen)
            await pilot.press("escape")                # deny, and finish
            await asyncio.to_thread(helper.communicate, 30)
            await self.wait_screen(app, ResultScreen)
            await self.settle(pilot)

    async def test_the_bar_fits_at_66_columns(self) -> None:
        app = self.make_app(waiting=True)
        async with app.run_test(size=(66, 20)) as pilot:
            await self.to_installation(pilot)
            await self.wait_screen(app, InstallationScreen)
            helper = self.ask_sudo(app)
            bar = await self.wait_bar(app, pilot)
            self.assertEqual(bar.size.height, 2)      # reason, field
            self.assertEqual(bar.region.bottom + 1,
                             bar.screen.query_one("#footer").region.y)
            body = str(bar.screen.query_one("#sudo_body").render())
            self.assertEqual(body, Strings("en")("sudo_password_body"))
            self.assertNotIn("never written", body)
            self.assertEqual(len(bar.screen.query("#sudo_title")), 0)
            self.assertFalse(bar.screen.query_one("#sudo_hint").display)
            prompt = str(bar.screen.query_one("#sudo_prompt").render())
            self.assertTrue(prompt.startswith("[sudo] password for "), prompt)
            log = bar.screen.query_one("#log", RichLog)
            self.assertEqual(bar.screen.query_one("#sudo_prompt").region.x,
                             log.region.x)
            field = bar.screen.query_one("#sudo_input", Input)
            self.assertEqual(field.size.height, 1)
            self.assertIs(app.focused, field)
            self.assertFalse(field._cursor_visible)      # no cursor block
            self.assertEqual(field.styles.background.a, 0)   # terminal shows through
            self.assertEqual(field.styles.background_tint.a, 0)
            await pilot.press("a")                       # typing restarts the blink
            self.assertFalse(field._cursor_visible)
            await pilot.press("escape")
            await asyncio.to_thread(helper.communicate, 30)
            await self.wait_screen(app, ResultScreen)
            await self.settle(pilot)

    async def test_wrong_password_is_surfaced_and_dropped(self) -> None:
        screen = Step("core", "kosctl install",
                      ["sh", "-c",
                       'echo "sudo: 3 incorrect password attempts" >&2; exit 1'])
        app = self.make_app(real=True)
        with mock.patch("installer.ui.app.build_plan", return_value=[screen]):
            async with app.run_test(size=(100, 30)) as pilot:
                await self.to_installation(pilot)
                await self.wait_screen(app, ResultScreen)
                await pilot.pause()

                self.assertIn(Strings("en")("sudo_password_wrong"),
                              "\n".join(app.log_tail))
                await self.settle(pilot)
                self.assertIsNone(app.askpass)   # retry starts a fresh channel

                await pilot.press("ctrl+r")      # Retry returns to Review
                await pilot.pause()
                self.assertIsInstance(app.screen, ReviewScreen)


if __name__ == "__main__":
    unittest.main()
