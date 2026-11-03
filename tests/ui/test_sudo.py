"""The sudo password prompt: asked once, reused, never kept.

Offline: sudo is never run (``sudo_ready`` is patched) and the plan is a step
that prints the askpass variables instead of installing anything.
"""

from __future__ import annotations

import asyncio
import importlib.util
import shutil
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


def print_env_step(key: str = "core") -> "Step":
    return Step(key, "kosctl install",
                ["sh", "-c", 'printf "%s\\n" "$SUDO_ASKPASS"'])


@unittest.skipUnless(HAS_TEXTUAL, "textual is not vendored (run tools/vendor.py)")
class SudoPromptTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.sudo_ready = True
        patchers = [
            mock.patch("installer.workflow.identity", side_effect=fake_source),
            mock.patch("installer.ui.app.sudo_ready",
                       side_effect=lambda: self.sudo_ready),
            # No backend probe: it would run the product's doctor for real.
            mock.patch("installer.ui.app.contract.read", return_value=None),
            mock.patch("installer.ui.app.probe.detect", return_value=None),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def make_app(self, fake_session: bool = True) -> "KosApp":
        return KosApp(lang="en", system=fake_system(),
                      paths=Paths.resolve(source_root=ROOT,
                                          env={"XDG_STATE_HOME": str(self.tmp)}),
                      prepare=fake_prepare,
                      session_factory=(None if not fake_session else
                                       lambda steps, log_path, root: FakeSession(
                                           steps, log_path, root)))

    async def to_review(self, pilot) -> None:
        await pilot.press("enter")   # Welcome -> Checks
        await pilot.pause()
        await pilot.press("enter")   # Checks -> Options
        await pilot.pause()
        await pilot.press("enter")   # Options -> Review
        await pilot.pause()

    async def wait_screen(self, app, kind) -> None:
        for _ in range(300):
            await asyncio.sleep(0.01)
            if isinstance(app.screen, kind):
                return
        self.fail(f"{kind.__name__} never became the active screen")

    def prompts(self, app) -> list:
        return [screen for screen in app._screen_stack
                if isinstance(screen, PasswordDialog)]

    async def test_no_prompt_when_sudo_is_primed(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_review(pilot)
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(self.prompts(app), [])
            self.assertTrue(any(isinstance(screen, InstallationScreen)
                                for screen in app._screen_stack))
            self.assertIsNone(app.askpass)

    async def test_prompt_appears_and_cancel_keeps_review(self) -> None:
        self.sudo_ready = False
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_review(pilot)
            await pilot.press("enter")
            await pilot.pause()
            self.assertIsInstance(app.screen, PasswordDialog)
            self.assertIsNone(app.askpass)

            await pilot.press("escape")
            await pilot.pause()
            self.assertIsInstance(app.screen, ReviewScreen)
            self.assertIsNone(app.askpass)

    async def test_one_password_reaches_the_run_then_is_removed(self) -> None:
        self.sudo_ready = False
        app = self.make_app(fake_session=False)
        with mock.patch("installer.ui.app.build_plan",
                        return_value=[print_env_step("one"), print_env_step("two")]):
            async with app.run_test(size=(100, 30)) as pilot:
                await self.to_review(pilot)
                await pilot.press("enter")
                await pilot.pause()
                self.assertIsInstance(app.screen, PasswordDialog)
                app.screen.query_one("#sudo_password", Input).value = PASSWORD
                await pilot.press("enter")
                await self.wait_screen(app, ResultScreen)
                await pilot.pause()

        lines = [line for line in app.log_tail if "/askpass.sh" in line]
        self.assertEqual(len(lines), 2)                 # both steps, same helper
        self.assertEqual(lines[0], lines[1])
        self.assertFalse(Path(lines[0]).exists())       # tree removed after the run
        self.assertIsNone(app.askpass)
        # The secret never reaches the log or the result tail.
        self.assertNotIn(PASSWORD, "\n".join(app.log_tail))
        self.assertNotIn(PASSWORD, app.log_path.read_text(encoding="utf-8"))

    async def test_wrong_password_is_surfaced_and_dropped(self) -> None:
        self.sudo_ready = False
        screen = Step("core", "kosctl install",
                      ["sh", "-c",
                       'echo "sudo: 3 incorrect password attempts" >&2; exit 1'])
        app = self.make_app(fake_session=False)
        with mock.patch("installer.ui.app.build_plan", return_value=[screen]):
            async with app.run_test(size=(100, 30)) as pilot:
                await self.to_review(pilot)
                await pilot.press("enter")
                await pilot.pause()
                app.screen.query_one("#sudo_password", Input).value = PASSWORD
                await pilot.press("enter")
                await self.wait_screen(app, ResultScreen)
                await pilot.pause()

                self.assertIn(Strings("en")("sudo_password_wrong"),
                              "\n".join(app.log_tail))
                self.assertIsNone(app.askpass)   # retry asks again

                await pilot.press("r")           # Retry returns to Review
                await pilot.pause()
                self.assertIsInstance(app.screen, ReviewScreen)


if __name__ == "__main__":
    unittest.main()
