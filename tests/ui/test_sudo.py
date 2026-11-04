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
    from textual.widgets import Input

    from installer import workflow
    from installer.core.events import Event
    from installer.detect import OsInfo, Probe, System
    from installer.paths import Paths
    from installer.plan import Step
    from installer.source.models import PreparedSource
    from installer.strings import Strings
    from installer.ui.app import KosApp
    from installer.ui.screens.installation import InstallationScreen
    from installer.ui.screens.result import ResultScreen
    from installer.ui.screens.review import ReviewScreen
    from installer.ui.widgets.password import PasswordDialog

PASSWORD = "hunter2-s3cret"


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
        await pilot.press("enter")   # Welcome -> Checks
        await pilot.pause()
        await pilot.press("enter")   # Checks -> Options
        await pilot.pause()
        await pilot.press("enter")   # Options -> Review
        await pilot.pause()
        await pilot.press("enter")   # Review -> confirmation page
        await pilot.pause()
        await pilot.press("1")       # select "start", which does not run it
        await pilot.pause()
        await pilot.press("enter")   # the confirmation itself

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

    async def wait_dialog(self, app) -> None:
        """Wait for the dialog and for its field: the screen appears first."""
        await self.wait_screen(app, PasswordDialog)
        for _ in range(100):
            if app.screen.query("#sudo_password"):
                return
            await asyncio.sleep(0.01)
        self.fail("the password dialog never composed its field")

    def prompts(self, app) -> list:
        return [screen for screen in app._screen_stack
                if isinstance(screen, PasswordDialog)]

    async def answer_dialog(self, app, pilot) -> None:
        """Wait until a request raises the dialog, then answer that request."""
        for _ in range(500):
            await asyncio.sleep(0.01)
            if (isinstance(app.screen, PasswordDialog)
                    and app._dialog_token not in self.answered):
                break
        else:
            self.fail("no password dialog was raised")
        await self.settle(pilot)        # composed and focused before it is typed on
        self.assertEqual(len(self.prompts(app)), 1)
        self.answered.add(app._dialog_token)
        self.prompts_seen += 1
        app.screen.query_one("#sudo_password", Input).value = PASSWORD
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
                await self.answer_dialog(app, pilot)    # the build's sudo call
                await self.answer_dialog(app, pilot)    # the plugins' sudo call
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
            self.assertEqual(self.prompts(app), [])
        self.assertIsNone(app.askpass)          # the tree is gone after the run

    async def test_a_blocked_sudo_call_raises_the_dialog_and_is_answered(self) -> None:
        app = self.make_app(waiting=True)
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_installation(pilot)
            await self.wait_screen(app, InstallationScreen)
            # The plan is running and nothing has asked: no prompt at start.
            await asyncio.sleep(0.5)
            self.assertEqual(self.prompts(app), [])
            self.assertEqual(self.prompts_seen, 0)

            helper = self.ask_sudo(app)
            await self.wait_dialog(app)
            self.assertEqual(len(self.prompts(app)), 1)

            app.screen.query_one("#sudo_password", Input).value = PASSWORD
            await pilot.press("enter")
            # Off the event loop, as the dialog never blocks it either.
            out, _err = await asyncio.to_thread(helper.communicate, 30)
            self.assertEqual(out.decode(), PASSWORD)   # the answer reached sudo
            self.assertIsNone(app.askpass.pending())
            self.assertNotIn(PASSWORD, "\n".join(app.log_tail))

            app.cancel_install()
            await self.wait_screen(app, ResultScreen)
            await self.settle(pilot)
        self.assertIsNone(app.askpass)

    async def test_one_dialog_at_a_time_then_the_next_request(self) -> None:
        app = self.make_app(waiting=True)
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_installation(pilot)
            await self.wait_screen(app, InstallationScreen)

            first = self.ask_sudo(app)
            await self.wait_dialog(app)
            second = self.ask_sudo(app)
            await asyncio.sleep(0.5)
            self.assertEqual(len(self.prompts(app)), 1)   # it did not stack

            app.screen.query_one("#sudo_password", Input).value = PASSWORD
            await pilot.press("enter")
            await asyncio.to_thread(first.communicate, 30)
            # The request that arrived while the dialog was open is asked next.
            await self.wait_dialog(app)
            self.assertEqual(len(self.prompts(app)), 1)
            app.screen.query_one("#sudo_password", Input).value = PASSWORD
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
            await self.wait_dialog(app)

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

                await pilot.press("r")           # Retry returns to Review
                await pilot.pause()
                self.assertIsInstance(app.screen, ReviewScreen)


if __name__ == "__main__":
    unittest.main()
