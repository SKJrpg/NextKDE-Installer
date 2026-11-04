"""Feedback and navigation: failure guidance, the help overlay, Esc, step jumps.

Offline like the other UI tests: preparation is injected and no source is fetched.
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
    from textual.widgets._footer import FooterKey

    from installer import workflow
    from installer.core.events import Event
    from installer.detect import OsInfo, Probe, System
    from installer.paths import Paths
    from installer.source.models import PreparedSource
    from installer.strings import Strings
    from installer.ui.app import KosApp
    from installer.ui.screens.installation import InstallationScreen
    from installer.ui.screens.logs import LogViewerScreen
    from installer.ui.screens.options import OptionsScreen
    from installer.ui.screens.review import ReviewScreen, advice_for
    from installer.ui.screens.system import SystemScreen
    from installer.ui.screens.welcome import WelcomeScreen
    from installer.ui.widgets.confirm import ConfirmDialog
    from installer.ui.widgets.help import HelpScreen


def fake_system() -> "System":
    return System(
        os=OsInfo(id="cachyos", version="", like=("arch",), pretty="CachyOS"),
        family="arch", method="kosctl", arch="x86_64",
        probes=[Probe("probe_os", "PASS", "CachyOS"),
                Probe("probe_disk", "WARN", "4.2 GiB free")])


def fake_source() -> "PreparedSource":
    return PreparedSource(mode="stable", repository="https://example.invalid/r.git",
                          ref="v1.0", commit="a" * 40,
                          path=Path("/tmp/nextkde-fake"), dirty=False, managed=True)


def fake_prepare(mode, opts, paths) -> "workflow.Preparation":
    return workflow.Preparation(paths, prepared=fake_source())


def footer_text(target) -> str:
    """What a screen's footer currently says, as one string."""
    screen = getattr(target, "screen", target)
    return " ".join(key.description for key in screen.query(FooterKey))


class FakeSession:
    """The real session interface, without running anything."""

    def __init__(self, steps, log_path, root) -> None:
        self.steps, self.log_path, self.root = list(steps), log_path, root
        self.result, self.exit_code, self.failed_index = "", 0, None
        self.tail: list[tuple[str, str]] = []

    def run(self, emit, cancel) -> int:
        self.result = "ok"
        return 0


@unittest.skipUnless(HAS_TEXTUAL, "textual is not vendored (run tools/vendor.py)")
class GuidanceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        patcher = mock.patch("installer.workflow.identity", return_value=fake_source())
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_app(self) -> "KosApp":
        return KosApp(lang="en", system=fake_system(),
                      paths=Paths.resolve(source_root=ROOT),
                      prepare=fake_prepare,
                      session_factory=FakeSession)

    async def wait_screen(self, app, kind) -> None:
        for _ in range(200):
            await asyncio.sleep(0.01)
            if isinstance(app.screen, kind):
                return
        self.fail(f"{kind.__name__} never became the active screen")

    async def to_review(self, pilot) -> None:
        for _ in range(3):          # Welcome -> Checks -> Options -> Review
            await pilot.press("enter")
            await pilot.pause()

    # -- B: a failure that says what to do -------------------------------
    async def test_failed_preparation_names_the_step_and_the_keys(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            app.prepare_error = ("fatal: unable to access 'https://example.invalid/r.git/': "
                                 "Could not resolve host: example.invalid")
            app.push_screen(ReviewScreen(Strings("en")))
            await pilot.pause()
            status = str(app.screen.query_one("#status").render())
            self.assertIn("git clone", status)                  # names the step
            self.assertIn("[r] retry", status)
            self.assertIn("[l]", status)
            self.assertIn("[Esc] back", status)
            self.assertIn(Strings("en")("advice_network"), status)
            self.assertIn("Could not resolve host", status)     # the raw reason
            footer = footer_text(app)
            self.assertIn("retry", footer)
            self.assertIn("log", footer)

    async def test_a_failed_review_can_open_the_log(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            app.prepare_error = "fatal: something"
            app.push_screen(ReviewScreen(Strings("en")))
            await pilot.pause()
            await pilot.press("l")
            await pilot.pause()
            self.assertIsInstance(app.screen, LogViewerScreen)
            await pilot.press("escape")
            await pilot.pause()
            self.assertIsInstance(app.screen, ReviewScreen)

    async def test_a_healthy_review_offers_no_retry_or_log(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_review(pilot)
            self.assertIsInstance(app.screen, ReviewScreen)
            footer = footer_text(app)
            self.assertNotIn("retry", footer)
            self.assertNotIn("log", footer)

    def test_the_common_causes_have_one_line_of_advice(self) -> None:
        self.assertEqual(advice_for("Could not resolve host: github.com"), "advice_network")
        self.assertEqual(advice_for("fatal: Connection timed out"), "advice_network")
        self.assertEqual(advice_for("https://x has no ref v9.9.9"), "advice_tag")
        self.assertEqual(advice_for("Permission denied (publickey)"), "advice_credentials")
        self.assertEqual(advice_for("fatal: repository 'x' not found"), "")
        self.assertEqual(advice_for("[Errno 13] Permission denied: /x"), "advice_permissions")
        self.assertEqual(advice_for("exit status 1"), "")    # no advice is invented
        for key in ("advice_network", "advice_tag", "advice_credentials",
                    "advice_permissions", "review_error_keys", "key_jump",
                    "quit_title", "quit_confirm"):
            for lang in ("zh", "en"):
                self.assertNotEqual(Strings(lang)(key), key)

    # -- A: the clone's own progress -------------------------------------
    async def test_preparing_shows_the_percentage_and_the_last_line(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            screen = InstallationScreen(Strings("en"))
            app.push_screen(screen)
            await pilot.pause()
            screen.handle(Event("stage", text="git clone v0.3.0", index=1, total=1))
            await pilot.pause()
            self.assertIn("git clone v0.3.0",
                          str(screen.query_one("#stages").render()))
            # Nothing measured yet: the bar stays indeterminate.
            self.assertIn("no measured progress",
                          str(screen.query_one("#progress_state").render()))
            screen.handle(Event("log", text="Receiving objects:  42% (4116/9800), 4.1 MiB"))
            screen.handle(Event("stage", text="git clone v0.3.0", index=1, total=1,
                                fraction=0.42))
            await pilot.pause()
            state = str(screen.query_one("#progress_state").render())
            self.assertIn("42%", state)
            self.assertIn("Receiving objects:  42% (4116/9800)", state)

    # -- C: help, Esc and jumps ------------------------------------------
    async def test_help_lists_only_the_current_screens_keys(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(66, 20)) as pilot:
            await self.to_review(pilot)
            await pilot.press("?")
            await pilot.pause()
            self.assertIsInstance(app.screen, HelpScreen)
            body = str(app.screen.query_one("#help_body").render())
            self.assertIn("start install", body)
            self.assertIn("commands", body)
            self.assertIn("back", body)
            self.assertIn("jump to step", body)
            self.assertNotIn("re-check", body)          # a Checks-only key
            await pilot.press("escape")
            await pilot.pause()
            self.assertIsInstance(app.screen, ReviewScreen)

    async def test_help_lists_the_language_key_on_welcome(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("?")
            await pilot.pause()
            body = str(app.screen.query_one("#help_body").render())
            self.assertIn("language", body)
            self.assertNotIn("jump to step", body)      # nowhere to jump from Welcome

    async def test_escape_steps_back_through_the_wizard(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_review(pilot)
            for kind in (OptionsScreen, SystemScreen, WelcomeScreen):
                await pilot.press("escape")
                await pilot.pause()
                self.assertIsInstance(app.screen, kind)

    async def test_escape_on_welcome_asks_before_quitting(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            self.assertIsInstance(app.screen, ConfirmDialog)
            self.assertIn(Strings("en")("quit_confirm"),
                          str(app.screen.query_one("#confirm_body").render()))
            await pilot.press("escape")         # cancel: still here
            await pilot.pause()
            self.assertIsInstance(app.screen, WelcomeScreen)

    async def test_numbers_jump_to_a_completed_step(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_review(pilot)
            await pilot.press("2")
            await pilot.pause()
            self.assertIsInstance(app.screen, SystemScreen)
            await pilot.press("5")             # beyond Review: not available
            await pilot.pause()
            self.assertIsInstance(app.screen, SystemScreen)
            app.push_screen(ReviewScreen(Strings("en")))
            await pilot.pause()
            await pilot.press("1")
            await pilot.pause()
            self.assertIsInstance(app.screen, WelcomeScreen)

    async def test_clicking_a_sidebar_step_jumps_there(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_review(pilot)
            await pilot.click("#sidebar", offset=(2, 3))   # third row: Options
            await pilot.pause()
            self.assertIsInstance(app.screen, OptionsScreen)

    # -- the footer and the help come from one table ----------------------
    async def test_footer_and_help_agree_on_every_screen(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            screens = []
            await pilot.pause()
            screens.append(app.screen)                       # Welcome
            for _ in range(2):
                await pilot.press("enter")
                await pilot.pause()
                screens.append(app.screen)                   # Checks, Options
            await pilot.press("enter")
            await pilot.pause()
            screens.append(app.screen)                       # Review
            app.prepare_error = "fatal: no ref v9"
            app.screen.reload()
            await pilot.pause()
            screens.append(app.screen)                       # Review, failed

            for screen in screens:
                s = Strings("en")

                # One table: a footer hint is a table word, and nothing else.
                labels = {s(label) for _k, _a, label, *_r in screen.keys() if label}
                for key in screen.query(FooterKey):
                    self.assertIn(key.description, labels,
                                  f"{screen.__class__.__name__}: footer says "
                                  f"{key.description!r}")
                # The overlay lists those words, plus where digits go.
                allowed = labels | {s("key_jump")}
                for text in dict(screen.help_rows()).values():
                    self.assertIn(text, allowed)
                # And every hint names an action the screen really has.
                for keys, action, label, *rest in screen.keys():
                    name = action.split("(")[0]
                    if not (rest[1] if len(rest) > 1 else True):
                        continue        # grouped into another row, e.g. ↓
                    self.assertTrue(callable(getattr(screen, "action_" + name, None)),
                                    f"{screen.__class__.__name__}: no action_{name}")
                    if name == "help" or screen.check_action(name, ()) is False:
                        continue        # no hint is offered for these two states
                    self.assertIn(s(label), dict(screen.help_rows()).values())
            self.assertIn("retry", footer_text(app))

