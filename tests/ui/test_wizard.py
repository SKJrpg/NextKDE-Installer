"""Stage T2: the wizard reaches Options, Review, Installation and Result.

Every test is offline: preparation and the install session are injected, and the
source is never fetched. Skipped when textual is not vendored.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
_VENDOR = ROOT / "vendor"
if _VENDOR.is_dir():
    sys.path.insert(0, str(_VENDOR))
HAS_TEXTUAL = importlib.util.find_spec("textual") is not None

if HAS_TEXTUAL:
    from textual.widgets import Checkbox, RadioButton

    from installer import workflow
    from installer.detect import OsInfo, Probe, System
    from installer.core.events import Event
    from installer.paths import Paths
    from installer.plan import Options, build_plan
    from installer.source.models import PreparedSource
    from installer.ui.app import KosApp
    from installer.ui.screens.installation import InstallationScreen
    from installer.ui.screens.options import OptionsScreen
    from installer.ui.screens.result import ResultScreen
    from installer.ui.screens.review import ReviewScreen
    from installer.ui.screens.system import SystemScreen
    from installer.ui.screens.welcome import WelcomeScreen


def fake_system() -> "System":
    return System(
        os=OsInfo(id="cachyos", version="", like=("arch",), pretty="CachyOS"),
        family="arch",
        method="kosctl",
        arch="x86_64",
        probes=[Probe("probe_os", "PASS", "CachyOS"),
                Probe("probe_disk", "WARN", "4.2 GiB free")],
    )


def fake_source(mode: str = "stable") -> "PreparedSource":
    return PreparedSource(mode=workflow.MODES.get(mode, "stable"),
                          repository="https://example.invalid/r.git",
                          ref="v1.0", commit="a" * 40,
                          path=Path("/tmp/nextkde-fake"), dirty=False,
                          managed=True)


def fake_prepare(mode, opts, paths) -> "workflow.Preparation":
    """Preparation that resolves instantly and never touches the network."""
    return workflow.Preparation(paths, prepared=fake_source())


def fake_identity(mode, opts, paths) -> "PreparedSource":
    """The identity Review resolves for an unprepared source, offline."""
    return fake_source(mode)


def radio_on(app) -> str:
    """The marker the Options rows use for a selected radio, per terminal."""
    return "(*)" if app.strings.ascii else "(•)"


class FakeSession:
    """A session with the real interface: emits events, honours the cancel flag."""

    def __init__(self, steps, log_path, root, mode: str = "ok") -> None:
        self.steps = list(steps)
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
            cancel.wait(5)
            self.result, self.exit_code = "cancelled", 130
            emit(Event("cancelled", index=1, total=1))
            return 130
        for index, step in enumerate(self.steps, 1):
            emit(Event("stage", text=step.title, key=step.key, index=index,
                       total=len(self.steps)))
            emit(Event("log", text="ran " + step.key, level="OK"))
        self.result = "ok"
        emit(Event("done", index=len(self.steps), total=len(self.steps)))
        return 0


@unittest.skipUnless(HAS_TEXTUAL, "textual is not vendored (run tools/vendor.py)")
class WizardTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # Review resolves the source identity to build the real plan.
        patcher = mock.patch("installer.workflow.identity", side_effect=fake_identity)
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_app(self, mode: str = "ok") -> "KosApp":
        return KosApp(lang="en", system=fake_system(),
                      paths=Paths.resolve(source_root=ROOT),
                      prepare=fake_prepare,
                      session_factory=lambda steps, log_path, root: FakeSession(
                          steps, log_path, root, mode))

    async def to_options(self, pilot) -> None:
        await pilot.press("enter")   # Welcome -> Checks
        await pilot.pause()
        await pilot.press("enter")   # Checks -> Options
        await pilot.pause()

    async def wait_screen(self, app, kind) -> None:
        for _ in range(200):
            await asyncio.sleep(0.01)
            if isinstance(app.screen, kind):
                return
        self.fail(f"{kind.__name__} never became the active screen")

    async def test_options_survive_back_and_forward(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_options(pilot)
            self.assertIsInstance(app.screen, OptionsScreen)
            self.assertIn("[ ]", app.screen.query_one("#app_todo", Checkbox).label.plain)
            app.screen.query_one("#app_todo", Checkbox).value = True
            await pilot.pause()
            self.assertIn("todo", app.opts.app_set)
            self.assertIn("[x]", app.screen.query_one("#app_todo", Checkbox).label.plain)

            await pilot.press("escape")
            await pilot.pause()
            self.assertIsInstance(app.screen, SystemScreen)

            await pilot.press("enter")
            await pilot.pause()
            self.assertIsInstance(app.screen, OptionsScreen)
            self.assertIn("[x]", app.screen.query_one("#app_todo", Checkbox).label.plain)
            self.assertIn("[x]", app.screen.query_one("#core", Checkbox).label.plain)
            self.assertTrue(app.screen.query_one("#core", Checkbox).disabled)

    async def test_seeded_options_are_shown(self) -> None:
        # What `--source local --apps todo` produces must be on screen already.
        app = KosApp(lang="en", system=fake_system(),
                     paths=Paths.resolve(source_root=ROOT),
                     opts=Options(source="local", apps=True, app_set={"todo"}))
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_options(pilot)
            self.assertTrue(app.screen.query_one("#source_local", RadioButton)
                            .label.plain.startswith(radio_on(app)))
            self.assertTrue(app.screen.query_one("#app_todo", Checkbox)
                            .label.plain.startswith("[x] "))
            self.assertTrue(app.screen.query_one("#app_calendar", Checkbox)
                            .label.plain.startswith("[ ] "))

    async def test_selected_rows_carry_different_text_markers(self) -> None:
        app = KosApp(lang="en", system=fake_system(),
                     paths=Paths.resolve(source_root=ROOT),
                     opts=Options(source="local", apps=True, app_set={"todo"}))
        async with app.run_test(size=(66, 20)) as pilot:
            await self.to_options(pilot)

            def label(ident: str) -> str:
                return app.screen.query_one("#" + ident).label.plain

            self.assertTrue(label("app_todo").startswith("[x] "))
            self.assertTrue(label("app_calendar").startswith("[ ] "))
            self.assertTrue(label("source_local").startswith(radio_on(app) + " "))
            self.assertTrue(label("source_main").startswith("( ) "))
            self.assertNotEqual(label("app_todo")[:3], label("source_local")[:3])

            app.screen.query_one("#source_main", RadioButton).value = True
            app.screen.query_one("#app_calendar", Checkbox).value = True
            await pilot.pause()
            self.assertTrue(label("source_main").startswith(radio_on(app) + " "))
            self.assertTrue(label("source_local").startswith("( ) "))
            self.assertTrue(label("app_calendar").startswith("[x] "))

    async def test_review_lists_the_real_plan(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_options(pilot)
            await pilot.press("enter")
            await pilot.pause()
            self.assertIsInstance(app.screen, ReviewScreen)
            steps = build_plan(app.system.family, app.opts, app.paths,
                               fake_source(app.opts.source))
            text = str(app.screen.query_one("#steps").render())
            for step in steps:
                self.assertIn(step.title, text)

            await pilot.press("t")
            await pilot.pause()
            argv = " ".join(steps[0].argv)
            self.assertIn(argv, str(app.screen.query_one("#steps").render()))

    async def test_review_omits_the_legacy_update_step(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_options(pilot)
            await pilot.press("enter")
            await pilot.pause()
            self.assertIsInstance(app.screen, ReviewScreen)
            text = str(app.screen.query_one("#steps").render())
            self.assertNotIn("kosctl update", text)
            prepared = build_plan(app.system.family, app.opts, app.paths,
                                  fake_source(app.opts.source))
            self.assertNotIn("source", [step.key for step in prepared])
            for step in prepared:
                self.assertIn(step.title, text)

    async def test_confirm_reaches_installation_and_result(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_options(pilot)
            await pilot.press("enter")   # Options -> Review
            await pilot.pause()
            await pilot.press("enter")   # Review -> prepare + install
            await pilot.pause()
            await self.wait_screen(app, ResultScreen)
            self.assertTrue(any(isinstance(screen, InstallationScreen)
                                for screen in app._screen_stack))
            self.assertEqual(app.exit_code, 0)
            head = str(app.screen.query_one("#result_head").render())
            text = str(app.screen.query_one("#result_text").render())
            self.assertIn("finished", head.lower())
            self.assertIn("kosctl install", text)

    async def test_ctrl_c_during_install_ends_cancelled(self) -> None:
        app = self.make_app(mode="cancel")
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_options(pilot)
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            for _ in range(200):
                await asyncio.sleep(0.01)
                if isinstance(app.screen, InstallationScreen) and app.session is not None:
                    break
            await pilot.press("ctrl+c")
            await self.wait_screen(app, ResultScreen)
            self.assertEqual(app.exit_code, 130)
            text = str(app.screen.query_one("#result_text").render())
            self.assertIn("cancelled", text.lower())

    async def test_activity_indicator_lives_only_while_installing(self) -> None:
        app = self.make_app(mode="cancel")
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_options(pilot)
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            for _ in range(200):
                await asyncio.sleep(0.01)
                if isinstance(app.screen, InstallationScreen) and app.session is not None:
                    break
            screen = app.screen
            self.assertEqual(len(screen.query("#activity")), 1)

            await pilot.press("ctrl+c")
            await self.wait_screen(app, ResultScreen)
            await pilot.pause()
            self.assertEqual(len(screen.query("#activity")), 0)

    async def test_activity_indicator_stops_when_the_run_finishes(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_options(pilot)
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            await self.wait_screen(app, ResultScreen)
            await pilot.pause()
            install = next(s for s in app._screen_stack
                           if isinstance(s, InstallationScreen))
            self.assertEqual(len(install.query("#activity")), 0)
