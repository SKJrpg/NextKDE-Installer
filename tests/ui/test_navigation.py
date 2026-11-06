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
    from rich.cells import cell_len
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
    from installer.ui.screens.options import OptionsScreen, SourceRow
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
    "welcome": "Tab next  ←/→ language  ctrl+p commands  ctrl+k help",
    "checks": "↑/↓ select  Tab next  ctrl+r re-check  Shift+Tab back  "
              "ctrl+p commands  ctrl+k help",
    "options_source": "↑/↓ select  ⏎ options below  Tab next  Shift+Tab back  "
                      "ctrl+p commands  ctrl+k help",
    "options_check": "↑/↓ move  ⏎ confirm  space toggle  Tab next  "
                     "Shift+Tab back  ctrl+p commands  ctrl+k help",
    "review": "⏎ continue  ↑/↓ scroll  Tab next  ctrl+e details  Shift+Tab back  "
              "ctrl+p commands  ctrl+k help",
    "review_failed": "↑/↓ scroll  g/G first/last  ctrl+r retry  ctrl+l log  "
                     "Shift+Tab back  ctrl+p commands  ctrl+k help",
    "confirm": "y confirm  n cancel  ctrl+k help",
    "installation": "ctrl+z abort  ctrl+k help",
    "result_ok": "q Quit  ctrl+l log  ctrl+p commands  ctrl+k help",
    "result_failed": "ctrl+r retry  q Quit  ctrl+l log  ctrl+p commands  ctrl+k help",
    "management": "1–6 go to  ↑/↓ select  g/G first/last  ⏎ open  esc back  "
                  "ctrl+p commands  ctrl+k help",
    "units": "↑/↓ select  g/G first/last  ⏎ toggle  esc back  "
             "ctrl+p commands  ctrl+k help",
    "snapshots": "↑/↓ select  g/G first/last  ⏎ roll back  ctrl+n create  "
                 "esc back  ctrl+p commands  ctrl+k help",
    "logs": "↑/↓ select  g/G first/last  ⏎ open  esc back  "
            "ctrl+p commands  ctrl+k help",
    "log_view": "↑/↓ scroll  ctrl+u/d page  g/G first/last  esc back  "
                "ctrl+p commands  ctrl+k help",
}

# At 66 columns the fit drops the secondary hints first; help always stays.
FOOTERS_NARROW = {
    "welcome": "Tab next  ←/→ language  ctrl+p commands  ctrl+k help",
    "checks": "↑/↓ select  Tab next  Shift+Tab back  ctrl+k help",
    "options_source": "⏎ options below  Tab next  Shift+Tab back  ctrl+k help",
    "options_check": "⏎ confirm  space toggle  Tab next  Shift+Tab back  ctrl+k help",
    "review": "⏎ continue  Tab next  Shift+Tab back  ctrl+k help",
    "review_failed": "ctrl+r retry  Shift+Tab back  ctrl+k help",
    "confirm": "y confirm  n cancel  ctrl+k help",
    "installation": "ctrl+z abort  ctrl+k help",
    "result_ok": "q Quit  ctrl+l log  ctrl+p commands  ctrl+k help",
    "result_failed": "ctrl+r retry  q Quit  ctrl+l log  ctrl+p commands  ctrl+k help",
    "management": "1–6 go to  ↑/↓ select  ⏎ open  esc back  ctrl+k help",
    "units": "↑/↓ select  g/G first/last  ⏎ toggle  esc back  ctrl+k help",
    "snapshots": "↑/↓ select  ⏎ roll back  ctrl+n create  esc back  ctrl+k help",
    "logs": "↑/↓ select  g/G first/last  ⏎ open  esc back  ctrl+k help",
    "log_view": "↑/↓ scroll  ctrl+u/d page  g/G first/last  esc back  ctrl+k help",
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
            cancel.wait(60)
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
            await pilot.press("tab")
            await pilot.pause()

    async def to_confirm(self, pilot) -> None:
        await self.to_review(pilot)
        await pilot.press("enter")
        await pilot.pause()

    async def start_install(self, pilot) -> None:
        await self.to_confirm(pilot)
        await pilot.press("y")
        await pilot.pause()

    # -- footers: whole line, at both sizes ------------------------------
    async def test_wizard_footers_are_whole_lines_at_both_sizes(self) -> None:
        for size, table in (((100, 30), FOOTERS), ((66, 20), FOOTERS_NARROW)):
            with self.subTest(size=size):
                app = self.make_app()
                async with app.run_test(size=size) as pilot:
                    await pilot.pause()
                    self.assertEqual(foot(app), table["welcome"])
                    await pilot.press("enter")     # no page on Enter now
                    await pilot.pause()
                    self.assertEqual(foot(app), table["welcome"])
                    await pilot.press("tab")
                    await pilot.pause()
                    self.assertEqual(foot(app), table["checks"])
                    await pilot.press("tab")
                    await pilot.pause()
                    self.assertEqual(foot(app), table["options_source"])
                    await pilot.press("enter")     # down into the options below
                    await pilot.pause()
                    self.assertEqual(foot(app), table["options_check"])
                    self.assertLessEqual(cell_len(foot(app)), size[0])
                    await pilot.press("tab")
                    await pilot.pause()
                    self.assertEqual(foot(app), table["review"])
                    await pilot.press("enter")
                    await pilot.pause()
                    self.assertEqual(foot(app), table["confirm"])
                    self.assertLessEqual(cell_len(foot(app)), size[0])

    async def test_installation_and_result_footers(self) -> None:
        app = self.make_app(mode="cancel")
        async with app.run_test(size=(66, 20)) as pilot:
            await self.start_install(pilot)
            await self.wait_for(pilot, lambda: isinstance(app.screen, InstallationScreen))
            self.assertEqual(foot(app), FOOTERS_NARROW["installation"])
            await pilot.press("ctrl+k")     # the guard has no row to offer
            await pilot.pause()
            keys = [key for key, _text in app.screen.rows]
            self.assertIn("ctrl+z", keys)
            self.assertNotIn("ctrl+c", keys)
            self.assertTrue(all(text for _key, text in app.screen.rows))
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("ctrl+z")
            await self.wait_for(pilot, lambda: isinstance(app.screen, ResultScreen))
            self.assertEqual(foot(app), FOOTERS_NARROW["result_failed"])

        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            app.push_screen(ResultScreen(Strings("en"), "ok"))
            await pilot.pause()
            self.assertEqual(foot(app), FOOTERS["result_ok"])

    async def test_q_quits_from_the_result_page(self) -> None:
        app = self.make_app()
        seen = []
        async with app.run_test(size=(100, 30)) as pilot:
            app.push_screen(ResultScreen(Strings("en"), "ok"), callback=seen.append)
            await pilot.pause()
            self.assertIn("q Quit", foot(app))
            await pilot.press("q")
            await pilot.pause()
            self.assertEqual(seen, ["quit"])
            self.assertNotIsInstance(app.screen, ResultScreen)

    # -- the confirmation page: Y or N, nothing else ----------------------
    async def test_confirm_is_inert_until_y_or_n(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_confirm(pilot)
            screen = app.screen
            self.assertIsInstance(screen, ConfirmScreen)
            for key in ("enter", "tab", "1", "2", "up", "down", "h", "l", "j", "k"):
                await pilot.press(key)
                await pilot.pause()
                self.assertIs(app.screen, screen, key)
                self.assertTrue(all(not isinstance(s, InstallationScreen)
                                    for s in app._screen_stack), key)

            await pilot.press("n")
            await pilot.pause()
            self.assertIsInstance(app.screen, ReviewScreen)

    async def test_y_installs_and_n_goes_back(self) -> None:
        app = self.make_app(mode="cancel")
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_confirm(pilot)
            await pilot.press("N")
            await pilot.pause()
            self.assertIsInstance(app.screen, ReviewScreen)
            self.assertTrue(all(not isinstance(s, InstallationScreen)
                                for s in app._screen_stack))

            await pilot.press("enter")        # Review -> Confirm again
            await pilot.pause()
            self.assertIsInstance(app.screen, ConfirmScreen)
            await pilot.press("Y")
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

    async def test_abort_is_immediate_on_the_run_page(self) -> None:
        app = self.make_app(mode="cancel")
        async with app.run_test(size=(100, 30)) as pilot:
            await self.start_install(pilot)
            await self.wait_for(pilot, lambda: isinstance(app.screen, InstallationScreen))
            await pilot.press("ctrl+z")
            self.assertTrue(app.cancel_event.is_set())      # no question in between
            await self.wait_for(pilot, lambda: isinstance(app.screen, ResultScreen))
            self.assertEqual(app.exit_code, 130)
            self.assertIn("cancelled",
                          str(app.screen.query_one("#result_text").render()).lower())

    async def test_ctrl_c_does_nothing_while_a_run_owns_it(self) -> None:
        app = self.make_app(mode="cancel")
        async with app.run_test(size=(100, 30), notifications=True) as pilot:
            await self.start_install(pilot)
            await self.wait_for(pilot, lambda: isinstance(app.screen, InstallationScreen))
            await pilot.press("ctrl+c")
            await pilot.press("ctrl+c")
            await pilot.pause()
            self.assertFalse(app._exit)                      # no quit gesture
            self.assertFalse(app.cancel_event.is_set())      # and no abort either
            self.assertIsInstance(app.screen, InstallationScreen)

    async def test_ctrl_c_twice_quits_from_the_wizard(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30), notifications=True) as pilot:
            await pilot.press("tab")
            await pilot.pause()
            self.assertIsInstance(app.screen, SystemScreen)
            await pilot.press("ctrl+c")
            await pilot.pause()
            self.assertIsInstance(app.screen, SystemScreen)   # still here
            self.assertIn(Strings("en")("ctrl_c_hint"),
                          [note.message for note in app._notifications])
            await pilot.press("ctrl+c")
            await pilot.pause()
            self.assertTrue(app._exit)

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

    async def test_a_modal_question_suppresses_the_quit_gesture(self) -> None:
        app = self.manage_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.open_management(pilot, app)
            await pilot.press("5")              # uninstall asks for a typed word
            await pilot.pause()
            self.assertIsInstance(app.screen, ConfirmDialog)
            await pilot.press("ctrl+c")
            await pilot.press("ctrl+c")
            await pilot.pause()
            self.assertFalse(app._exit)          # no bypass
            self.assertIsInstance(app.screen, ConfirmDialog)

    async def test_help_overlay_does_not_arm_the_quit_gesture(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("tab")
            await pilot.pause()
            await pilot.press("ctrl+k")
            await pilot.pause()
            self.assertIsInstance(app.screen, HelpScreen)
            await pilot.press("ctrl+c")          # closes the overlay, as any key does
            await pilot.pause()
            self.assertIsInstance(app.screen, SystemScreen)
            self.assertFalse(app._exit)          # and did not arm a quit
            await pilot.press("ctrl+c")
            await pilot.pause()
            self.assertIsInstance(app.screen, SystemScreen)
            self.assertFalse(app._exit)

    # -- help overlay ------------------------------------------------------
    async def test_help_is_ctrl_k_and_question_mark_still_works(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("tab")
            await pilot.pause()
            self.assertIn("ctrl+k help", foot(app))
            self.assertNotIn("? help", foot(app))
            await pilot.press("?")            # the hidden alias
            await pilot.pause()
            self.assertIsInstance(app.screen, HelpScreen)
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("ctrl+k")       # and the advertised key
            await pilot.pause()
            self.assertIsInstance(app.screen, HelpScreen)

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
                await pilot.press("tab")
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
            await pilot.press("tab")
            await pilot.pause()
            await pilot.press("?")
            await pilot.pause()
            body = str(app.screen.query_one("#help_body").render())
            self.assertIn("re-check", body)
            self.assertIn("j/k", body)             # the Vim aliases are listed
            self.assertNotIn("ctrl+e", body)        # details live on Review
            self.assertIn("ctrl+p", body)           # the command menu is here
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("tab")               # Options
            await pilot.pause()
            await pilot.press("enter")             # down to the first app row
            await pilot.pause()
            self.assertTrue(app.focused.id.startswith("app_"))
            await pilot.press("?")
            await pilot.pause()
            body = str(app.screen.query_one("#help_body").render())
            self.assertIn("toggle", body)
            self.assertIn("move", body)
            self.assertIn("confirm", body)

    async def test_a_config_override_changes_the_footer_and_the_key(self) -> None:
        keymap.apply_overrides({"wizard.previous": "b"})
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("tab")
            await pilot.pause()
            self.assertEqual(foot(app),
                             "↑/↓ select  Tab next  ctrl+r re-check  b back  "
                             "ctrl+p commands  ctrl+k help")
            await pilot.press("b")
            await pilot.pause()
            self.assertIsInstance(app.screen, WelcomeScreen)

    # -- Vim navigation ----------------------------------------------------
    async def test_vim_keys_move_checks_and_the_source_choice(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("tab")            # Checks
            await pilot.pause()
            self.assertEqual(app.screen.row, 0)
            await pilot.press("j")
            await pilot.pause()
            self.assertEqual(app.screen.row, 1)
            await pilot.press("j")              # past the last -> first
            await pilot.pause()
            self.assertEqual(app.screen.row, 0)
            await pilot.press("k")              # before the first -> last
            await pilot.pause()
            self.assertEqual(app.screen.row, 1)
            await pilot.press("k")
            await pilot.pause()
            self.assertEqual(app.screen.row, 0)
            await pilot.press("tab")            # Options
            await pilot.pause()
            self.assertEqual(app.opts.source, "stable")
            await pilot.press("j")
            await pilot.pause()
            self.assertEqual(app.opts.source, "main")
            await pilot.press("space")          # no longer a selection key
            await pilot.pause()
            self.assertEqual(app.opts.source, "main")
            await pilot.press("k")
            await pilot.pause()
            self.assertEqual(app.opts.source, "stable")

    async def test_vim_keys_scroll_the_review_page(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 20)) as pilot:
            await self.to_review(pilot)
            view = app.screen.query_one("#review")
            self.assertGreater(view.max_scroll_y, 0)
            await pilot.press("j")
            await pilot.pause()
            self.assertEqual(view.scroll_y, 1)
            await pilot.press("k")
            await pilot.pause()
            self.assertEqual(view.scroll_y, 0)
            await pilot.press("G")
            await pilot.pause()
            self.assertEqual(view.scroll_y, view.max_scroll_y)
            await pilot.press("g")
            await pilot.pause()
            self.assertEqual(view.scroll_y, 0)

    async def test_vim_keys_in_the_menu_and_the_log(self) -> None:
        app = self.manage_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.open_management(pilot, app)
            listing = app.screen.query_one("#manage_list", OptionList)
            await pilot.press("j")
            await pilot.pause()
            self.assertEqual(listing.highlighted, 1)
            await pilot.press("G")
            await pilot.pause()
            self.assertEqual(listing.highlighted, 5)
            await pilot.press("g")
            await pilot.pause()
            self.assertEqual(listing.highlighted, 0)

            log = app.paths.log_dir / "vim.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text("\n".join(f"line {n}" for n in range(80)), encoding="utf-8")
            self.addCleanup(log.unlink, missing_ok=True)
            app.push_screen(LogViewerScreen(Strings("en"), log))
            await self.wait_for(pilot, lambda: isinstance(app.screen, LogViewerScreen)
                                and bool(app.screen.query_one("#log_view").lines))
            view = app.screen.query_one("#log_view")
            await pilot.press("G")
            await pilot.pause()
            self.assertGreater(view.scroll_y, 0)
            await pilot.press("g")
            await pilot.pause()
            self.assertEqual(view.scroll_y, 0)
            await pilot.press("ctrl+d")
            await pilot.pause()
            self.assertGreater(view.scroll_y, 0)
            await pilot.press("ctrl+u")
            await pilot.pause()
            self.assertEqual(view.scroll_y, 0)

    # -- page keys: Tab pages, Enter activates ------------------------------
    async def test_tab_pages_and_enter_does_not(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            self.assertIsInstance(app.screen, WelcomeScreen)
            await pilot.press("enter")           # no page on Enter here
            await pilot.pause()
            self.assertIsInstance(app.screen, WelcomeScreen)
            await pilot.press("tab")
            await pilot.pause()
            self.assertIsInstance(app.screen, SystemScreen)
            await pilot.press("enter")
            await pilot.pause()
            self.assertIsInstance(app.screen, SystemScreen)
            await pilot.press("tab")
            await pilot.pause()
            self.assertIsInstance(app.screen, OptionsScreen)
            await pilot.press("enter")           # activates a row, does not page
            await pilot.pause()
            self.assertIsInstance(app.screen, OptionsScreen)
            await pilot.press("tab")
            await pilot.pause()
            self.assertIsInstance(app.screen, ReviewScreen)
            await pilot.press("shift+tab")
            await pilot.pause()
            self.assertIsInstance(app.screen, OptionsScreen)

    async def test_shift_tab_and_escape_both_leave_the_confirm_page(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await self.to_confirm(pilot)
            await pilot.press("shift+tab")
            await pilot.pause()
            self.assertIsInstance(app.screen, ReviewScreen)
            await pilot.press("enter")
            await pilot.pause()
            self.assertIsInstance(app.screen, ConfirmScreen)
            await pilot.press("escape")
            await pilot.pause()
            self.assertIsInstance(app.screen, ReviewScreen)

    # -- options: the source block, then the options below ------------------
    async def test_options_source_block_does_not_cross_down(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("tab")             # Checks
            await pilot.press("tab")             # Options
            await pilot.pause()
            self.assertIsInstance(app.screen, OptionsScreen)
            self.assertEqual(app.focused.id, "source_stable")
            await pilot.press("down")
            await pilot.pause()
            self.assertEqual(app.focused.id, "source_main")
            self.assertEqual(app.opts.source, "main")      # moving selects it
            await pilot.press("down")
            await pilot.pause()
            self.assertEqual(app.focused.id, "source_local")
            await pilot.press("down")                      # stays in the block
            await pilot.pause()
            self.assertEqual(app.focused.id, "source_local")
            await pilot.press("up")
            await pilot.pause()
            self.assertEqual(app.focused.id, "source_main")
            self.assertEqual(app.opts.source, "main")

    async def test_enter_on_a_source_steps_down_and_up_returns(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("tab")
            await pilot.press("tab")
            await pilot.pause()
            await pilot.press("down")            # main
            await pilot.pause()
            await pilot.press("enter")           # down into the options
            await pilot.pause()
            first_lower = app.focused.id
            self.assertTrue(first_lower.startswith("app_"), first_lower)
            self.assertEqual(app.opts.source, "main")
            await pilot.press("enter")           # Enter toggles that checkbox
            await pilot.pause()
            self.assertIn(first_lower.removeprefix("app_"), app.opts.app_set)
            await pilot.press("up")              # first lower row leads back up
            await pilot.pause()
            self.assertEqual(app.focused.id, "source_main")
            self.assertIsInstance(app.focused, SourceRow)

    async def test_options_space_toggles_checkboxes_only(self) -> None:
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("tab")
            await pilot.press("tab")
            await pilot.pause()
            await pilot.press("space")           # on a source row: nothing
            await pilot.pause()
            self.assertEqual(app.opts.source, "stable")
            await pilot.press("enter")           # step down into the options
            await pilot.pause()
            self.assertTrue(app.focused.id.startswith("app_"))
            await pilot.press("space")           # on a checkbox: toggles
            await pilot.pause()
            self.assertTrue(app.opts.app_set)

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
            self.assertIn("[Ctrl+R] retry", status)
            self.assertIn(Strings("en")("advice_network"), status)
            self.assertIn("Could not resolve host", status)
            await pilot.press("ctrl+l")
            await pilot.pause()
            self.assertIsInstance(app.screen, LogViewerScreen)

    def test_the_common_causes_have_one_line_of_advice(self) -> None:
        self.assertEqual(advice_for("Could not resolve host: github.com"), "advice_network")
        self.assertEqual(advice_for("https://x has no ref v9.9.9"), "advice_tag")
        self.assertEqual(advice_for("Permission denied (publickey)"), "advice_credentials")
        self.assertEqual(advice_for("exit status 1"), "")

    # -- management menu ---------------------------------------------------
    def manage_app(self, units=UNITS, snapshots=SNAPSHOTS, logs=(Path("/tmp/x.log"),),
                   session_mode: str = "ok"):
        patchers = [
            mock.patch("installer.manage.units", return_value=list(units)),
            mock.patch("installer.manage.snapshots", return_value=list(snapshots)),
            mock.patch("installer.manage.logs", return_value=list(logs)),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.sessions: list[FakeSession] = []

        def factory(steps, log, root):
            session = FakeSession(steps, log, root, session_mode)
            self.sessions.append(session)
            return session

        return KosApp(lang="en", system=fake_system(),
                      paths=Paths.resolve(source_root=ROOT),
                      prepare=fake_prepare, session_factory=factory)

    async def open_management(self, pilot, app) -> None:
        """Open management directly; Ctrl+P is Textual's palette now."""
        app.screen._open_management()
        await self.wait_for(pilot, lambda: isinstance(app.screen, ManagementScreen)
                            and app.screen.query_one("#manage_list",
                                                     OptionList).option_count == 6)

    async def test_management_menu_footer_and_disabled_slot(self) -> None:
        app = self.manage_app(units=[], snapshots=[], logs=())
        async with app.run_test(size=(66, 20)) as pilot:
            await self.open_management(pilot, app)
            self.assertEqual(foot(app), FOOTERS_NARROW["management"])
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
            await self.open_management(pilot, app)
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
            await self.open_management(pilot, app)
            await pilot.press("5")
            await pilot.pause()
            self.assertIsInstance(app.screen, ConfirmDialog)
            self.assertTrue(app.screen.query_one("#confirm_ok", Button).disabled)

    # -- abort is immediate; Ctrl+C belongs to the quit gesture elsewhere --
    async def test_abort_on_a_busy_menu_stops_the_action(self) -> None:
        app = self.manage_app(session_mode="cancel")
        async with app.run_test(size=(100, 30)) as pilot:
            await self.open_management(pilot, app)
            await pilot.press("1")
            await self.wait_for(pilot, lambda: isinstance(app.screen, UnitsScreen)
                                and app.screen.query_one("#manage_list",
                                                         OptionList).option_count == 2)
            await pilot.press("down")
            await pilot.press("space")
            await self.wait_for(pilot, lambda: app.screen.busy)
            self.assertIn("ctrl+z abort", foot(app))
            await pilot.press("ctrl+c")           # swallowed: neither quit nor abort
            await pilot.pause()
            self.assertFalse(app._exit)
            self.assertTrue(app.screen.busy)
            await pilot.press("ctrl+z")
            await self.wait_for(pilot, lambda: not app.screen.busy)
            self.assertEqual(self.sessions[0].result, "cancelled")
