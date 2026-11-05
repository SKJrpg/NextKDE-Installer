"""The key scheme as the user sees it: footers, help, Esc, confirmations.

Offline: preparation, the management reads and the install session are stubs.
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
    from textual.widgets import Button, OptionList
    from textual.widgets.option_list import Option

    from installer import manage, workflow
    from installer.core.events import Event
    from installer.detect import OsInfo, Probe, System
    from installer.paths import Paths
    from installer.source.models import PreparedSource
    from installer.strings import Strings
    from installer.ui import keymap
    from installer.ui.app import KosApp
    from installer.ui.screens.confirm import ConfirmScreen
    from installer.ui.screens.installation import InstallationScreen
    from installer.ui.screens.logs import LogViewerScreen, LogsScreen
    from installer.ui.screens.management import ManagementScreen
    from installer.ui.screens.options import OptionsScreen
    from installer.ui.screens.result import ResultScreen
    from installer.ui.screens.review import ReviewScreen, advice_for
    from installer.ui.screens.snapshots import SnapshotsScreen
    from installer.ui.screens.system import SystemScreen
    from installer.ui.screens.units import UnitsScreen
    from installer.ui.screens.welcome import WelcomeScreen
    from installer.ui.widgets.confirm import ConfirmDialog
    from installer.ui.widgets.help import HelpScreen


UNITS = [manage.Unit("core", "1.0", "dirs", 4, "2026-01-01T00:00:00"),
         manage.Unit("apps", "1.0", "files", 2, "")]
SNAPSHOTS = [manage.Snapshot("s1", "2026-01-01T00:00:00", "before", "config")]

FOOTERS = {
    "welcome": "⏎ next  ←/→ language  ^P manage  q quit  ? help",
    "checks": "↑/↓ select  ⏎ next  r re-check  esc back  q quit  ? help",
    "options_radio": "↑/↓ select  ⏎ next  esc back  q quit  ? help",
    "options_check": "space toggle  ↑/↓ move  ⏎ next  esc back  q quit  ? help",
    "review": "⏎ continue  t commands  esc back  q quit  ? help",
    "review_failed": "r retry  l log  esc back  q quit  ? help",
    "confirm": "1/2 select  ⏎ confirm  esc back  ? help",
    "installation": "ctrl+c abort  ? help",
    "result_ok": "q exit  l log  ^P manage  ? help",
    "result_failed": "r retry  l log  ^P manage  q exit  ? help",
    "management": "1–6 go to  ↑/↓ select  ⏎ open  esc back  ? help",
    "units": "↑/↓ select  ⏎ toggle  esc back  ? help",
    "snapshots": "↑/↓ select  ⏎ roll back  c create  esc back  ? help",
    "logs": "↑/↓ select  ⏎ open  esc back  ? help",
    "log_view": "↑/↓ scroll  esc back  ? help",
}


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


class FakeSession:
    """The session interface without running anything; ``cancel`` blocks."""

    def __init__(self, steps, log_path, root, mode: str = "ok") -> None:
        self.steps, self.log_path, self.root = list(steps), log_path, root
        self.mode = mode
        self.result, self.exit_code, self.failed_index = "", 0, None
        self.tail: list[tuple[str, str]] = []

    def run(self, emit, cancel) -> int:
        if self.mode == "cancel":
            emit(Event("stage", text="working", key="fake", index=1, total=1))
            cancel.wait(10)
            self.result, self.exit_code = "cancelled", 130
            emit(Event("cancelled", index=1, total=1))
            return 130
        self.result = "ok"
        return 0


def foot(app) -> str:
    return str(app.screen.query_one("#footer").render())


@unittest.skipUnless(HAS_TEXTUAL, "textual is not vendored (run tools/vendor.py)")
@unittest.skipIf(Strings("en").ascii, "the exact footer glyphs need UTF-8")
class KeySchemeTest(unittest.IsolatedAsyncioTestCase):
    def make_app(self, mode: str = "ok", **kwargs) -> "KosApp":
        return KosApp(lang="en", system=fake_system(),
                      paths=Paths.resolve(source_root=ROOT),
                      prepare=fake_prepare,
                      session_factory=lambda steps, log, root: FakeSession(steps, log, root, mode),
                      **kwargs)

    def setUp(self) -> None:
        patcher = mock.patch("installer.workflow.identity", side_effect=lambda *a: fake_source())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(keymap.apply_overrides, {})

    async def wait_for(self, pilot, predicate) -> None:
        for _ in range(300):
            await asyncio.sleep(0.01)
            if predicate():
                return
        self.fail("condition was never met")

    async def to_review(self, pilot) -> None:
        for _ in range(3):          # Welcome -> Checks -> Options -> Review
            await pilot.press("enter")
            await pilot.pause()

    async def to_confirm(self, pilot) -> None:
        await self.to_review(pilot)
        await pilot.press("enter")
        await pilot.pause()

    async def start_install(self, pilot) -> None:
        await self.to_confirm(pilot)
        await pilot.press("1")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    # -- footers: whole line, at both sizes ------------------------------
    async def test_wizard_footers_are_whole_lines_at_both_sizes(self) -> None:
        for size in ((100, 30), (66, 20)):
            with self.subTest(size=size):
                app = self.make_app()
                async with app.run_test(size=size) as pilot:
                    await pilot.pause()
                    self.assertEqual(foot(app), FOOTERS["welcome"])
                    await pilot.press("enter")
                    await pilot.pause()
                    self.assertEqual(foot(app), FOOTERS["checks"])
                    await pilot.press("enter")
                    await pilot.pause()
                    self.assertEqual(foot(app), FOOTERS["options_radio"])
                    await pilot.press("tab")
                    await pilot.pause()
                    self.assertEqual(foot(app), FOOTERS["options_check"])
                    await pilot.press("enter")
                    await pilot.pause()
                    self.assertEqual(foot(app), FOOTERS["review"])
                    await pilot.press("enter")
                    await pilot.pause()
                    self.assertEqual(foot(app), FOOTERS["confirm"])

    async def test_installation_and_result_footers(self) -> None:
        app = self.make_app(mode="cancel")
        async with app.run_test(size=(66, 20)) as pilot:
            await self.start_install(pilot)
            await self.wait_for(pilot, lambda: isinstance(app.screen, InstallationScreen))
            self.assertEqual(foot(app), FOOTERS["installation"])
            await pilot.press("ctrl+c")
            await self.wait_for(pilot, lambda: isinstance(app.screen, ConfirmDialog)
                                and bool(app.screen.query("#confirm_ok")))
            await pilot.click("#confirm_ok")
            await self.wait_for(pilot, lambda: isinstance(app.screen, ResultScreen))
            self.assertEqual(foot(app), FOOTERS["result_failed"])

        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            app.push_screen(ResultScreen(Strings("en"), "ok"))
            await pilot.pause()
            self.assertEqual(foot(app), FOOTERS["result_ok"])

    # -- the confirmation page -------------------------------------------
    async def test_confirm_defaults_to_back_and_enter_alone_never_installs(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_confirm(pilot)
            screen = app.screen
            self.assertIsInstance(screen, ConfirmScreen)
            self.assertEqual(screen.choice, "back")
            await pilot.press("enter")        # Enter on the default choice
            await pilot.pause()
            self.assertIsInstance(app.screen, ReviewScreen)   # back, not install
            self.assertTrue(all(not isinstance(s, InstallationScreen)
                                for s in app._screen_stack))

    async def test_numbers_only_move_the_choice(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_confirm(pilot)
            screen = app.screen
            await pilot.press("1")
            await pilot.pause()
            self.assertEqual(screen.choice, "install")
            self.assertIs(app.screen, screen)          # nothing started
            await pilot.press("2")
            await pilot.pause()
            self.assertEqual(screen.choice, "back")
            self.assertIs(app.screen, screen)

    async def test_the_chosen_install_does_start(self) -> None:
        app = self.make_app(mode="cancel")
        async with app.run_test(size=(100, 30)) as pilot:
            await self.start_install(pilot)
            await self.wait_for(pilot, lambda: isinstance(app.screen, InstallationScreen))

    # -- Esc is back only -------------------------------------------------
    async def test_escape_walks_back_and_never_quits(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_confirm(pilot)
            for kind in (ReviewScreen, OptionsScreen, SystemScreen, WelcomeScreen):
                await pilot.press("escape")
                await pilot.pause()
                self.assertIsInstance(app.screen, kind)
            await pilot.press("escape")       # Welcome has no page to go back to
            await pilot.pause()
            self.assertIsInstance(app.screen, WelcomeScreen)

    async def test_the_quit_question_takes_arrow_keys(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("q")
            await pilot.pause()
            self.assertIsInstance(app.screen, ConfirmDialog)
            self.assertEqual(app.focused.id, "confirm_cancel")
            await pilot.press("right")
            await pilot.pause()
            self.assertEqual(app.focused.id, "confirm_ok")
            await pilot.press("left")
            await pilot.pause()
            self.assertEqual(app.focused.id, "confirm_cancel")
            await pilot.press("escape")
            await pilot.pause()
            self.assertIsInstance(app.screen, SystemScreen)

    async def test_q_asks_mid_wizard_and_leaves_on_welcome(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("q")
            await pilot.pause()
            self.assertIsInstance(app.screen, ConfirmDialog)
            self.assertIn(Strings("en")("quit_stay"),
                          str(app.screen.query_one("#confirm_cancel", Button).label))
            await pilot.press("escape")
            await pilot.pause()
            self.assertIsInstance(app.screen, SystemScreen)

    # -- no wizard digits, no ctrl+q --------------------------------------
    async def test_digits_do_not_jump_the_wizard(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_review(pilot)
            await pilot.press("1")
            await pilot.pause()
            self.assertIsInstance(app.screen, ReviewScreen)
            options = [s for s in app._screen_stack if isinstance(s, OptionsScreen)]
            self.assertTrue(options)          # still there to go back to

    async def test_no_hidden_ctrl_q_quit(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_review(pilot)
            screen = app.screen
            await pilot.press("ctrl+q")
            await pilot.pause()
            self.assertIs(app.screen, screen)   # no inherited ctrl+q quit

    async def test_ctrl_c_twice_quits(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30), notifications=True) as pilot:
            await self.to_review(pilot)
            await pilot.press("ctrl+c")
            await pilot.pause()
            self.assertFalse(app._exit)
            self.assertIn(Strings("en")("ctrl_c_hint"),
                          [note.message for note in app._notifications])
            await pilot.press("ctrl+c")
            await pilot.pause()
            self.assertTrue(app._exit)

    async def test_ctrl_c_does_not_quit_through_a_question(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_review(pilot)
            await pilot.press("q")              # the quit question
            await pilot.pause()
            self.assertIsInstance(app.screen, ConfirmDialog)
            await pilot.press("ctrl+c")
            await pilot.press("ctrl+c")
            await pilot.pause()
            self.assertFalse(app._exit)
            self.assertIsInstance(app.screen, ConfirmDialog)

    # -- help overlay ------------------------------------------------------
    async def test_help_lists_what_the_footer_offers(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_review(pilot)
            for _ in range(4):
                screen = app.screen
                offered = {(row.action.id) for row in screen.footer_rows()}
                shown = set()
                for keys, label in screen.help_rows():
                    shown.add(label)
                self.assertTrue(all(rows for rows in (offered,)))
                await pilot.press("?")
                await pilot.pause()
                body = str(app.screen.query_one("#help_body").render())
                for _keys, label in screen.help_rows():
                    self.assertIn(label, body)
                self.assertIn("Tab", body)          # hidden rows are in the overlay
                await pilot.press("escape")
                await pilot.pause()
                if isinstance(app.screen, OptionsScreen):
                    await pilot.press("escape")
                    await pilot.pause()
                break

    async def test_every_offered_binding_has_a_method(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            screens = [app.screen]
            for _ in range(3):
                await pilot.press("enter")
                await pilot.pause()
                screens.append(app.screen)
            for screen in screens:
                for row in screen.key_rows():
                    for target in row.targets:
                        name = target.split("(")[0]
                        if "." in name:          # a namespace, e.g. app.focus_next
                            continue
                        self.assertTrue(
                            callable(getattr(screen, "action_" + name, None)),
                            f"{type(screen).__name__}: no action_{name}")

    async def test_help_on_checks_and_options(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(66, 20)) as pilot:
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("?")
            await pilot.pause()
            body = str(app.screen.query_one("#help_body").render())
            self.assertIn("re-check", body)
            self.assertNotIn("commands", body)      # that key lives on Review
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("tab")
            await pilot.pause()
            await pilot.press("?")
            await pilot.pause()
            body = str(app.screen.query_one("#help_body").render())
            self.assertIn("toggle", body)
            self.assertIn("move", body)

    async def test_a_config_override_changes_the_footer_and_the_key(self) -> None:
        keymap.apply_overrides({"wizard.previous": "b"})
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(foot(app),
                             "↑/↓ select  ⏎ next  r re-check  b back  q quit  ? help")
            await pilot.press("b")
            await pilot.pause()
            self.assertIsInstance(app.screen, WelcomeScreen)

    # -- options focus model ----------------------------------------------
    async def test_enter_advances_and_space_toggles(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("enter")       # Checks
            await pilot.press("enter")       # Options
            await pilot.pause()
            self.assertIsInstance(app.screen, OptionsScreen)
            self.assertFalse(app.opts.app_set)
            await pilot.press("tab")         # first app row
            await pilot.pause()
            self.assertTrue(app.focused.id.startswith("app_"))
            await pilot.press("space")
            await pilot.pause()
            self.assertTrue(app.opts.app_set)          # space toggled it
            await pilot.press("enter")                 # Enter is the page's
            await pilot.pause()
            self.assertIsInstance(app.screen, ReviewScreen)
            self.assertTrue(app.opts.app_set)          # and toggled nothing

    async def test_tab_moves_between_groups_and_arrows_within(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("enter")
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app.focused.id, "sources")
            await pilot.press("tab")
            await pilot.pause()
            first = app.focused.id
            self.assertTrue(first.startswith("app_"), first)
            await pilot.press("down")
            await pilot.pause()
            self.assertNotEqual(app.focused.id, first)
            self.assertTrue(app.focused.id.startswith("app_"))
            await pilot.press("tab")
            await pilot.pause()
            self.assertIn(app.focused.id, ("lockscreen", "spatial", "start"))

    # -- review failure ----------------------------------------------------
    async def test_a_failed_review_swaps_the_keys_and_explains(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            app.prepare_error = ("fatal: unable to access 'https://example.invalid/': "
                                 "Could not resolve host: example.invalid")
            app.push_screen(ReviewScreen(Strings("en")))
            await pilot.pause()
            self.assertEqual(foot(app), FOOTERS["review_failed"])
            status = str(app.screen.query_one("#status").render())
            self.assertIn("git clone", status)
            self.assertIn("[r] retry", status)
            self.assertIn(Strings("en")("advice_network"), status)
            self.assertIn("Could not resolve host", status)
            await pilot.press("l")
            await pilot.pause()
            self.assertIsInstance(app.screen, LogViewerScreen)

    def test_the_common_causes_have_one_line_of_advice(self) -> None:
        self.assertEqual(advice_for("Could not resolve host: github.com"), "advice_network")
        self.assertEqual(advice_for("https://x has no ref v9.9.9"), "advice_tag")
        self.assertEqual(advice_for("Permission denied (publickey)"), "advice_credentials")
        self.assertEqual(advice_for("exit status 1"), "")

    # -- management menu ---------------------------------------------------
    def manage_app(self, units=UNITS, snapshots=SNAPSHOTS, logs=(Path("/tmp/x.log"),)):
        patchers = [
            mock.patch("installer.manage.units", return_value=list(units)),
            mock.patch("installer.manage.snapshots", return_value=list(snapshots)),
            mock.patch("installer.manage.logs", return_value=list(logs)),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        return self.make_app()

    async def test_management_menu_footer_and_disabled_slot(self) -> None:
        app = self.manage_app(units=[], snapshots=[], logs=())
        async with app.run_test(size=(66, 20)) as pilot:
            await pilot.press("ctrl+p")
            await self.wait_for(pilot, lambda: isinstance(app.screen, ManagementScreen)
                                and app.screen.query_one("#manage_list",
                                                         OptionList).option_count == 6)
            self.assertEqual(foot(app), FOOTERS["management"])
            rows = [str(option.prompt) for option in
                    app.screen.query_one("#manage_list", OptionList).options]
            self.assertEqual([row[:4] for row in rows],
                             ["[1] ", "[2] ", "[3] ", "[4] ", "[5] ", "[6] "])
            self.assertIn("unavailable: nothing installed", rows[4])
            self.assertIn("unavailable: no logs", rows[3])

            await pilot.press("5")             # disabled: its slot is kept, nothing runs
            await pilot.pause()
            self.assertIsInstance(app.screen, ManagementScreen)

            await pilot.press("6")             # back
            await pilot.pause()
            self.assertIsInstance(app.screen, WelcomeScreen)

    async def test_management_opens_children_and_their_footers(self) -> None:
        app = self.manage_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("ctrl+p")
            await self.wait_for(pilot, lambda: isinstance(app.screen, ManagementScreen)
                                and app.screen.query_one("#manage_list",
                                                         OptionList).option_count == 6)
            await pilot.press("1")
            await self.wait_for(pilot, lambda: isinstance(app.screen, UnitsScreen)
                                and app.screen.query_one("#manage_list",
                                                         OptionList).option_count == 2)
            self.assertEqual(foot(app), FOOTERS["units"])

            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("2")
            await self.wait_for(pilot, lambda: isinstance(app.screen, SnapshotsScreen)
                                and app.screen.query_one("#manage_list",
                                                         OptionList).option_count == 1)
            self.assertEqual(foot(app), FOOTERS["snapshots"])

            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("4")
            await self.wait_for(pilot, lambda: isinstance(app.screen, LogsScreen)
                                and app.screen.query_one("#manage_list",
                                                         OptionList).option_count == 1)
            self.assertEqual(foot(app), FOOTERS["logs"])
            await pilot.press("enter")
            await self.wait_for(pilot, lambda: isinstance(app.screen, LogViewerScreen))
            self.assertEqual(foot(app), FOOTERS["log_view"])

    async def test_uninstall_keeps_the_typed_word(self) -> None:
        app = self.manage_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("ctrl+p")
            await self.wait_for(pilot, lambda: isinstance(app.screen, ManagementScreen)
                                and app.screen.query_one("#manage_list",
                                                         OptionList).option_count == 6)
            await pilot.press("5")
            await pilot.pause()
            self.assertIsInstance(app.screen, ConfirmDialog)
            self.assertTrue(app.screen.query_one("#confirm_ok", Button).disabled)

    # -- dangerous things ask first ---------------------------------------
    async def test_ctrl_c_asks_and_the_safe_choice_keeps_running(self) -> None:
        app = self.make_app(mode="cancel")
        async with app.run_test(size=(100, 30)) as pilot:
            await self.start_install(pilot)
            await self.wait_for(pilot, lambda: isinstance(app.screen, InstallationScreen))
            # Nothing is focused: a stray Enter cannot press "cancel".
            self.assertIsNone(pilot.app.focused)
            await pilot.press("enter")
            await pilot.pause()
            self.assertIsInstance(app.screen, InstallationScreen)
            self.assertFalse(app.cancel_event.is_set())
            await pilot.press("ctrl+c")
            await self.wait_for(pilot, lambda: isinstance(app.screen, ConfirmDialog)
                                and bool(app.screen.query("#confirm_ok")))
            dialog = app.screen
            self.assertIn(Strings("en")("abort_keep"),
                          str(dialog.query_one("#confirm_cancel", Button).label))
            self.assertIn(Strings("en")("abort_confirm"),
                          str(dialog.query_one("#confirm_ok", Button).label))
            await pilot.press("enter")          # focused "keep running"
            await pilot.pause()
            self.assertIsInstance(app.screen, InstallationScreen)
            self.assertFalse(app.cancel_event.is_set())

            await pilot.press("ctrl+c")
            await self.wait_for(pilot, lambda: isinstance(app.screen, ConfirmDialog)
                                and bool(app.screen.query("#confirm_ok")))
            await pilot.click("#confirm_ok")
            await self.wait_for(pilot, lambda: app.cancel_event.is_set())
