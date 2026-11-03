"""Management screens plus the wizard's layout, rendering and footer wiring.

No terminal is initialised and no kosctl/state command runs: `_run_action` is
replaced, and every screen is drawn into :class:`FakeWin`, a text grid that
records each written cell. That is what lets the layout tests below check for
overlaps, clipping and empty panes without a real terminal or a third-party
rendering library.
"""

from __future__ import annotations

import curses
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from installer import manage  # noqa: E402
from installer.detect import OsInfo, Probe, System  # noqa: E402
from installer.paths import Paths  # noqa: E402
from installer.plan import Step  # noqa: E402
from installer.render import curses_ui, plain  # noqa: E402
from installer.render import layout as layout_mod  # noqa: E402
from installer.render.curses_ui import UI  # noqa: E402
from installer.render.theme import ASCII, UNICODE, Theme, supports_unicode  # noqa: E402
from installer.render.widgets import _clip, _printable, _width, _wrap  # noqa: E402
from installer.strings import Strings  # noqa: E402


class FakeWin:
    """A curses window made of characters, with cell ownership tracking."""

    def __init__(self, height: int, width: int) -> None:
        self.h, self.w = height, width
        self.cells = [[" "] * width for _ in range(height)]
        self.attrs = [[0] * width for _ in range(height)]
        self.overlaps: list[tuple[int, int, str, str]] = []
        self.escapes: list[tuple[int, int]] = []

    # -- curses surface -------------------------------------------------
    def getmaxyx(self):
        return self.h, self.w

    def erase(self):
        self.cells = [[" "] * self.w for _ in range(self.h)]
        self.attrs = [[0] * self.w for _ in range(self.h)]

    def clearok(self, flag):
        pass

    def nodelay(self, flag):
        pass

    def keypad(self, flag):
        pass

    def noutrefresh(self):
        pass

    def doupdate(self):
        pass

    def getch(self):
        return -1

    def _write(self, y, x, char, count, attr=0):
        if not (0 <= y < self.h) or not (0 <= x < self.w):
            self.escapes.append((y, x))
            raise curses.error("out of bounds")
        col = x
        for _ in range(count):
            for index in range(max(1, _width(char))):
                if col + index >= self.w:
                    self.escapes.append((y, col))
                    raise curses.error("clip")
                old = self.cells[y][col + index]
                new = char if index == 0 else ""
                if old != " " and old != new:
                    self.overlaps.append((y, col, old, new))
                self.cells[y][col + index] = new
                self.attrs[y][col + index] = attr
            col += max(1, _width(char))

    def addnstr(self, y, x, text, n, attr=0):
        if not (0 <= y < self.h) or not (0 <= x < self.w):
            self.escapes.append((y, x))
            raise curses.error("position")
        col = x
        for char in text[:n]:
            if col + _width(char) > self.w:
                self.escapes.append((y, col))
                raise curses.error("clip")
            old = self.cells[y][col]
            if old != " " and old != char:
                self.overlaps.append((y, col, old, char))
            self.cells[y][col] = char
            self.attrs[y][col] = attr
            if _width(char) == 2:
                self.cells[y][col + 1] = ""
                self.attrs[y][col + 1] = attr
            col += _width(char)

    def hline(self, y, x, char, n):
        self._write(y, x, char if isinstance(char, str) else "-", n)

    def vline(self, y, x, char, n):
        char = char if isinstance(char, str) else "|"
        for offset in range(n):
            self._write(y + offset, x, char, 1)

    # -- inspection -----------------------------------------------------
    def text(self) -> list[str]:
        return ["".join(row).rstrip() for row in self.cells]

    def region_text(self, x: int, width: int) -> str:
        return "".join("".join(row[x:x + width]) for row in self.cells).strip()


def make_paths(root: Path = Path("/repo"), state: Path = Path("/state")) -> Paths:
    return Paths(installer_root=HERE, source_root=Path(root),
                 build_root=Path("/cache/build"), state_root=Path(state))


def make_system(blocked: bool = False, probes: list[Probe] | None = None) -> System:
    return System(os=OsInfo(id="arch", version="", like=(), pretty="Arch Linux"),
                  family="arch", method="kosctl", arch="x86_64",
                  probes=probes if probes is not None else [], blocked=blocked)


def make_ui(blocked: bool = False, lang: str = "en", probes: list[Probe] | None = None,
            ascii_glyphs: bool = False) -> UI:
    empty = manage.Deps(family="arch", packages=[])
    with tempfile.TemporaryDirectory() as directory, \
            mock.patch.object(curses_ui, "latest_release", return_value="v0.1.1"), \
            mock.patch.object(manage, "deps_from_docs", return_value=empty), \
            mock.patch.object(manage, "deps", return_value=empty):
        ui = UI(make_system(blocked, probes), make_paths(state=Path(directory)),
                Strings(lang))
    if ascii_glyphs:
        ui.theme = Theme(ASCII, color=False)
    return ui


PROBES = [
    Probe("probe_os", "PASS", "Arch Linux"),
    Probe("probe_arch", "PASS", "x86_64"),
    Probe("probe_session", "PASS", "wayland (KDE)"),
    Probe("probe_kwin", "PASS", "kwin 6.8.2"),
    Probe("probe_quickshell", "WARN", "not found", "The install step can provide it."),
    Probe("probe_sudo", "WARN", "password required", "Prime sudo with `sudo -v`."),
    Probe("probe_packages", "FAIL", "2 missing: kf6-calendarcore, pkgconf",
          "kosctl install adds these with the package manager."),
]


def fill(ui: UI) -> UI:
    """Give every screen something real to draw."""
    ui.steps = [
        Step("source", "kosctl update (skipped)", [], note="skipped_source"),
        Step("core", "kosctl install", [str(Path("/repo") / "tools" / "kosctl"), "install"]),
        Step("apps", "kosctl install apps", [str(Path("/repo") / "tools" / "kosctl"),
                                            "install", "apps", "--only", "calendar"]),
        Step("start", "kosctl start", [str(Path("/repo") / "tools" / "kosctl"), "start"]),
    ]
    ui.step_index = 1
    ui.current = ui.steps[1]
    ui.phase = "build"
    ui.current_progress = 0.42
    ui.log_lines = [("INFO", "=== build ==="), ("OK", "link done"),
                    ("WARN", "deprecated option"), ("ERROR", "ninja: build stopped")]
    ui.units = [manage.Unit("core", "0.1.1", "files", 42, "2026-11-01T10:00:00"),
                manage.Unit("apps", "0.1.1", "files", 8, "")]
    ui.snapshots = [manage.Snapshot("20261103-101010", "2026-11-03 10:10",
                                    "before update", "~/.config/kos")]
    ui.log_text = ["line one", "line two", "line three"]
    ui.log_text_path = Path("/repo/install.log")
    ui.action_title = "kosctl doctor"
    ui.action_state = "done"
    ui.result = "ok"
    ui.result_units = ui.units
    ui.install_started = 0.0
    return ui


SCREEN_NAMES = ("welcome", "system", "options", "review", "install", "result",
                "manage", "units", "snapshots", "action", "log")


def render(ui: UI, name: str, height: int, width: int) -> FakeWin:
    ui.screen = {"welcome": UI.WELCOME, "system": UI.SYSTEM, "options": UI.OPTIONS,
                 "review": UI.REVIEW, "install": UI.INSTALL, "result": UI.RESULT,
                 "manage": UI.MANAGE, "units": UI.UNITS, "snapshots": UI.SNAPSHOTS,
                 "action": UI.ACTION, "log": UI.LOG}[name]
    win = FakeWin(height, width)
    with mock.patch.object(curses, "doupdate"):
        ui._draw(win)
    return win


class StringsTest(unittest.TestCase):
    """The UI composes keys at runtime; a missing one would print as garbage."""

    def test_dynamic_keys_all_resolve(self) -> None:
        from installer.detect import METHODS
        from installer.plan import ALL_APPS

        keys = [f"why_probe_{name}" for name in (
            "os", "arch", "session", "plasma", "kwin", "quickshell", "disk",
            "git", "python", "sudo", "manager", "packages")]
        keys += ["status_pass", "status_warn", "status_fail"]
        keys += [f"app_{name}" for name in ALL_APPS]
        keys += ["source_stable", "source_main", "source_local",
                 "source_stable_note", "source_main_note", "source_local_note"]
        keys += ["detail_source", "detail_core", "detail_apps",
                 "detail_lockscreen", "detail_spatial", "detail_start"]
        keys += ["stage_done", "stage_running", "stage_failed", "stage_skipped",
                 "stage_waiting"]
        keys += ["step_welcome", "step_system", "step_options", "step_review",
                 "step_install"]
        keys += [f"method_{method}" for method in (*METHODS.values(), "unknown")]
        for lang in ("zh", "en"):
            strings = Strings(lang)
            for key in keys:
                with self.subTest(lang=lang, key=key):
                    self.assertNotEqual(strings(key), key, "missing translation")

    def test_both_languages_cover_the_same_keys(self) -> None:
        from installer.strings import _TEXT

        for key, pair in _TEXT.items():
            with self.subTest(key=key):
                self.assertIsInstance(pair, tuple)
                self.assertEqual(len(pair), 2)
                self.assertTrue(pair[0] and pair[1], "an empty translation")


class ConfirmationTest(unittest.TestCase):
    def test_declining_uninstall_changes_nothing(self) -> None:
        ui = make_ui()
        ui.confirm, ui.confirm_action = "uninstall?", "uninstall"
        with mock.patch.object(ui, "_run_action") as run:
            ui._resolve_confirm(None, False)
        run.assert_not_called()
        self.assertEqual((ui.confirm, ui.confirm_action), ("", ""))

    def test_accepting_uninstall_runs_the_backend(self) -> None:
        ui = make_ui()
        ui.confirm, ui.confirm_action = "uninstall?", "uninstall"
        with mock.patch.object(ui, "_run_action") as run:
            ui._resolve_confirm(None, True)
        _stdscr, _title, steps, return_screen = run.call_args.args
        self.assertEqual(steps[0].argv[-1], "uninstall")
        self.assertEqual(return_screen, UI.MANAGE)

    def test_rollback_uses_the_selected_snapshot(self) -> None:
        ui = make_ui()
        ui.snapshots = [manage.Snapshot(id="20260101-120000", created_at="",
                                        note="", trees="")]
        ui.confirm, ui.confirm_action = "rollback?", "rollback"
        ui.row = 0
        with mock.patch.object(ui, "_run_action") as run:
            ui._resolve_confirm(None, True)
        _stdscr, _title, steps, return_screen = run.call_args.args
        self.assertEqual(steps[0].argv[-1], "20260101-120000")
        self.assertEqual(return_screen, UI.SNAPSHOTS)

    def test_any_key_reaches_the_resolver(self) -> None:
        # The old code raised AttributeError here and killed the UI.
        ui = make_ui()
        ui.confirm, ui.confirm_action = "uninstall?", "uninstall"
        with mock.patch.object(ui, "_resolve_confirm") as resolve:
            ui._manage_key(None, ord("y"))
        resolve.assert_called_once()


class BlockerTest(unittest.TestCase):
    def test_a_failed_check_keeps_the_install_disabled(self) -> None:
        ui = make_ui(blocked=True)
        ui.screen = UI.REVIEW
        with mock.patch.object(ui, "_install_loop") as install:
            ui._review_key(None, 10)
        install.assert_not_called()
        self.assertEqual(ui.screen, UI.REVIEW)


class RowClampTest(unittest.TestCase):
    def test_a_stale_row_from_a_longer_screen_is_clamped(self) -> None:
        # Esc from the manage menu used to index past the four menu rows and
        # take the whole UI down with an IndexError.
        ui = make_ui()
        ui.row = 99
        ui._clamp_row(4)
        self.assertEqual(ui.row, 3)
        ui.row = -1
        ui._clamp_row(4)
        self.assertEqual(ui.row, 0)
        ui.row = 2
        ui._clamp_row(0)
        self.assertEqual(ui.row, 0)


class LayoutTest(unittest.TestCase):
    def test_modes_follow_the_width(self) -> None:
        self.assertEqual(layout_mod.layout_for(66, 20).mode, "narrow")
        self.assertEqual(layout_mod.layout_for(40, 12).mode, "narrow")
        self.assertEqual(layout_mod.layout_for(80, 24).mode, "standard")
        self.assertEqual(layout_mod.layout_for(100, 30).mode, "standard")
        self.assertEqual(layout_mod.layout_for(110, 30).mode, "wide")
        self.assertEqual(layout_mod.layout_for(120, 36).mode, "wide")
        self.assertEqual(layout_mod.layout_for(39, 11).mode, "tiny")
        self.assertEqual(layout_mod.layout_for(80, 11).mode, "tiny")

    def test_wide_layout_uses_the_width_it_has(self) -> None:
        # The old split capped the block at 100 columns: 110+ was dead space.
        near = layout_mod.layout_for(110, 30)
        far = layout_mod.layout_for(120, 36)
        self.assertGreaterEqual(near.usable, 100)
        self.assertGreater(far.usable, near.usable)
        self.assertGreater(far.content.w, near.content.w)
        self.assertIsNotNone(near.detail)
        third = layout_mod.layout_for(300, 40)
        self.assertEqual(third.usable, layout_mod.MAX_USABLE)
        self.assertEqual(third.x, (300 - layout_mod.MAX_USABLE) // 2)

    def test_three_columns_only_when_asked_for(self) -> None:
        self.assertIsNone(layout_mod.layout_for(66, 20).nav)
        self.assertIsNotNone(layout_mod.layout_for(80, 24).nav)
        self.assertIsNone(layout_mod.layout_for(80, 24).detail)
        self.assertIsNotNone(layout_mod.layout_for(120, 36).detail)

    def test_panes_stay_inside_the_terminal(self) -> None:
        for width in range(36, 200, 2):
            for height in (10, 12, 20, 24, 36):
                with self.subTest(width=width, height=height):
                    layout = layout_mod.layout_for(width, height)
                    boxes = [layout.content, layout.nav, layout.detail]
                    for box in boxes:
                        if box is None:
                            continue
                        self.assertGreaterEqual(box.w, 0)
                        self.assertGreaterEqual(box.h, 0)
                        if not layout.tiny:
                            self.assertLessEqual(box.right, width)
                            self.assertLessEqual(box.bottom, height)
                    if layout.nav and layout.detail:
                        self.assertLess(layout.content.right, layout.detail.x)
                    self.assertLessEqual(layout.content.right, layout.usable + layout.x)

    def test_resize_switches_mode(self) -> None:
        widths = [66, 80, 100, 120]
        modes = [layout_mod.layout_for(width, 30).mode for width in widths]
        self.assertEqual(modes, ["narrow", "standard", "standard", "wide"])

    def test_short_terminal_keeps_the_body_alive(self) -> None:
        layout = layout_mod.layout_for(80, 12)
        self.assertGreaterEqual(layout.content.h, 4)
        self.assertLessEqual(layout.content.bottom, 12 - layout_mod.FOOTER_H)

    def test_copy_of_the_layout_is_not_shared(self) -> None:
        # Frozen boxes: a screen must ask for a new one instead of mutating.
        box = layout_mod.Box(1, 2, 3, 4)
        with self.assertRaises(Exception):
            box.x = 9  # type: ignore[misc]

    def test_stacked_list_hugs_its_rows(self) -> None:
        box = layout_mod.Box(0, 2, 20, 20)
        top, bottom = layout_mod.stack_list(box, 5, 6)
        self.assertEqual(top.h, 5)
        self.assertIsNotNone(bottom)
        self.assertEqual(bottom.y, top.bottom + 1)
        self.assertEqual(bottom.h, 6)
        # A long list takes the room; the detail keeps its own.
        tall, detail = layout_mod.stack_list(box, 100, 6)
        self.assertEqual(tall.h, box.h - 6 - 1)
        self.assertEqual(detail.bottom, box.bottom)
        # No room left for a detail block.
        short, none = layout_mod.stack_list(layout_mod.Box(0, 0, 10, 3), 2, 4)
        self.assertIsNone(none)
        self.assertEqual(short.h, 3)


class TextTest(unittest.TestCase):
    def test_wrapping_never_exceeds_the_cell_budget(self) -> None:
        samples = [
            "A Plasma 6 desktop rebuilt in Quickshell: panels, launcher, lock screen.",
            "用 Quickshell 重写的 Plasma 6 桌面：面板、启动器、锁屏与原生特效。",
            "/home/someone/Projects/NextKde/tools/kosctl install --only calendar,todo",
            "混合 mixed 中英文 text 的内容 with words",
        ]
        for text in samples:
            for cells in (8, 12, 20, 33, 64):
                for chunk in _wrap(text, cells):
                    self.assertLessEqual(_width(chunk), cells, f"{chunk!r} at {cells}")

    def test_wrapping_keeps_every_character(self) -> None:
        text = "/home/someone/Projects/NextKde/.slim/worktrees/installer-tui/tools/kosctl"
        joined = "".join(_wrap(text, 20)).replace(" ", "")
        self.assertEqual(joined, text)

    def test_wrapping_is_lossless_at_every_width(self) -> None:
        # The detail pane wraps at exactly the width it draws, so a chunk that
        # fills the pane must survive: no dropped character, no "…" for text
        # that fits. Odd widths put a 2-cell glyph on the boundary.
        samples = [
            "stable = 最新发布 tag；main = 开发分支。只在 checkout 位于 main 且干净时才会执行 update。",
            "The install takes over plasmashell; it applies after a log out and back in.",
            "混合 mixed 中英文 text 的内容 with words and /a/long/path/tools/kosctl",
            "用 Quickshell 重写的 Plasma 6 桌面：面板、启动器、锁屏与原生特效。",
        ]
        for text in samples:
            for cells in (7, 12, 20, 31, 32, 33, 48):
                with self.subTest(cells=cells, text=text[:12]):
                    joined = "".join(_wrap(text, cells))
                    self.assertEqual(joined.replace(" ", ""), text.replace(" ", ""))
                    for chunk in _wrap(text, cells):
                        self.assertLessEqual(_width(chunk), cells)

    def test_a_full_pane_of_text_is_drawn_without_an_ellipsis(self) -> None:
        from installer.render.layout import Box
        from installer.render.widgets import Canvas, Row

        ui = make_ui()
        for text in ("x" * 20, "中" * 10, "中文 mixed 中英 1234"):
            box = Box(0, 1, 20, 1)
            win = FakeWin(4, 24)
            Canvas(win, ui.theme).rows(box, [Row(text)], pointer=False)
            drawn = win.text()[1]
            with self.subTest(text=text):
                self.assertEqual(drawn, text)
                self.assertNotIn(ui.theme.glyphs.more, drawn)

    def test_clipping_marks_the_cut_and_fits(self) -> None:
        path = "/home/someone/Projects/NextKde/tools/kosctl"
        for cells in (5, 10, 24):
            clipped = _clip(path, cells)
            self.assertLessEqual(_width(clipped), cells)
            self.assertNotEqual(clipped, path)
        self.assertEqual(_clip("abc", 10), "abc")
        self.assertEqual(_clip(path, 0), "")
        self.assertLessEqual(_width(_clip(path, 6, "...")), 6)

    def test_wide_characters_count_as_two_cells(self) -> None:
        self.assertEqual(_width("中文"), 4)
        self.assertEqual(_width("abc"), 3)
        self.assertEqual(_width("中a"), 3)

    def test_control_characters_cannot_move_the_cursor(self) -> None:
        self.assertEqual(_printable("a\tb"), "a   b")
        self.assertNotIn("\n", _printable("a\nb"))


class GlyphTest(unittest.TestCase):
    def test_unicode_is_chosen_only_for_utf8(self) -> None:
        self.assertTrue(supports_unicode("UTF-8", "xterm-256color"))
        self.assertFalse(supports_unicode("UTF-8", "linux"))
        self.assertFalse(supports_unicode("ANSI_X3.4-1968", "xterm"))

    def test_ascii_fallback_has_no_unicode(self) -> None:
        ui = make_ui(probes=PROBES, ascii_glyphs=True)
        ui.sys_row = 6
        win = render(ui, "system", 24, 100)
        text = "\n".join(win.text())
        self.assertIn("[fail]", text)
        self.assertIn("[ok]", text)
        self.assertNotIn("✔", text)
        self.assertNotIn("✖", text)

    def test_unicode_glyphs_are_used_on_a_utf8_terminal(self) -> None:
        ui = make_ui(probes=PROBES)
        ui.theme = Theme(UNICODE, color=False)
        ui.sys_row = 6
        text = "\n".join(render(ui, "system", 24, 100).text())
        self.assertIn("✖", text)
        self.assertNotIn("[fail]", text)

    def test_status_is_never_colour_only(self) -> None:
        # The colour theme is off in tests; the rows still carry words.
        ui = make_ui(probes=PROBES)
        text = "\n".join(render(ui, "system", 24, 120).text())
        for word in ("pass", "warn", "fail"):
            self.assertIn(word, text)

    def test_theme_without_colour_still_marks_selection(self) -> None:
        theme = Theme(UNICODE, color=False)
        self.assertTrue(theme.attr("selected") & curses.A_REVERSE)
        self.assertFalse(theme.attr("brand") & curses.A_REVERSE)


class ScrollTest(unittest.TestCase):
    def test_selected_row_stays_visible(self) -> None:
        for count in (0, 1, 5, 20, 200):
            for height in (1, 3, 10):
                for selected in range(max(1, count)):
                    start = layout_mod.scroll_start(selected, count, height)
                    if count <= height:
                        self.assertEqual(start, 0)
                    else:
                        self.assertLessEqual(start, selected)
                        self.assertLess(selected, start + height)

    def test_option_list_scrolls_to_the_last_row(self) -> None:
        ui = make_ui()
        ui.opt_row = len(ui._option_targets(ui._options_rows())) - 1
        win = render(ui, "options", 20, 66)
        text = "\n".join(win.text())
        self.assertIn(ui.s("opt_start"), text)
        self.assertNotIn(ui.s("group_source"), text)
        self.assertIn("/", text)  # the range hint is shown

    def test_long_list_keeps_the_heading_and_the_hint(self) -> None:
        ui = make_ui(probes=PROBES)
        ui.sys_row = len(PROBES) - 1
        text = "\n".join(render(ui, "system", 20, 66).text())
        self.assertIn(ui.s("system_head"), text)
        self.assertIn(ui.s(PROBES[-1].key), text)

    def test_review_scroll_stops_at_the_end(self) -> None:
        ui = fill(make_ui())
        ui.review_scroll = 9999
        render(ui, "review", 24, 100)
        self.assertLess(ui.review_scroll, 9999)


class RenderTest(unittest.TestCase):
    SIZES = ((66, 20), (80, 24), (100, 30), (120, 36))

    def test_no_screen_overdraws_itself_in_either_language(self) -> None:
        for lang in ("zh", "en"):
            for width, height in self.SIZES:
                for name in SCREEN_NAMES:
                    with self.subTest(lang=lang, size=(width, height), screen=name):
                        ui = fill(make_ui(lang=lang, probes=PROBES))
                        win = render(ui, name, height, width)
                        self.assertEqual(win.overlaps, [])
                        self.assertEqual(win.escapes, [])

    def test_short_and_tiny_terminals_do_not_crash(self) -> None:
        for width, height in ((40, 12), (66, 12), (80, 13), (39, 11), (20, 6)):
            for name in SCREEN_NAMES:
                with self.subTest(size=(width, height), screen=name):
                    ui = fill(make_ui(probes=PROBES))
                    win = render(ui, name, height, width)
                    self.assertEqual(win.overlaps, [])
                    self.assertEqual(win.escapes, [])
                    text = "\n".join(win.text())
                    for token in ("why_probe", "detail_", "status_", "method_",
                                  "key_", "stage_", "source_stable"):
                        self.assertNotIn(token, text)
                    self.assertTrue(any(line.strip() for line in win.text()))

    def test_detail_panes_never_show_a_mid_sentence_ellipsis(self) -> None:
        # Regression: a one-cell row prefix used to push every full-width
        # wrapped line past the pane, replacing its last character with "…".
        for lang in ("zh", "en"):
            for width, height in self.SIZES:
                with self.subTest(lang=lang, size=(width, height)):
                    ui = fill(make_ui(lang=lang, probes=PROBES))
                    win = render(ui, "options", height, width)
                    detail = layout_mod.layout_for(width, height).detail
                    if detail is not None:
                        body = win.region_text(detail.x, detail.w)
                    else:  # stacked: everything above the footer rule
                        body = "\n".join(win.text()[:-2])
                    self.assertNotIn(ui.theme.glyphs.more, body)

    def test_the_wide_detail_column_is_actually_used(self) -> None:
        for name in ("system", "options", "review", "install"):
            with self.subTest(screen=name):
                ui = fill(make_ui(probes=PROBES))
                win = render(ui, name, 36, 120)
                detail = layout_mod.layout_for(120, 36).detail
                self.assertIsNotNone(detail)
                self.assertTrue(win.region_text(detail.x, detail.w))

    def test_resize_redraws_in_the_new_mode(self) -> None:
        ui = fill(make_ui(probes=PROBES))
        small = render(ui, "system", 20, 66)
        big = render(ui, "system", 36, 120)
        self.assertEqual(small.overlaps, [])
        self.assertEqual(big.overlaps, [])
        self.assertGreater(sum(len(line) for line in big.text()),
                           sum(len(line) for line in small.text()))

    def test_footer_and_header_stay_visible_on_every_size(self) -> None:
        ui = fill(make_ui(probes=PROBES))
        for width, height in self.SIZES:
            win = render(ui, "options", height, width)
            self.assertIn("KOS Installer", win.text()[0])
            self.assertTrue(win.text()[-1].strip())

    def test_a_failed_check_does_not_hide_the_footer(self) -> None:
        ui = fill(make_ui(blocked=True, probes=PROBES))
        text = "\n".join(render(ui, "review", 30, 100).text())
        self.assertIn(ui.s("review_blocked"), text)

    def test_selected_option_row_is_reversed(self) -> None:
        ui = make_ui()
        ui.opt_row = 4
        win = render(ui, "options", 30, 100)
        reversed_rows = {y for y, row in enumerate(win.attrs)
                         for attr in row if attr & curses.A_REVERSE}
        self.assertTrue(reversed_rows)
        # The only reversed row is the focused one, inside the list pane.
        self.assertEqual(len(reversed_rows), 1)


class FooterTest(unittest.TestCase):
    def test_every_screen_has_footer_keys(self) -> None:
        ui = fill(make_ui())
        for screen in (UI.WELCOME, UI.SYSTEM, UI.OPTIONS, UI.REVIEW, UI.MANAGE,
                       UI.UNITS, UI.SNAPSHOTS, UI.LOG):
            ui.screen = screen
            parts = ui.footer_parts()
            with self.subTest(screen=screen):
                self.assertTrue(parts)
                keys = [key for key, _label in parts]
                self.assertEqual(len(keys), len(set(keys)))

    def test_footer_is_localised(self) -> None:
        # The welcome footer used to be hard-coded English.
        for screen in (UI.WELCOME, UI.SYSTEM, UI.OPTIONS, UI.REVIEW, UI.RESULT,
                       UI.MANAGE, UI.UNITS, UI.SNAPSHOTS, UI.LOG):
            with self.subTest(screen=screen):
                zh = make_ui(lang="zh")
                zh.screen = screen
                en = make_ui(lang="en")
                en.screen = screen
                self.assertNotEqual([label for _k, label in zh.footer_parts()],
                                    [label for _k, label in en.footer_parts()])

    def test_install_lists_cancel_and_pause(self) -> None:
        ui = make_ui()
        ui.screen = UI.INSTALL
        keys = [key for key, _label in ui.footer_parts()]
        self.assertIn("Ctrl+C", keys)
        self.assertIn("p", keys)
        self.assertNotIn("F1", keys)
        ui.log_paused = True
        self.assertIn(("p", ui.s("key_resume")), ui.footer_parts())

    def test_review_offers_install_and_commands(self) -> None:
        ui = fill(make_ui())
        ui.screen = UI.REVIEW
        keys = [key for key, _label in ui.footer_parts()]
        self.assertIn("Enter", keys)
        self.assertIn("t", keys)

    def test_rendered_footer_matches_footer_parts(self) -> None:
        ui = fill(make_ui(lang="zh"))
        text = render(ui, "options", 30, 120).text()[-1]
        for key, label in ui.footer_parts():
            self.assertIn(f"{key} {label}", text)


class HelpTest(unittest.TestCase):
    def test_f1_opens_the_overlay_and_any_key_closes_it(self) -> None:
        ui = fill(make_ui())
        ui.screen = UI.OPTIONS
        self.assertTrue(ui.help_key(curses.KEY_F1))
        self.assertTrue(ui.help_open)
        self.assertTrue(ui.help_key(ord("x")))  # consumed by closing
        self.assertFalse(ui.help_open)
        self.assertTrue(ui.help_key(ord("?")))
        text = "\n".join(render(ui, "options", 24, 80).text())
        self.assertIn(ui.s("help_title"), text)
        self.assertEqual(ui.screen, UI.OPTIONS)

    def test_no_help_overlay_while_installing(self) -> None:
        ui = make_ui()
        ui.screen = UI.INSTALL
        self.assertFalse(ui.help_key(curses.KEY_F1))


class NavigationTest(unittest.TestCase):
    def test_options_survive_a_round_trip_through_review(self) -> None:
        ui = make_ui()
        ui.screen = UI.OPTIONS
        ui.opts.source = "main"
        ui.opts.app_set = {"todo"}
        ui.opts.apps = True
        ui.opts.lockscreen = True
        ui.opts.spatial = True
        ui.opts.start = True
        with mock.patch.object(curses_ui, "apps_missing", return_value=[]):
            ui._options_key(None, 10)          # Enter -> review
        self.assertEqual(ui.screen, UI.REVIEW)
        self.assertTrue(any("todo" in step.argv for step in ui.steps
                            if "--only" in step.argv))
        ui._review_key(None, 27)               # Esc -> options
        self.assertEqual(ui.screen, UI.OPTIONS)
        self.assertEqual((ui.opts.source, ui.opts.app_set, ui.opts.lockscreen,
                          ui.opts.spatial, ui.opts.start),
                         ("main", {"todo"}, True, True, True))

    def test_space_toggles_and_arrows_pick_the_source(self) -> None:
        ui = make_ui()
        ui.screen = UI.OPTIONS
        ui.opt_row = 0                          # the source row
        ui._options_key(None, curses.KEY_RIGHT)
        self.assertEqual(ui.opts.source, "main")
        ui._options_key(None, curses.KEY_RIGHT)
        self.assertEqual(ui.opts.source, "local")
        ui._options_key(None, curses.KEY_LEFT)
        self.assertEqual(ui.opts.source, "main")
        ui.opt_row = 1                          # the required core row: no toggle
        ui._options_key(None, ord(" "))
        self.assertEqual(ui.opts.source, "main")

    def test_turning_an_app_off_keeps_the_others(self) -> None:
        ui = make_ui()
        ui.opts.apps = True
        ui.opts.app_set = {"calendar", "todo"}
        ui.opt_row = 2                          # calendar (source, core, apps...)
        ui._options_key(None, ord(" "))
        self.assertEqual(ui.opts.app_set, {"todo"})
        self.assertTrue(ui.opts.apps)
        ui.opt_row = 3
        ui._options_key(None, ord(" "))
        self.assertEqual(ui.opts.app_set, set())
        self.assertFalse(ui.opts.apps)

    def test_system_enter_continues_and_esc_goes_back(self) -> None:
        ui = make_ui(probes=PROBES)
        ui.screen = UI.SYSTEM
        ui._system_key(None, 10)
        self.assertEqual(ui.screen, UI.OPTIONS)
        ui._system_key(None, 27)
        self.assertEqual(ui.screen, UI.WELCOME)

    def test_language_change_applies_immediately(self) -> None:
        ui = make_ui(lang="en")
        ui.screen = UI.WELCOME
        self.assertEqual(ui.s.lang, "en")
        ui._welcome_key(None, curses.KEY_DOWN)
        self.assertEqual(ui.s.lang, "zh")
        ui._welcome_key(None, curses.KEY_DOWN)
        self.assertEqual(ui.s.lang, "en")

    def test_review_enter_starts_install_and_returns_to_result(self) -> None:
        ui = fill(make_ui())
        ui.screen = UI.REVIEW
        with mock.patch.object(ui, "_install_loop") as loop, \
                mock.patch.object(ui, "_enter_result") as result:
            ui._review_key(None, 10)
        loop.assert_called_once()
        result.assert_called_once()
        self.assertEqual(ui.screen, UI.INSTALL)  # _enter_result is mocked

    def test_enter_on_a_blocked_review_runs_nothing(self) -> None:
        ui = make_ui(blocked=True, probes=PROBES)
        ui.screen = UI.REVIEW
        with mock.patch.object(ui, "_install_loop") as loop:
            ui._review_key(None, 10)
        loop.assert_not_called()
        self.assertEqual(ui.screen, UI.REVIEW)

    def test_t_shows_the_full_command(self) -> None:
        ui = fill(make_ui())
        ui.screen = UI.REVIEW
        # Tall enough that the step list is on screen: the point is that the
        # full argv becomes readable, not that it survives clipping.
        before = "\n".join(render(ui, "review", 40, 100).text())
        self.assertNotIn("/repo/tools/kosctl install apps --only", before)
        ui._review_key(None, ord("t"))
        after = "\n".join(render(ui, "review", 40, 100).text())
        self.assertNotEqual(before, after)
        self.assertIn("/repo/tools/kosctl", after.replace("\n", "").replace(" ", ""))

    def test_install_pause_stops_following_the_log(self) -> None:
        ui = fill(make_ui())
        ui.screen = UI.INSTALL
        self.assertFalse(ui.log_paused)
        ui._toggle_pause()
        self.assertTrue(ui.log_paused)
        self.assertEqual(ui.log_scroll, len(ui.log_lines) - 1)
        ui._scroll_log(-2)
        self.assertEqual(ui.log_scroll, len(ui.log_lines) - 3)
        text = "\n".join(render(ui, "install", 30, 100).text())
        self.assertIn(ui.s("install_log_paused"), text)

    def test_install_stage_states_are_reported(self) -> None:
        ui = fill(make_ui())
        self.assertEqual(ui._stage_state(0), "skipped")
        self.assertEqual(ui._stage_state(1), "running")
        self.assertEqual(ui._stage_state(2), "waiting")
        ui.result = "failed"
        ui.failed_index = 1
        self.assertEqual(ui._stage_state(1), "failed")
        ui.result = "ok"
        ui.current = None
        ui.step_index = len(ui.steps)
        self.assertEqual(ui._stage_state(1), "done")


class ResultTest(unittest.TestCase):
    def test_success_names_the_components_and_the_logout(self) -> None:
        ui = fill(make_ui())
        ui.result = "ok"
        text = "\n".join(render(ui, "result", 30, 100).text())
        self.assertIn(ui.s("success_title"), text)
        self.assertIn("core", text)
        self.assertIn(ui.s("next_steps")[:20], text)
        self.assertIn(str(ui.log_path)[:20], text)

    def test_failure_shows_the_step_the_code_and_the_tail(self) -> None:
        ui = fill(make_ui())
        ui.result = "failed"
        ui.failed = ui.steps[1]
        ui.failed_rc = 2
        ui.failed_index = 1
        text = "\n".join(render(ui, "result", 30, 120).text())
        self.assertIn(ui.s("failure_title"), text)
        self.assertIn("exit code: 2".replace("exit code", ui.s("result_exit_code")), text)
        self.assertIn("ninja: build stopped", text)

    def test_a_skipped_step_is_not_reported_as_done(self) -> None:
        ui = fill(make_ui())
        ui.result = "ok"
        ui.current = None
        ui.step_index = len(ui.steps)
        ui.skipped_steps = {2}
        text = "\n".join(render(ui, "result", 30, 120).text())
        self.assertIn(ui.s("result_skipped") % "kosctl install apps", text)


class PlainTest(unittest.TestCase):
    def _report(self, stream) -> str:
        system = make_system(probes=PROBES)
        steps = [Step("core", "kosctl install", ["/repo/tools/kosctl", "install"])]
        with mock.patch.object(plain.sys, "stdout", stream):
            plain.print_report(system, steps, Strings("en"))
        return stream.getvalue()

    def test_no_ansi_when_stdout_is_not_a_tty(self) -> None:
        output = self._report(io.StringIO())
        self.assertNotIn("\033", output)
        self.assertIn("System compatibility", output)
        self.assertIn("PASS", output)
        self.assertIn("kosctl install", output)

    def test_no_color_disables_ansi_on_a_tty(self) -> None:
        class Tty(io.StringIO):
            def isatty(self):
                return True

        with mock.patch.dict("os.environ", {"NO_COLOR": "1"}):
            output = self._report(Tty())
        self.assertNotIn("\033", output)

    def test_color_returns_on_a_tty_without_no_color(self) -> None:
        class Tty(io.StringIO):
            def isatty(self):
                return True

        with mock.patch.dict("os.environ", {}, clear=True):
            output = self._report(Tty())
        self.assertIn("\033[32m", output)

    def test_failure_names_the_log_path(self) -> None:
        system = make_system(probes=PROBES)
        stream = io.StringIO()
        step = Step("core", "kosctl install", [sys.executable, "-c", "raise SystemExit(3)"])
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(plain.sys, "stdout", stream):
            paths = make_paths(Path("."), Path(directory))
            code = plain.execute(system, [step], paths, Strings("en"))
        self.assertEqual(code, 1)
        output = stream.getvalue()
        self.assertIn(Strings("en")("log_path"), output)
        self.assertIn("3", output)
        self.assertNotIn("\033", output)


class BannerTest(unittest.TestCase):
    def test_welcome_shows_the_detection_at_every_size(self) -> None:
        ui = fill(make_ui(lang="zh", probes=PROBES))
        for width, height in ((66, 20), (80, 24), (100, 30), (120, 36)):
            with self.subTest(size=(width, height)):
                text = "\n".join(render(ui, "welcome", height, width).text())
                self.assertTrue("NextKDE" in text or curses_ui.LOGO[0] in text)
                self.assertIn(ui.s("welcome_start"), text)
                self.assertIn(ui.s("label_language"), text)
                self.assertIn("Arch Linux", text)

    def test_welcome_language_row_is_marked(self) -> None:
        ui = make_ui(lang="en")
        win = render(ui, "welcome", 24, 80)
        rows = {y for y, row in enumerate(win.attrs) for attr in row
                if attr & curses.A_REVERSE}
        self.assertTrue(rows)
        self.assertIn("English", "\n".join(win.text()))


if __name__ == "__main__":
    unittest.main()
