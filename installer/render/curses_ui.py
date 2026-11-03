"""The installer wizard and manager: input routing, navigation and state.

Screens: Welcome, System checks, Options, Review, Install, Result, Manage,
Units, Snapshots, Action, Log.

Geometry is decided by layout.py (narrow / standard / wide), colours and glyphs
by theme.py, and every write goes through widgets.Canvas, so no screen can
overdraw another pane. Backend work (detect, plan, runner, manage) is imported
unchanged: screens only present what it reports.
"""

from __future__ import annotations

import curses
import locale
import subprocess
import time
from pathlib import Path

from .. import manage, workflow
from ..detect import System, detect, method_label
from ..paths import Paths
from ..plan import (ALL_APPS, Options, Step, apps_missing, build_plan,
                    latest_release, proxy_url, selected_apps, unsupported)
from ..runner import StepRunner, classify
from ..strings import Strings
from .layout import (MIN_H, MIN_W, Box, layout_for, scroll_start, split_rows,
                     stack_list)
from .theme import (ASCII, PAIRS, UNICODE, Theme, supports_unicode)
from .widgets import Canvas, Row, _printable, _width, _wrap

LOGO = (
    "███╗   ██╗███████╗██╗  ██╗████████╗    ██╗  ██╗██████╗ ███████╗",
    "████╗  ██║██╔════╝╚██╗██╔╝╚══██╔══╝    ██║ ██╔╝██╔══██╗██╔════╝",
    "██╔██╗ ██║█████╗   ╚███╔╝    ██║       █████╔╝ ██║  ██║█████╗",
    "██║╚██╗██║██╔══╝   ██╔██╗    ██║       ██╔═██╗ ██║  ██║██╔══╝",
    "██║ ╚████║███████╗██╔╝ ██╗   ██║       ██║  ██╗██████╔╝███████╗",
    "╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝   ╚═╝       ╚═╝  ╚═╝╚═════╝ ╚══════╝",
)

ENTER = (10, 13, curses.KEY_ENTER)
UP = (curses.KEY_UP, ord("k"))
DOWN = (curses.KEY_DOWN, ord("j"))
SOURCES = ("stable", "main", "local")
STAGE_COUNT = 5
# The install steps themselves resolve these; everything else is the user's.
FIXABLE = ("probe_packages", "probe_quickshell")
_COLORS = {"brand": curses.COLOR_CYAN, "ok": curses.COLOR_GREEN,
           "warn": curses.COLOR_YELLOW, "fail": curses.COLOR_RED}


def _clock(seconds: float) -> str:
    seconds = int(max(0.0, seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class UI:
    (WELCOME, SYSTEM, OPTIONS, REVIEW, INSTALL, RESULT, MANAGE, UNITS,
     SNAPSHOTS, ACTION, LOG) = range(11)

    LANGUAGES = ("zh", "en")
    WIZARD = (WELCOME, SYSTEM, OPTIONS, REVIEW, INSTALL, RESULT)

    def __init__(self, system: System, paths: Paths, strings,
                 lang_explicit: bool = False) -> None:
        self.system = system
        self.paths = paths
        self.root = paths.source_root
        self.s = strings
        self.log_dir = paths.log_dir
        self.opts = Options()
        # An empty app set with apps enabled means "the standard four"; showing
        # it as checked is the same plan the backend already produces.
        if self.opts.apps and not self.opts.app_set:
            self.opts.app_set = set(ALL_APPS)
        self.steps: list[Step] = build_plan(system.family, self.opts, self.paths)
        self.prepared = None          # the source's identity, once obtained
        self.prepare_error = ""
        self.screen = self.WELCOME
        self.row = 0          # list row shared by manage/units/snapshots/logs
        self.lang_row = 0 if strings.lang == "zh" else 1
        self.opt_row = 0
        self.sys_row = 0
        self.review_scroll = 0
        self.review_details = False
        self.help_open = False
        self.latest_tag = latest_release(self.root)
        self.theme = Theme(self._glyphs(), color=False)
        self.layout = layout_for(80, 24)
        self.log_lines: list[tuple[str, str]] = []
        self.log_path = paths.log_dir / time.strftime("install-%Y%m%d-%H%M%S.log")
        self.log_paused = False
        self.log_scroll = 0
        self.current: Step | None = None
        self.phase = ""
        self.step_index = 0
        self.current_progress: float | None = None
        self.install_started = 0.0
        self.cancel_requested = False
        self.result = ""
        self.failed: Step | None = None
        self.failed_index: int | None = None
        self.failed_rc: int | None = None
        self.skipped_steps: set[int] = set()
        self.result_units: list[manage.Unit] = []
        self.app_deps: list[str] = []
        self._drawn_screen = -1
        self.action_title = ""
        self.action_steps: list[Step] = []
        self.action_state = ""
        self.return_screen = self.MANAGE
        self.units: list[manage.Unit] = []
        # The system row's pane shows the packages too, so load them once here
        # (one package-manager query plus a doc parse, ~0.2 s).
        self.deps_data = manage.deps_from_docs(self.root, system.family or "")
        if not self.deps_data.packages:
            self.deps_data = manage.deps(self.root)
        self.snapshots: list[manage.Snapshot] = []
        self.picker: list[tuple[str, str]] = []
        self.log_text: list[str] = []
        self.log_text_path = self.log_path
        self.log_scroll_view = 0
        self.confirm = ""
        self.confirm_action = ""
        self.log_return = self.MANAGE
        self.manage_return = self.WELCOME

    # -- glyphs and entry ------------------------------------------------
    @staticmethod
    def _glyphs():
        return UNICODE if supports_unicode() else ASCII

    def run(self) -> int:
        locale.setlocale(locale.LC_ALL, "")
        return curses.wrapper(self._loop)

    def _loop(self, stdscr) -> int:
        curses.curs_set(0)
        stdscr.keypad(True)
        color = False
        if curses.has_colors():
            curses.start_color()
            try:
                curses.use_default_colors()
                background = -1
            except curses.error:
                background = curses.COLOR_BLACK
            for role, pair in PAIRS.items():
                curses.init_pair(pair, _COLORS[role], background)
            color = True
        self.theme = Theme(self._glyphs(), color=color)

        while True:
            self._draw(stdscr)
            ch = stdscr.getch()
            if ch == curses.KEY_RESIZE:
                continue
            if self.help_key(ch):
                continue
            handler = {
                self.WELCOME: self._welcome_key,
                self.SYSTEM: self._system_key,
                self.OPTIONS: self._options_key,
                self.REVIEW: self._review_key,
                self.RESULT: self._result_key,
                self.MANAGE: self._manage_key,
                self.UNITS: self._units_key,
                self.SNAPSHOTS: self._snapshots_key,
                self.ACTION: self._action_key,
                self.LOG: self._log_key,
            }.get(self.screen)
            if handler is None:
                continue
            code = handler(stdscr, ch)
            if code is not None:
                return code

    # -- welcome ---------------------------------------------------------
    def _apply_language(self) -> None:
        self.s = Strings(self.LANGUAGES[self.lang_row])

    def _welcome_key(self, stdscr, ch) -> int | None:
        if ch in UP or ch in DOWN or ch in (curses.KEY_LEFT, curses.KEY_RIGHT) \
                or ch == ord(" "):
            self.lang_row = (self.lang_row + 1) % len(self.LANGUAGES)
            self._apply_language()
        elif ch in ENTER:
            self._apply_language()
            self.screen = self.SYSTEM
        elif ch in (ord("m"), ord("M")):
            self._enter_manage(self.WELCOME)
        elif ch in (ord("q"), 27):
            return 0
        return None

    # -- system checks ---------------------------------------------------
    def _system_key(self, stdscr, ch) -> int | None:
        if ch in UP:
            self.sys_row = max(0, self.sys_row - 1)
        elif ch in DOWN:
            self.sys_row += 1
        elif ch == curses.KEY_PPAGE:
            self.sys_row = max(0, self.sys_row - 10)
        elif ch == curses.KEY_NPAGE:
            self.sys_row += 10
        elif ch == curses.KEY_F5:
            self.system = detect(root=self.root)
            self._load_deps()
            self.sys_row = 0
        elif ch in ENTER:
            self.screen = self.OPTIONS
        elif ch in (27, ord("q")):
            self.screen = self.WELCOME
        self.sys_row = min(self.sys_row, max(0, len(self.system.probes) - 1))
        return None

    def _load_deps(self) -> None:
        """Prefer the guide's list (docs/GettingStarted.md); kosctl is the fallback."""
        self.deps_data = manage.deps_from_docs(self.root, self.system.family or "")
        if not self.deps_data.packages:
            self.deps_data = manage.deps(self.root)

    def _missing_deps(self) -> list[str]:
        return [name for name, good in (self.deps_data.packages if self.deps_data else [])
                if not good]

    # -- options ---------------------------------------------------------
    def _options_rows(self) -> list[tuple[str, str, str, str]]:
        """(kind, key, label, value); ``group`` rows are headings."""
        s = self.s
        rows: list[tuple[str, str, str, str]] = [
            ("group", "group_source", s("group_source"), ""),
            ("source", "source", s("source_" + self.opts.source),
             self.latest_tag if self.opts.source == "stable" else ""),
            ("group", "group_core", s("group_core"), ""),
            ("core", "core", s("core_shell"), s("label_required")),
            ("group", "group_optional", s("group_optional"), ""),
        ]
        rows += [("app", name, s("app_" + name), "") for name in ALL_APPS]
        rows += [
            ("group", "group_advanced", s("group_advanced"), ""),
            ("toggle", "lockscreen", s("opt_lockscreen"), ""),
            ("toggle", "spatial", s("opt_spatial"), ""),
            ("toggle", "start", s("opt_start"), ""),
        ]
        return rows

    @staticmethod
    def _option_targets(rows) -> list[int]:
        return [index for index, row in enumerate(rows) if row[0] != "group"]

    def _focused_option(self) -> tuple[str, str]:
        rows = self._options_rows()
        targets = self._option_targets(rows)
        if not targets:
            return "", ""
        index = targets[min(self.opt_row, len(targets) - 1)]
        kind, key, _label, _value = rows[index]
        return kind, key

    def _option_on(self, kind: str, key: str) -> bool:
        if kind == "app":
            return key in self.opts.app_set
        if kind == "toggle":
            return bool(getattr(self.opts, key))
        return True

    def _set_option(self, kind: str, key: str, on: bool) -> None:
        if kind == "app":
            if on:
                self.opts.app_set.add(key)
            else:
                self.opts.app_set.discard(key)
            self.opts.apps = bool(self.opts.app_set)
        elif kind == "toggle":
            setattr(self.opts, key, on)
        elif kind == "source":
            options = list(SOURCES)
            step = 1 if on else -1
            self.opts.source = options[(options.index(self.opts.source) + step) % len(options)]
            # A different channel is a different commit: prepare it again.
            self.prepared = None
            self.prepare_error = ""

    def _options_key(self, stdscr, ch) -> int | None:
        rows = self._options_rows()
        targets = self._option_targets(rows)
        self.opt_row = max(0, min(self.opt_row, len(targets) - 1))
        if ch in UP:
            self.opt_row = max(0, self.opt_row - 1)
        elif ch in DOWN:
            self.opt_row = min(len(targets) - 1, self.opt_row + 1)
        elif ch in (curses.KEY_LEFT, curses.KEY_RIGHT, ord(" ")):
            kind, key = self._focused_option()
            if kind == "source":
                self._set_option(kind, key, ch == curses.KEY_RIGHT)
            elif kind in ("toggle", "app"):
                on = (ch == curses.KEY_RIGHT) if ch in (curses.KEY_LEFT, curses.KEY_RIGHT) \
                    else not self._option_on(kind, key)
                self._set_option(kind, key, on)
        elif ch in ENTER:
            self._enter_review()
        elif ch in (27, ord("q")):
            self.screen = self.WELCOME
        return None

    def _enter_review(self) -> None:
        self.steps = build_plan(self.system.family, self.opts, self.paths, self.prepared)
        source = self.prepared.path if self.prepared is not None else self.root
        self.app_deps = apps_missing(source) if self.opts.apps else []
        self.prepare_error = ""
        self.review_scroll = 0
        self.screen = self.REVIEW

    # -- review / install ------------------------------------------------
    def _review_key(self, stdscr, ch) -> int | None:
        if ch in (ord("i"), ord("I")):
            if self._missing_deps():
                self._run_action(stdscr, "kosctl deps --install",
                                 [manage.kosctl(self.root, "deps", "--install")], self.REVIEW)
                self._load_deps()
            return None
        if ch in (ord("t"), ord("T")):
            self.review_details = not self.review_details
            self.review_scroll = 0
        elif ch in UP:
            self.review_scroll = max(0, self.review_scroll - 1)
        elif ch in DOWN:
            self.review_scroll += 1
        elif ch == curses.KEY_PPAGE:
            self.review_scroll = max(0, self.review_scroll - 8)
        elif ch == curses.KEY_NPAGE:
            self.review_scroll += 8
        elif ch in ENTER:
            if self.system.blocked:
                return None
            if self.prepared is None:
                # Fetch once, then come back here: the commit that will be
                # installed has to be visible before anything changes.
                self._prepare_source(stdscr)
                return None
            self.screen = self.INSTALL
            self._install_loop(stdscr)
            self._enter_result()
        elif ch in (27, ord("q")):
            self.screen = self.OPTIONS
        return None

    def _prepare_source(self, stdscr) -> bool:
        """Fetch and verify the chosen source; True once ``self.prepared`` is set.

        Runs the one clone step through the ACTION screen, so its output is
        visible, and returns to Review either way: on failure with the error.
        """
        self.prepare_error = ""
        try:
            preparation = workflow.begin(self.opts.source, self.opts, self.paths)
            if preparation.steps:
                self._run_action(stdscr, preparation.steps[0].title,
                                 preparation.steps, self.REVIEW)
                if self.action_state != "done":
                    self.action_state = "failed"
                    self.prepare_error = self._error_summary()
                    self.screen = self.REVIEW
                    return False
            self.prepared = preparation.finish()
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            self.action_state = "failed"
            self.prepare_error = str(error)
            self.log_lines.append(("ERROR", str(error)))
            self.screen = self.REVIEW
            return False
        self.steps = build_plan(self.system.family, self.opts, self.paths, self.prepared)
        self.screen = self.REVIEW
        return True

    def _enter_result(self) -> None:
        self.screen = self.RESULT
        self.result_units = manage.units(self.root)
        self.review_details = False

    def _result_key(self, stdscr, ch) -> int | None:
        if self.result != "ok" and ch in (ord("r"), ord("R")):
            self.screen = self.INSTALL
            self._install_loop(stdscr)
            self._enter_result()
        elif ch in (ord("l"), ord("L")):
            self._open_install_log()
        elif ch in (ord("m"), ord("M")):
            self._enter_manage(self.RESULT)
        elif ch in (*ENTER, ord("q"), 27):
            return self._exit_code()
        return None

    def _exit_code(self) -> int:
        if self.result == "ok":
            return 0
        if self.result == "cancelled":
            return 130
        return 1 if self.result == "failed" else 0

    # -- manage ---------------------------------------------------------
    def _manage_rows(self) -> list[tuple[str, str]]:
        return [
            ("units", self.s("manage_units")),
            ("snapshots", self.s("manage_snapshots")),
            ("doctor", self.s("manage_doctor")),
            ("logs", self.s("manage_logs")),
            ("uninstall", self.s("manage_uninstall")),
        ]

    def _manage_values(self) -> dict[str, str]:
        return {"units": str(len(self.units)), "snapshots": str(len(self.snapshots))}

    def _enter_manage(self, return_screen: int) -> None:
        self.manage_return = return_screen
        self.units = manage.units(self.root)
        self.snapshots = manage.snapshots(self.root)
        self.row = 0
        self.screen = self.MANAGE

    def _manage_key(self, stdscr, ch) -> int | None:
        if self.confirm:
            self._resolve_confirm(stdscr, ch in (ord("y"), ord("Y")))
            return None
        rows = self._manage_rows()
        if ch in UP:
            self.row = (self.row - 1) % len(rows)
        elif ch in DOWN:
            self.row = (self.row + 1) % len(rows)
        elif ch in (27, ord("q")):
            self.screen = self.manage_return
        elif ch in ENTER:
            key = rows[self.row][0]
            if key == "units":
                self.units = manage.units(self.root)
                self.row = 0
                self.screen = self.UNITS
            elif key == "snapshots":
                self.snapshots = manage.snapshots(self.root)
                self.row = 0
                self.screen = self.SNAPSHOTS
            elif key == "doctor":
                self._run_action(stdscr, self.s("manage_doctor"),
                                 [manage.action_step(self.root, "kosctl doctor",
                                                     str(self.root / "tools" / "kosctl"), "doctor")],
                                 self.MANAGE)
            elif key == "logs":
                self._open_logs()
            elif key == "uninstall":
                self.confirm = self.s("confirm_uninstall")
                self.confirm_action = "uninstall"
        return None

    def _units_key(self, stdscr, ch) -> int | None:
        if not self.units:
            if ch in (27, *ENTER):
                self.screen = self.MANAGE
            return None
        if ch in UP:
            self.row = (self.row - 1) % len(self.units)
        elif ch in DOWN:
            self.row = (self.row + 1) % len(self.units)
        elif ch in (27, ord("q")):
            self.screen = self.MANAGE
        elif ch == ord(" "):
            unit = self.units[self.row].name
            verb = "off" if self.units[self.row].installed else "on"
            if unit == "core" and verb == "off":
                self.action_state = "failed"
                self.action_title = "core"
                self.log_lines = [("ERROR", "core cannot be switched off; use uninstall")]
                self.screen = self.ACTION
                return None
            self._run_action(stdscr, f"kosctl {verb} {unit}",
                             [manage.kosctl(self.root, verb, unit)], self.UNITS)
        elif ch in ENTER:
            self.screen = self.MANAGE
        return None

    def _snapshots_key(self, stdscr, ch) -> int | None:
        if self.confirm:
            self._resolve_confirm(stdscr, ch in (ord("y"), ord("Y")))
            return None
        if ch in (27, ord("q")):
            self.screen = self.MANAGE
            return None
        if ch == ord(" "):
            self._run_action(stdscr, "kosctl snapshot",
                             [manage.kosctl(self.root, "snapshot", "from installer")],
                             self.SNAPSHOTS)
            return None
        if not self.snapshots:
            return None
        if ch in UP:
            self.row = (self.row - 1) % len(self.snapshots)
        elif ch in DOWN:
            self.row = (self.row + 1) % len(self.snapshots)
        elif ch in ENTER:
            self.confirm = self.s("confirm_rollback")
            self.confirm_action = "rollback"
        return None

    def _resolve_confirm(self, stdscr, yes: bool) -> None:
        action, self.confirm, self.confirm_action = self.confirm_action, "", ""
        if yes and action:
            self._confirm_then(stdscr, action)

    def _confirm_then(self, stdscr, action: str) -> None:
        if action == "uninstall":
            self._run_action(stdscr, "kosctl uninstall",
                             [manage.kosctl(self.root, "uninstall")], self.MANAGE)
        elif action == "rollback" and self.snapshots:
            snapshot_id = self.snapshots[self.row].id
            self._run_action(stdscr, f"kosctl rollback {snapshot_id}",
                             [manage.kosctl(self.root, "rollback", snapshot_id)],
                             self.SNAPSHOTS)

    # -- action runner ---------------------------------------------------
    def _run_action(self, stdscr, title: str, steps: list[Step], return_screen: int) -> None:
        self.action_title = title
        self.action_steps = steps
        self.action_state = "running"
        self.return_screen = return_screen
        self.screen = self.ACTION
        self.log_lines = []
        self._run_action_blocking(stdscr)

    def _action_key(self, stdscr, ch) -> int | None:
        # The action itself runs from _draw_action's first frame; keys only
        # leave once it is finished.
        if self.action_state in ("done", "failed") and ch in (10, 13, 27, curses.KEY_ENTER):
            self._refresh_after_action()
            self.screen = self.return_screen
        return None

    def _refresh_after_action(self) -> None:
        self.units = manage.units(self.root)
        self.snapshots = manage.snapshots(self.root)

    def _run_action_blocking(self, stdscr) -> None:
        stdscr.nodelay(True)
        self.log_lines = []
        try:
            with self.log_path.open("a", encoding="utf-8") as log:
                failed = False
                for step in self.action_steps:
                    self.current = step
                    runner = StepRunner(step, self.root, log)
                    runner.start()
                    last = 0.0
                    while True:
                        line = runner.readline(0.05)
                        while line is not None:
                            self.log_lines.append((classify(line), line))
                            if len(self.log_lines) > 800:
                                del self.log_lines[:300]
                            line = runner.readline(0.0)
                        now = time.monotonic()
                        if now - last > 0.1:
                            self._draw(stdscr)
                            last = now
                        # Management actions can take minutes (a full
                        # uninstall); q/Esc stops them the same way the
                        # install loop does.
                        if stdscr.getch() in (27, ord("q"), ord("Q")):
                            runner.cancel()
                        if runner.poll() is not None:
                            break
                    if runner.close() != 0:
                        failed = True
                        break
                self.action_state = "failed" if failed else "done"
                self.current = None
                self._draw(stdscr)
        finally:
            stdscr.nodelay(False)

    # -- logs -------------------------------------------------------------
    def _open_install_log(self) -> None:
        self.log_return = self.RESULT if self.result else self.MANAGE
        self._show_log(self.log_path)

    def _open_logs(self) -> None:
        files = manage.logs(self.log_dir)
        self.log_return = self.MANAGE
        if not files:
            self.picker = []
            self.log_text = [self.s("logs_none")]
            self.log_scroll_view = 0
            self.screen = self.LOG
            return
        self.picker = [(str(path), path.name) for path in files]
        self.row = 0
        self.screen = self.LOG

    def _show_log(self, path: Path) -> None:
        try:
            self.log_text = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as error:
            self.log_text = [str(error)]
        self.log_scroll_view = max(0, len(self.log_text) - 10)
        self.picker = []
        self.log_text_path = path
        self.screen = self.LOG

    def _log_key(self, stdscr, ch) -> int | None:
        if self.picker:  # choosing a file
            if ch in UP:
                self.row = (self.row - 1) % len(self.picker)
            elif ch in DOWN:
                self.row = (self.row + 1) % len(self.picker)
            elif ch in ENTER:
                self._show_log(Path(self.picker[self.row][0]))
            elif ch in (27, ord("q")):
                self.screen = self.log_return
            return None
        if ch in (27, ord("q")):
            self.screen = self.log_return
            return None
        if ch in UP:
            self.log_scroll_view = max(0, self.log_scroll_view - 1)
        elif ch in DOWN:
            self.log_scroll_view = min(max(0, len(self.log_text) - 1),
                                       self.log_scroll_view + 1)
        elif ch == curses.KEY_PPAGE:
            self.log_scroll_view = max(0, self.log_scroll_view - 10)
        elif ch == curses.KEY_NPAGE:
            self.log_scroll_view += 10
        return None

    # -- drawing ---------------------------------------------------------
    def _clamp_row(self, count: int) -> None:
        self.row = max(0, min(self.row, count - 1))

    def _draw(self, stdscr) -> None:
        if self.screen != self._drawn_screen:
            stdscr.clearok(True)
            self._drawn_screen = self.screen
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        c = Canvas(stdscr, self.theme)
        layout = layout_for(width, height)
        self.layout = layout
        if layout.tiny:
            c.put(0, 1, self.s("title"), "brand", True)
            c.wrapped(2, 1, max(1, width - 2), 2,
                      self.s("notice_big") % (MIN_W, MIN_H, width, height), "warn")
            stdscr.noutrefresh()
            curses.doupdate()
            return
        self._header(c, layout)
        self._footer(c, layout)
        self._clamp_rows()
        full = Box(layout.x, layout.top, layout.usable, layout.bottom - layout.top)
        if self.screen in self.WIZARD and self.screen != self.WELCOME:
            box, side = layout.content, layout.detail
            if layout.nav:
                self._nav(c, layout.nav)
                c.vrule(layout.nav.right, layout.nav.y, layout.nav.h)
            if side is not None:
                # The rule sits in the first gap column, leaving one blank
                # before the column's text: "│ text", not "│text".
                c.vrule(side.x - 2, side.y, side.h)
        elif self.screen in (self.WELCOME, self.LOG, self.ACTION):
            # A hero page, a log reader and one command's output all read
            # better across the whole width.
            box, side = full, None
        else:
            box, side = self._management_split(full)
            if side is not None:
                # The rule sits in the first gap column, leaving one blank
                # before the column's text: "│ text", not "│text".
                c.vrule(side.x - 2, side.y, side.h)
        drawer = {
            self.WELCOME: self._welcome,
            self.SYSTEM: self._system,
            self.OPTIONS: self._options,
            self.REVIEW: self._review,
            self.INSTALL: self._installation,
            self.RESULT: self._result,
            self.MANAGE: self._manage,
            self.UNITS: self._units,
            self.SNAPSHOTS: self._snapshots,
            self.ACTION: self._action,
            self.LOG: self._log,
        }[self.screen]
        drawer(c, box, side)
        if self.confirm:
            c.dialog(self.s("title"), [self.confirm], "[y/N]")
        if self.help_open:
            self._help(c)
        stdscr.noutrefresh()
        curses.doupdate()

    def _clamp_rows(self) -> None:
        # Every screen shares self.row; coming back from a longer list (the
        # manage menu, a unit list) must not index past this one.
        if self.screen == self.MANAGE:
            self._clamp_row(len(self._manage_rows()))
        elif self.screen == self.UNITS:
            self._clamp_row(len(self.units))
        elif self.screen == self.SNAPSHOTS:
            self._clamp_row(len(self.snapshots))
        elif self.screen == self.REVIEW:
            self.review_scroll = max(0, self.review_scroll)
        elif self.screen == self.LOG:
            if self.picker:
                self._clamp_row(len(self.picker))
            else:
                self.log_scroll_view = max(0, min(self.log_scroll_view,
                                                  max(0, len(self.log_text) - 1)))

    def _management_split(self, full: Box) -> tuple[Box, Box | None]:
        if full.w < 70:
            return full, None
        list_w = max(30, min(52, full.w * 2 // 3))
        return (Box(full.x, full.y, list_w, full.h),
                Box(full.x + list_w + 2, full.y, full.w - list_w - 2, full.h))

    def _header(self, c: Canvas, layout) -> None:
        # The brand is constant: it must not change when the language does.
        sep = f" {self.theme.glyphs.sep} "
        source = self._source_text()
        left = f"KOS Installer{sep}{source}"
        right = f"{self.system.label}{sep}{self.system.arch}"
        c.put(0, layout.x, left, "brand", True, layout.usable)
        if _width(left) + 3 + _width(right) <= layout.usable:
            c.put(0, layout.x + layout.usable - _width(right) - 1, right, "secondary",
                  False, _width(right) + 1)
        c.rule(1, layout.x, layout.usable)

    def _footer(self, c: Canvas, layout) -> None:
        c.rule(layout.height - 2, 0, layout.width)
        sep = f" {self.theme.glyphs.sep} "
        hints = sep.join(f"{key} {label}" for key, label in self.footer_parts())
        c.put(layout.height - 1, 1, hints, "secondary", False, layout.width - 1)

    def footer_parts(self) -> list[tuple[str, str]]:
        """Only the keys that do something on this screen."""
        s = self.s
        up_down = self.theme.glyphs.up_down
        left_right = self.theme.glyphs.left_right
        parts = {
            self.WELCOME: [(up_down + left_right, s("key_language")),
                           ("Enter", s("key_start")), ("m", s("key_manage")),
                           ("q", s("key_quit"))],
            self.SYSTEM: [(up_down, s("key_select")), ("Enter", s("key_continue")),
                          ("F5", s("key_refresh")), ("Esc", s("key_back"))],
            self.OPTIONS: [(up_down, s("key_move")), ("Space", s("key_toggle")),
                           (left_right, s("key_cycle")), ("Enter", s("key_continue")),
                           ("Esc", s("key_back"))],
            self.REVIEW: [(up_down, s("key_scroll")), ("t", s("key_details")),
                          ("Enter", s("key_start")), ("Esc", s("key_back"))],
            self.INSTALL: [("Ctrl+C", s("key_cancel")),
                           ("p", s("key_resume") if self.log_paused else s("key_pause")),
                           (up_down, s("key_scroll"))],
            self.RESULT: [("Enter", s("key_exit")), ("l", s("key_log")),
                          ("m", s("key_manage"))],
            self.MANAGE: [(up_down, s("key_move")), ("Enter", s("key_open")),
                          ("Esc", s("key_back"))],
            self.UNITS: [(up_down, s("key_move")), ("Space", s("key_toggle")),
                         ("Esc", s("key_back"))],
            self.SNAPSHOTS: [(up_down, s("key_move")), ("Space", s("key_create")),
                             ("Enter", s("key_rollback")), ("Esc", s("key_back"))],
            self.ACTION: [("Enter", s("key_back"))],
            self.LOG: [(up_down, s("key_scroll")), ("Esc", s("key_back"))],
        }.get(self.screen, [])
        if self.screen == self.REVIEW and self._missing_deps():
            parts = parts[:1] + [("i", s("key_deps"))] + parts[1:]
        if self.screen == self.RESULT and self.result != "ok":
            parts = parts[:1] + [("r", s("key_retry"))] + parts[1:]
        if self.screen not in (self.INSTALL, self.ACTION, self.LOG):
            parts = [*parts, ("F1", s("key_help"))]
        return parts

    def help_key(self, ch) -> bool:
        """True when the key belonged to the help overlay."""
        if self.help_open:
            self.help_open = False
            return True
        if ch in (curses.KEY_F1, ord("?")) and self.screen != self.INSTALL:
            self.help_open = True
            return True
        return False

    def _help(self, c: Canvas) -> None:
        lines = [self.s("help_heading"),
                 *[f"{key}: {label}" for key, label in self.footer_parts()]]
        c.dialog(self.s("help_title"), lines, self.s("help_close"))

    def _heading(self, c: Canvas, box: Box, text: str, step: int | None = None,
                 hint: str = "") -> None:
        c.put(box.y, box.x, text, "brand", True, box.w)
        if hint:
            right = box.x + box.w - _width(hint) - 1
            if right > box.x + _width(text) + 2:
                c.put(box.y, right, hint, "secondary", False, _width(hint) + 1)
            return
        if step is None or self.layout.nav is not None:
            return
        tag = self.s("step_of") % (step + 1, STAGE_COUNT)
        right = box.x + box.w - _width(tag) - 1
        if right > box.x + _width(text) + 2:
            c.put(box.y, right, tag, "secondary", False, _width(tag) + 1)

    def _range_hint(self, start: int, shown: int, total: int) -> str:
        """Say where the visible window sits, so a clipped list is not silent."""
        if total <= shown:
            return ""
        return self.s("listing_range") % (start + 1, start + shown, total)

    def _nav(self, c: Canvas, box: Box) -> None:
        if box.h <= 0:
            return
        step = {self.WELCOME: 0, self.SYSTEM: 1, self.OPTIONS: 2, self.REVIEW: 3,
                self.INSTALL: 4, self.RESULT: 4}.get(self.screen, 0)
        labels = (self.s("step_welcome"), self.s("step_system"), self.s("step_options"),
                  self.s("step_review"), self.s("step_install"))
        glyphs = self.theme.glyphs
        y = box.y + 1
        for index, label in enumerate(labels):
            if y >= box.bottom:
                return
            if index == step:
                # Brand bold marks "you are here"; reverse is reserved for the
                # row that actually has focus.
                c.put(y, box.x, f"{glyphs.pointer} {label}", "brand", True, box.w)
            elif index < step:
                c.put(y, box.x, f"  {glyphs.ok} {label}", "secondary", False, box.w)
            else:
                c.put(y, box.x, f"  {glyphs.info} {label}", "secondary", False, box.w)
            y += 1
        if box.bottom - y >= 3:
            c.rule(y + 1, box.x, max(1, box.w - 2))
            c.put(y + 2, box.x, f"m {self.s('nav_manage')}", "secondary", False, box.w)

    def _source_text(self) -> str:
        if self.opts.source == "local":
            return self.s("source_local")
        if self.opts.source == "main":
            return self.s("source_main")
        tag = f" {self.latest_tag}" if self.latest_tag else ""
        return f"{self.s('source_stable')}{tag}"

    def _session_text(self) -> str:
        probe = next((p for p in self.system.probes if p.key == "probe_session"), None)
        return probe.detail if probe else "?"

    # -- welcome ---------------------------------------------------------
    def _welcome(self, c: Canvas, box: Box, side: Box | None = None) -> None:
        glyphs = self.theme.glyphs
        # A hero block: one centred column instead of panes. It reads as a
        # landing page and keeps the language choice and the start action on
        # screen however short the terminal is.
        block_w = min(box.w, 74)
        block_x = box.x + (box.w - block_w) // 2
        y = box.y + 1
        logo_fits = box.h >= 22 and block_w >= _width(LOGO[0])
        if logo_fits:
            pad = max(0, (block_w - _width(LOGO[0])) // 2)
            for line in LOGO:
                c.put(y, block_x + pad, line, "brand", True, block_w - pad)
                y += 1
            y += 1
        else:
            c.put(y, block_x, "NextKDE", "brand", True, block_w)
            y += 2
        y = c.wrapped(y, block_x, block_w, 2, self.s("welcome_intro"), "secondary") + 1
        facts = [
            (self.s("label_distro"), self.system.label),
            (self.s("label_arch"), self.system.arch),
            (self.s("label_session"), self._session_text()),
            (self.s("label_path"), self.s("review_target")),
            (self.s("label_source"), self._source_text()),
        ]
        # Language and start need three rows; the facts use whatever is above.
        language_y = box.bottom - 3
        if language_y - y > len(facts):
            key_w = max(_width(label) for label, _value in facts) + 2
            for label, value in facts:
                c.put(y, block_x, label, "secondary", False, key_w + 1)
                c.put(y, block_x + key_w, value, "text", False, max(4, block_w - key_w))
                y += 1
            language_y = min(y + 1, box.bottom - 3)
        else:
            language_y = min(y, box.bottom - 3)
        self._language_row(c, Box(block_x, box.y, block_w, box.h), language_y)
        start_y = min(language_y + 2, box.bottom - 1)
        c.put(start_y, block_x, f"{glyphs.pointer} [Enter] {self.s('welcome_start')}",
              "brand", True, block_w)

    def _language_row(self, c: Canvas, box: Box, y: int) -> None:
        if y >= box.bottom - 1:
            return
        glyphs = self.theme.glyphs
        label = self.s("label_language")
        labels = [("中文" if lang == "zh" else "English", index)
                  for index, lang in enumerate(self.LANGUAGES)]
        chips = sum(_width(text) + 4 for text, _index in labels) + 2
        inline = _width(label) + 3 + chips <= box.w
        if inline:
            c.put(y, box.x, label, "secondary", False, _width(label) + 1)
            x = box.x + _width(label) + 3
        else:
            c.put(y, box.x, label, "secondary", False, box.w)
            y += 1
            x = box.x + 2
        for text, index in labels:
            if y >= box.bottom - 1:
                return
            active = index == self.lang_row
            if active:
                c.put(y, x, glyphs.pointer, "brand", True, 3)
            c.put(y, x + 2, text, "selected" if active else "secondary", False,
                  _width(text) + 1)
            if inline:
                x += 2 + _width(text) + 4
            else:
                y += 1
                x = box.x + 2

    # -- system ----------------------------------------------------------
    def _system(self, c: Canvas, box: Box, side: Box | None = None) -> None:
        probes = self.system.probes
        if not probes:
            self._heading(c, box, self.s("system_head"), 1)
            c.put(box.y + 2, box.x, self.s("check_none"), "warn", False, box.w)
            return
        self.sys_row = max(0, min(self.sys_row, len(probes) - 1))
        passed = sum(1 for probe in probes if probe.status == "PASS")
        warned = sum(1 for probe in probes if probe.status == "WARN")
        failed = sum(1 for probe in probes if probe.status == "FAIL")
        counts = self.s("system_counts") % (passed, warned, failed)
        c.put(box.y + 1, box.x, counts, "fail" if failed else "warn" if warned else "ok",
              False, box.w)
        y = box.y + 3
        body = Box(box.x, y, box.w, max(1, box.bottom - y))
        detail_box = side
        if side is None:
            list_box, detail_box = stack_list(body, len(probes), min(9, max(4, body.h // 2)))
            if detail_box is not None:
                c.rule(detail_box.y - 1, detail_box.x, detail_box.w)
        else:
            list_box = body
        rows = self._probe_rows(probes, list_box.w)
        start = scroll_start(self.sys_row, len(rows), list_box.h)
        self._heading(c, box, self.s("system_head"), 1,
                      self._range_hint(start, list_box.h, len(rows)))
        c.rows(list_box, rows, self.sys_row, start)
        if detail_box is None or detail_box.h <= 0:
            return
        detail_rows = self._probe_detail(probes[self.sys_row], detail_box.w)
        if self.deps_data and self.deps_data.packages and detail_box.h >= 14:
            ok = sum(1 for _name, good in self.deps_data.packages if good)
            detail_rows += [Row(""), Row("─" * max(4, detail_box.w - 2), "secondary"),
                            Row(self.s("deps_title") % self.deps_data.family, "brand", True),
                            Row(self.s("deps_summary") % (ok, len(self.deps_data.packages)),
                                "secondary")]
            for name, good in self.deps_data.packages:
                detail_rows.append(Row(f"{self.theme.glyph('PASS' if good else 'FAIL')} {name}",
                                       "ok" if good else "fail"))
        c.rows(detail_box, detail_rows, None, 0, pointer=False)

    def _probe_rows(self, probes, width: int) -> list[Row]:
        names = [self.s(probe.key) for probe in probes]
        words = [self.s("status_" + probe.status.lower()) for probe in probes]
        name_w = min(24, max(_width(name) for name in names) + 4)
        word_w = max(_width(word) for word in words) + 2
        rows = []
        for index, probe in enumerate(probes):
            role = {"PASS": "ok", "WARN": "warn", "FAIL": "fail"}.get(probe.status, "text")
            text = f"{self.theme.glyph(probe.status)} {names[index]}"
            if width >= name_w + word_w + 12:
                text += " " * max(1, name_w - _width(text))
                text += words[index] + " " * max(1, word_w - _width(words[index]))
                text += probe.detail
            rows.append(Row(text, role))
        return rows

    def _probe_detail(self, probe, width: int) -> list[Row]:
        s = self.s
        role = {"PASS": "ok", "WARN": "warn", "FAIL": "fail"}.get(probe.status, "text")
        pairs = [
            (s("check_what"), s(probe.key), "secondary"),
            (s("check_status"), s("status_" + probe.status.lower()), role),
            (s("check_result"), probe.detail, "text"),
            (s("check_why"), s("why_" + probe.key), "secondary"),
            (s("check_fixable"), s("check_fix_yes") if probe.key in FIXABLE
             else s("check_fix_no"), "ok" if probe.key in FIXABLE else "warn"),
        ]
        if probe.remedy and probe.status != "PASS":
            pairs.append((s("check_remedy"), probe.remedy, "warn"))
        return self._pairs(pairs, width)

    def _pairs(self, pairs, width: int) -> list[Row]:
        rows: list[Row] = []
        for label, value, role in pairs:
            prefix = f"{label}: " if label else ""
            chunks = _wrap(prefix + value, max(10, width - 2))
            rows.append(Row(chunks[0], role))
            rows += [Row(f"  {chunk}", role) for chunk in chunks[1:]]
        return rows

    # -- options ---------------------------------------------------------
    def _options(self, c: Canvas, box: Box, side: Box | None = None) -> None:
        rows = self._options_rows()
        targets = self._option_targets(rows)
        if targets:
            self.opt_row = max(0, min(self.opt_row, len(targets) - 1))
        body = Box(box.x, box.y + 2, box.w, max(1, box.h - 2))
        display: list[Row] = []
        selected_row = 0
        target_index = 0
        for kind, key, label, value in rows:
            if kind == "group":
                display.append(Row(label, "brand", True))
                continue
            selected = target_index == self.opt_row
            if selected:
                selected_row = len(display)
            display.append(Row(self._option_line(kind, key, label, value, body.w)))
            target_index += 1
        detail_box = side
        if side is None:
            list_box, detail_box = stack_list(body, len(display),
                                              min(6, max(2, body.h // 3)))
            if detail_box is not None:
                c.rule(detail_box.y - 1, detail_box.x, detail_box.w)
        else:
            list_box = body
        start = scroll_start(selected_row, len(display), list_box.h)
        self._heading(c, box, self.s("options_head"), 2,
                      self._range_hint(start, list_box.h, len(display)))
        c.rows(list_box, display, selected_row, start)
        if detail_box is None or detail_box.h <= 0:
            return
        kind, key = self._focused_option()
        c.rows(detail_box, self._option_detail(kind, key, detail_box.w), None, 0,
               pointer=False)

    def _option_line(self, kind: str, key: str, label: str, value: str,
                     width: int) -> str:
        glyphs = self.theme.glyphs
        if kind == "core":
            mark = glyphs.ok
        elif kind in ("toggle", "app"):
            mark = glyphs.checked if self._option_on(kind, key) else glyphs.unchecked
        else:
            mark = " "
        text = f"{mark} {label}"
        if not value:
            return text
        pad = width - 3 - _width(text) - _width(value) - 2
        return f"{text}{' ' * pad}{value}" if pad > 0 else f"{text}  {value}"

    def _option_detail(self, kind: str, key: str, width: int) -> list[Row]:
        s = self.s
        desc = {"source": "detail_source", "core": "detail_core",
                "app": "detail_apps", "toggle": "detail_" + key}.get(kind, "detail_core")
        rows = [Row(chunk, "secondary") for chunk in _wrap(s(desc), max(10, width))]
        if kind == "source":
            rows += [Row(chunk, "secondary")
                     for chunk in _wrap(s("source_" + self.opts.source + "_note"),
                                        max(10, width))]
        if kind == "app":
            rows += [Row(chunk, "warn") for chunk in _wrap(s("apps_impact"), max(10, width))]
        if kind == "toggle" and key == "spatial":
            rows += [Row(chunk, "warn")
                     for chunk in _wrap(s("opt_spatial_hint"), max(10, width))]
        return rows

    # -- review ----------------------------------------------------------
    def _review(self, c: Canvas, box: Box, side: Box | None = None) -> None:
        self._heading(c, box, self.s("review_head"), 3)
        body = Box(box.x, box.y + 2, box.w, max(1, box.h - 2))
        summary = self._review_summary(body.w)
        side_rows = self._review_side(body.w)
        if side is not None:
            steps_box = body
            c.rows(side, side_rows, None, 0, pointer=False)
        else:
            steps_box = body
            summary = summary + [Row("")] + side_rows
        rows = summary + [Row("")] + self._review_steps(steps_box.w)
        rows += [Row(""), Row(self.s("review_details_on") if self.review_details
                              else self.s("review_details"), "secondary")]
        self.review_scroll = max(0, min(self.review_scroll,
                                        max(0, len(rows) - steps_box.h)))
        c.rows(steps_box, rows, None, self.review_scroll, pointer=False)

    def _review_summary(self, width: int) -> list[Row]:
        s = self.s
        sep = f" {self.theme.glyphs.sep} "
        # The same list the plan will install, so review cannot promise
        # something the backend will not do.
        apps = [s("app_" + name) for name in selected_apps(self.opts)]
        pairs = [(s("label_source"), self._source_text(), "text")]
        prepared = self.prepared
        if prepared is not None:
            # The identity the install will actually build, not the channel name.
            pairs += [(s("label_repo"), prepared.repository, "secondary"),
                      (s("label_ref"), prepared.ref, "secondary"),
                      (s("label_commit"), prepared.commit[:8], "secondary"),
                      (s("label_workspace"), str(prepared.path), "secondary"),
                      (s("label_dirty"),
                       s("review_dirty") if prepared.dirty else s("review_clean"),
                       "warn" if prepared.dirty else "ok")]
        pairs += [
            (s("label_core"), f"{s('core_shell')}{sep}{s('label_required')}", "text"),
            (s("method"), method_label(s, self.system.method), "secondary"),
            (s("label_apps"), ", ".join(apps) if apps else s("review_apps_none"), "text"),
            (s("opt_lockscreen"), s("on") if self.opts.lockscreen else s("off"), "text"),
            (s("opt_spatial"), s("on") if self.opts.spatial else s("off"), "text"),
            (s("opt_start"), s("on") if self.opts.start else s("off"), "text"),
        ]
        proxy = proxy_url()
        if proxy:
            pairs.append((s("opt_proxy"), proxy.split("://")[-1], "secondary"))
        missing = self._missing_deps()
        if missing:
            listed = ", ".join(missing[:6]) + (f" +{len(missing) - 6}" if len(missing) > 6 else "")
            pairs.append((s("label_deps"), s("review_deps_missing") % listed, "fail"))
        else:
            pairs.append((s("label_deps"), s("review_deps_ok"), "secondary"))
        rows = [Row(s("review_summary"), "brand", True), Row("")]
        rows += self._pairs(pairs, width)
        return rows

    def _review_side(self, width: int) -> list[Row]:
        s = self.s
        warnings: list[tuple[str, str]] = []
        if self.prepare_error:
            warnings.append((s("review_prepare_failed") % self.prepare_error, "fail"))
        if self.system.blocked:
            warnings.append((s("review_blocked"), "fail"))
        blocked_options = unsupported(self.system.family, self.opts)
        if blocked_options:
            warnings.append((s("review_unsupported") % ", ".join(blocked_options), "fail"))
        warnings.append((s("review_side_takeover"), "warn"))
        if self.opts.start:
            warnings.append((s("review_side_session"), "warn"))
        warnings.append((s("review_side_userpath"), "secondary"))
        warnings.append((s("review_side_log"), "secondary"))
        if self._missing_deps():
            warnings.append((s("review_skip_missing"), "warn"))
        glyphs = self.theme.glyphs
        rows = [Row(s("review_side"), "brand", True), Row("")]
        for text, role in warnings:
            mark = glyphs.info if role == "secondary" else glyphs.warn
            chunks = _wrap(text, max(8, width - 4))
            rows.append(Row(f"{mark} {chunks[0]}", role))
            rows += [Row(f"  {chunk}", role) for chunk in chunks[1:]]
        return rows

    def _review_steps(self, width: int) -> list[Row]:
        s = self.s
        rows = [Row(s("review_steps"), "brand", True)]
        if not self.steps:
            rows.append(Row(s("review_no_steps"), "warn"))
            return rows
        rows.append(Row(s("step_count") % len(self.steps), "secondary"))
        for index, step in enumerate(self.steps, 1):
            rows.append(Row(f"{index}. {step.title}", "text", True))
            if step.argv and self.review_details:
                for chunk in _wrap("$ " + " ".join(step.argv), max(10, width - 4)):
                    rows.append(Row(f"    {chunk}", "secondary"))
            elif step.argv:
                rows.append(Row(f"    {s('review_cmd')}: {step.argv[0]} "
                                f"+{max(0, len(step.argv) - 1)}", "secondary"))
            elif step.note:
                rows += [Row(f"    {chunk}", "warn")
                         for chunk in _wrap(s(step.note), max(10, width - 4))]
        return rows

    # -- installation ----------------------------------------------------
    def _stage_state(self, index: int) -> str:
        step = self.steps[index]
        if index == self.failed_index and self.result in ("failed", "cancelled"):
            return "failed"
        if index in self.skipped_steps or not step.argv:
            return "skipped"
        if index < self.step_index:
            return "done"
        if index == self.step_index and self.current is not None:
            return "running"
        return "waiting"

    def _stage_rows(self) -> list[Row]:
        glyphs = self.theme.glyphs
        marks = {"done": (glyphs.ok, "ok", "stage_done"),
                 "running": (glyphs.running, "brand", "stage_running"),
                 "failed": (glyphs.fail, "fail", "stage_failed"),
                 "skipped": (glyphs.info, "secondary", "stage_skipped"),
                 "waiting": (glyphs.info, "secondary", "stage_waiting")}
        rows = []
        for index, step in enumerate(self.steps):
            state = self._stage_state(index)
            mark, role, word = marks[state]
            rows.append(Row(f"{mark} {index + 1}. {step.title}  [{self.s(word)}]",
                            role, bold=state == "running"))
        return rows

    def _install_state(self) -> tuple[str, str]:
        if self.cancel_requested:
            return self.s("install_cancelling"), "warn"
        if self.result == "ok":
            return self.s("install_done"), "ok"
        if self.result in ("failed", "cancelled"):
            return self.s("install_failed"), "fail"
        return self.s("install_running"), "brand"

    def _installation(self, c: Canvas, box: Box, side: Box | None = None) -> None:
        self._heading(c, box, self.s("install_head"), 4)
        state, role = self._install_state()
        work = [index for index, step in enumerate(self.steps) if step.argv]
        done = sum(1 for index in work if self._stage_state(index) == "done")
        task = self.current.title if self.current else ""
        line = f"{state}{' ' + self.theme.glyphs.sep + ' ' + task}" if task else state
        c.put(box.y + 1, box.x, line, role, True, box.w)
        if self.install_started:
            elapsed = self.s("install_elapsed") % _clock(time.monotonic() - self.install_started)
            if _width(elapsed) + 4 < box.w:
                c.put(box.y + 1, box.x + box.w - _width(elapsed) - 1, elapsed,
                      "secondary", False, _width(elapsed) + 1)
        fraction: float | None = None
        label = self.s("install_no_progress")
        if work:
            if self.current is None:
                fraction = done / len(work)
                label = f"{int(fraction * 100):3d}%"
            elif self.current_progress is not None:
                # The build prints "[12/206]": that is real progress.
                fraction = (done + self.current_progress) / len(work)
                label = f"{int(fraction * 100):3d}%"
            else:
                # The step reports nothing measurable; the bar still shows the
                # steps that really finished, and says so.
                fraction = done / len(work)
                label = self.s("install_step_progress") % (done, len(work))
        bar_w = max(10, min(40, box.w - 16))
        c.bar(box.y + 2, box.x, bar_w, fraction)
        c.put(box.y + 2, box.x + bar_w + 2, label, "text" if fraction else "secondary",
              False, max(6, box.w - bar_w - 2))
        states = [self._stage_state(index) for index in range(len(self.steps))]
        # Only the states that occur, so the line fits a 50-column pane.
        counts = f" {self.theme.glyphs.sep} ".join(f"{self.s('stage_' + state)} {states.count(state)}"
                            for state in ("done", "running", "waiting", "skipped", "failed")
                            if states.count(state))
        c.put(box.y + 3, box.x, counts, "secondary", False, box.w)
        phase = ""
        if self.phase:
            phase = f"{self.s('install_stage')}: {self.phase}"
        c.put(box.y + 4, box.x, phase, "secondary", False, box.w)
        c.rule(box.y + 5, box.x, box.w)
        body = Box(box.x, box.y + 6, box.w, max(0, box.bottom - box.y - 6))
        if self.steps:
            if side is not None:
                self._stage_panel(c, body)
                self._log_panel(c, side)
            else:
                stage_h = max(2, min(len(self.steps), body.h // 3))
                stage_box, rest = split_rows(body, stage_h)
                log_box = Box(rest.x, rest.y + 1, rest.w, max(0, rest.h - 1))
                self._stage_panel(c, stage_box)
                c.rule(rest.y, rest.x, rest.w)
                self._log_panel(c, log_box)
        elif side is None:
            self._log_panel(c, body)
        else:
            self._log_panel(c, side)

    def _stage_panel(self, c: Canvas, box: Box) -> None:
        if box.h <= 0:
            return
        rows = self._stage_rows()
        focus = self.step_index if self.current is not None else 0
        c.rows(box, rows, None, scroll_start(focus, len(rows), box.h), pointer=False)

    def _log_panel(self, c: Canvas, box: Box) -> None:
        if box.h <= 1:
            return
        c.put(box.y, box.x, self.s("log_title"), "brand", False, box.w)
        status = (self.s("install_log_paused") if self.log_paused
                  else self.s("install_log_live"))
        offset = _width(self.s("log_title")) + 2
        c.put(box.y, box.x + offset, status,
              "warn" if self.log_paused else "secondary", False,
              max(4, box.w - offset))
        path_y = box.bottom - 1
        c.put(path_y, box.x, self.s("log_path") + str(self.log_path), "secondary",
              False, box.w)
        height = path_y - (box.y + 1)
        if height <= 0 or not self.log_lines:
            return
        if self.log_paused:
            start = min(self.log_scroll, max(0, len(self.log_lines) - 1))
        else:
            start = max(0, len(self.log_lines) - height)
        for offset, (level, text) in enumerate(self.log_lines[start:start + height]):
            color = {"ERROR": "fail", "WARN": "warn", "OK": "ok"}.get(level, "text")
            c.put(box.y + 1 + offset, box.x, _printable(text), color, False, box.w)

    # -- result ----------------------------------------------------------
    def _result(self, c: Canvas, box: Box, side: Box | None = None) -> None:
        ok = self.result == "ok"
        cancelled = self.result == "cancelled"
        role = "ok" if ok else "warn" if cancelled else "fail"
        if ok:
            title, status = self.s("success_title"), "PASS"
        elif cancelled:
            title, status = self.s("cancelled"), "WARN"
        else:
            title, status = self.s("failure_title"), "FAIL"
        c.put(box.y, box.x, f"{self.theme.glyph(status)} {title}", role, True, box.w)
        y = box.y + 2
        body = Box(box.x, y, box.w, max(0, box.bottom - y))
        rows = self._result_ok() if ok else self._result_failed()
        # The failure screen carries its log tail; success points at the file.
        tail = self._log_tail_rows(True) if not ok else []
        if side is not None and side.h > 0:
            c.rows(body, self._wrap_rows(rows, body.w), None, 0, pointer=False)
            c.rows(side, self._wrap_rows(tail, side.w), None, 0, pointer=False)
            return
        rows = self._wrap_rows(rows + [Row("")] + tail, body.w)
        c.rows(body, rows, None, 0, pointer=False)

    def _result_ok(self) -> list[Row]:
        s = self.s
        out: list[Row] = [Row(s("result_ran"), "brand", True)]
        skipped = [step.title for index, step in enumerate(self.steps)
                   if step.argv and self._stage_state(index) == "skipped"]
        for index, step in enumerate(self.steps):
            if not step.argv:
                continue
            state = self._stage_state(index)
            mark = self.theme.glyphs.ok if state == "done" else self.theme.glyphs.info
            out.append(Row(f"{mark} {step.title}",
                           "ok" if state == "done" else "secondary"))
        if skipped:
            out.append(Row(s("result_skipped") % ", ".join(skipped), "warn"))
        out.append(Row(""))
        out.append(Row(s("result_components"), "brand", True))
        installed = [unit for unit in self.result_units if unit.installed]
        if installed:
            out += [Row(f"  {unit.name} {unit.version}") for unit in installed]
        else:
            out.append(Row(s("result_units_none"), "secondary"))
        out.append(Row(""))
        out.append(Row(s("next_steps"), "warn"))
        out.append(Row(""))
        out.append(Row(s("log_path") + str(self.log_path), "secondary"))
        return out

    def _result_failed(self) -> list[Row]:
        s = self.s
        out: list[Row] = []
        if self.result == "cancelled":
            out.append(Row(s("result_cancelled"), "warn", True))
            if self.failed:
                out.append(Row(f"{s('cancelled')}: {self.failed.title}", "secondary"))
        elif self.failed:
            out.append(Row(f"{s('failed')}: {self.failed.title}", "fail", True))
            if self.failed_rc is not None:
                out.append(Row(f"{s('result_exit_code')}: {self.failed_rc}"))
            if self.failed.argv:
                out.append(Row(f"$ {' '.join(self.failed.argv)}", "secondary"))
            out.append(Row(f"{s('result_error')}: {self._error_summary()}", "fail"))
        out.append(Row(""))
        out.append(Row(s("result_retry_safe"), "secondary"))
        out.append(Row(s("log_path") + str(self.log_path), "secondary"))
        return out

    def _error_summary(self) -> str:
        for level, text in reversed(self.log_lines):
            if level == "ERROR":
                return text
        return self.s("result_none_logged")

    def _log_tail_rows(self, failure: bool) -> list[Row]:
        rows = [Row(self.s("result_tail") if failure else self.s("log_title"), "brand", True)]
        tail = [line for _level, line in self.log_lines[-8:]]
        if not tail:
            rows.append(Row(self.s("result_none_logged"), "secondary"))
        rows += [Row(_printable(line), "secondary") for line in tail]
        return rows

    def _wrap_rows(self, rows: list[Row], width: int) -> list[Row]:
        out: list[Row] = []
        for row in rows:
            if not row.text:
                out.append(Row(""))
                continue
            chunks = _wrap(row.text, max(10, width - 2))
            out.append(Row(chunks[0], row.role, row.bold))
            out += [Row("  " + chunk, row.role) for chunk in chunks[1:]]
        return out

    # -- manage ----------------------------------------------------------
    def _manage(self, c: Canvas, box: Box, side: Box | None = None) -> None:
        y = box.y + 2
        if not self.units:
            c.put(y, box.x, self.s("manage_empty"), "warn", False, box.w)
            y += 2
        values = self._manage_values()
        rows = [Row(f"{label}{' ' * max(1, 24 - _width(label))}{values[key]}"
                    if key in values else label)
                for key, label in self._manage_rows()]
        list_box = Box(box.x, y, box.w, max(1, box.bottom - y))
        start = scroll_start(self.row, len(rows), list_box.h)
        self._heading(c, box, self.s("row_manage"), None,
                      self._range_hint(start, list_box.h, len(rows)))
        c.rows(list_box, rows, self.row, start)
        if side is not None and side.h > 2:
            c.rows(side, [Row(chunk, "secondary")
                          for chunk in _wrap(self.s("detail_manage"), max(10, side.w))],
                   None, 0, pointer=False)

    def _units(self, c: Canvas, box: Box, side: Box | None = None) -> None:
        y = box.y + 2
        if not self.units:
            self._heading(c, box, self.s("units_title"))
            c.put(y, box.x, self.s("units_none"), "warn", False, box.w)
            return
        rows = [Row(f"{unit.name:<12} {self.s('on') if unit.installed else self.s('off'):<4} "
                    f"{unit.version:<12} {unit.paths:>3} paths")
                for unit in self.units]
        list_box = Box(box.x, y, box.w, max(1, box.bottom - y))
        start = scroll_start(self.row, len(rows), list_box.h)
        self._heading(c, box, self.s("units_title"), None,
                      self._range_hint(start, list_box.h, len(rows)))
        c.rows(list_box, rows, self.row, start)
        detail = side if side is not None else None
        if detail is None:
            return
        unit = self.units[self.row]
        lines = [Row(unit.name, "brand", True), Row("")]
        state = self.s("on") if unit.installed else self.s("off")
        if unit.installed:
            state += f" {self.theme.glyphs.sep} {unit.installed_at}"
        lines.append(Row(state, "text"))
        if unit.installed:
            lines.append(Row(f"{unit.mode} {self.theme.glyphs.sep} "
                             f"{unit.paths} paths", "secondary"))
        if unit.name == "core":
            lines.append(Row(""))
            lines += [Row(chunk, "warn") for chunk in
                      _wrap("core cannot be switched off; use uninstall.", max(10, detail.w))]
        c.rows(detail, lines, None, 0, pointer=False)

    def _snapshots(self, c: Canvas, box: Box, side: Box | None = None) -> None:
        y = box.y + 2
        c.put(y, box.x, f"[Space] {self.s('snapshots_create')}", "secondary", False, box.w)
        y += 2
        if not self.snapshots:
            self._heading(c, box, self.s("snapshots_title"))
            c.put(y, box.x, self.s("snapshots_none"), "warn", False, box.w)
            return
        list_box = Box(box.x, y, box.w, max(1, box.bottom - y))
        rows = [Row(snap.id) for snap in self.snapshots]
        start = scroll_start(self.row, len(rows), list_box.h)
        self._heading(c, box, self.s("snapshots_title"), None,
                      self._range_hint(start, list_box.h, len(rows)))
        c.rows(list_box, rows, self.row, start)
        if side is None or side.h <= 2:
            return
        snap = self.snapshots[self.row]
        lines = [Row(snap.id, "brand", True), Row(snap.created_at, "secondary"), Row("")]
        for text in (snap.note, snap.trees):
            if text:
                lines += [Row(chunk, "secondary") for chunk in _wrap(text, max(10, side.w))]
                lines.append(Row(""))
        c.rows(side, lines, None, 0, pointer=False)

    def _action(self, c: Canvas, box: Box, side: Box | None = None) -> None:
        state = {"running": self.theme.glyphs.running, "done": self.theme.glyphs.ok,
                 "failed": self.theme.glyphs.fail}.get(self.action_state, "")
        role = {"done": "ok", "failed": "fail"}.get(self.action_state, "brand")
        c.put(box.y, box.x, f"{state} {self.action_title}", role, True, box.w)
        y = box.y + 2
        height = max(0, box.bottom - y)
        for offset, (level, text) in enumerate(self.log_lines[-height:] if height else []):
            color = {"ERROR": "fail", "WARN": "warn", "OK": "ok"}.get(level, "text")
            c.put(y + offset, box.x, _printable(text), color, False, box.w)

    def _log(self, c: Canvas, box: Box, side: Box | None = None) -> None:
        if self.picker:
            list_box = Box(box.x, box.y + 2, box.w, max(1, box.h - 2))
            rows = [Row(name) for _path, name in self.picker]
            start = scroll_start(self.row, len(rows), list_box.h)
            self._heading(c, box, self.s("log_title"), None,
                          self._range_hint(start, list_box.h, len(rows)))
            c.rows(list_box, rows, self.row, start)
            return
        path = getattr(self, "log_text_path", self.log_path)
        title = self.s("log_title")
        self._heading(c, box, title)
        c.put(box.y, box.x + _width(title) + 2, str(path), "secondary", False,
              max(4, box.w - _width(title) - 2))
        y = box.y + 2
        height = max(0, box.bottom - y)
        for offset, line in enumerate(self.log_text[self.log_scroll_view:
                                                    self.log_scroll_view + height]):
            c.put(y + offset, box.x, _printable(line), "text", False, box.w)

    # -- install execution ------------------------------------------------
    def _install_loop(self, stdscr) -> None:
        stdscr.nodelay(True)
        try:
            self._install_body(stdscr)
        finally:
            stdscr.nodelay(False)

    def _toggle_pause(self) -> None:
        self.log_paused = not self.log_paused
        if self.log_paused:
            self.log_scroll = max(0, len(self.log_lines) - 1)

    def _scroll_log(self, delta: int) -> None:
        if not self.log_paused:
            self.log_paused = True
            self.log_scroll = max(0, len(self.log_lines) - 1)
        self.log_scroll = max(0, min(self.log_scroll + delta,
                                     max(0, len(self.log_lines) - 1)))

    def _install_body(self, stdscr) -> None:
        self.steps = build_plan(self.system.family, self.opts, self.paths, self.prepared)
        root = self.prepared.path if self.prepared is not None else self.root
        self.result = ""
        self.failed = None
        self.failed_rc = None
        self.failed_index = None
        self.skipped_steps = set()
        self.log_lines = []
        self.log_paused = False
        self.log_scroll = 0
        self.install_started = time.monotonic()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.paths.log_dir / time.strftime("install-%Y%m%d-%H%M%S.log")
        with self.log_path.open("w", encoding="utf-8") as log:
            log.write(f"# {self.system.label} {self.system.arch}\n")
            index = 0
            while index < len(self.steps):
                step = self.steps[index]
                self.current = step
                self.step_index = index
                self.phase = ""
                self.current_progress = None
                if not step.argv:
                    note = self.s(step.note) if step.note else "-"
                    self.log_lines.append(("WARN", f"{step.title}: {note}"))
                    self.skipped_steps.add(index)
                    index += 1
                    continue
                runner = StepRunner(step, root, log)
                runner.start()
                last_draw = 0.0
                while True:
                    line = runner.readline(0.05)
                    while line is not None:
                        self.log_lines.append((classify(line), line))
                        if len(self.log_lines) > 1000:
                            del self.log_lines[:400]
                        line = runner.readline(0.0)
                    self.phase = runner.phase
                    self.current_progress = runner.progress
                    now = time.monotonic()
                    if now - last_draw > 0.1:
                        self._draw(stdscr)
                        last_draw = now
                    ch = stdscr.getch()
                    if ch == curses.KEY_RESIZE:
                        self._draw(stdscr)
                        continue
                    if ch == 3:
                        self.cancel_requested = True
                    elif ch in (ord("p"), ord("P")):
                        self._toggle_pause()
                    elif ch in UP:
                        self._scroll_log(-1)
                    elif ch in DOWN:
                        self._scroll_log(1)
                    elif ch == curses.KEY_PPAGE:
                        self._scroll_log(-10)
                    elif ch == curses.KEY_NPAGE:
                        self._scroll_log(10)
                    if self.cancel_requested:
                        stdscr.nodelay(False)
                        answer = stdscr.getch()
                        stdscr.nodelay(True)
                        if answer in (ord("y"), ord("Y")):
                            runner.cancel()
                            self.cancel_requested = False
                            break
                        if answer in (ord("n"), ord("N"), 27):
                            self.cancel_requested = False
                    if runner.poll() is not None:
                        break
                rc = runner.close()
                self.cancel_requested = False
                if runner.cancelled:
                    self.result = "cancelled"
                    self.failed_index = index
                    if self.failed is None:
                        self.failed = step
                    self.log_lines.append(("ERROR", self.s("cancelled")))
                    return
                if rc != 0:
                    self.log_lines.append(("ERROR", f"{step.title}: exit {rc}"))
                    action = self._ask_failure(stdscr, step, rc)
                    if action == "retry":
                        continue
                    if action == "skip":
                        self.skipped_steps.add(index)
                        index += 1
                        continue
                    self.result = "failed"
                    self.failed = step
                    self.failed_rc = rc
                    self.failed_index = index
                    return
                index += 1
        self.current = None
        self.step_index = len(self.steps)
        self.result = "ok"

    def _ask_failure(self, stdscr, step: Step, rc: int) -> str:
        stdscr.nodelay(False)
        try:
            return self._ask_failure_blocking(stdscr, step, rc)
        finally:
            stdscr.nodelay(True)

    def _ask_failure_blocking(self, stdscr, step: Step, rc: int) -> str:
        while True:
            self._draw(stdscr)
            keys = (f"[r] {self.s('retry')}  [s] {self.s('skip')}  "
                    f"[a] {self.s('abort')}")
            c = Canvas(stdscr, self.theme)
            c.dialog(self.s("failure_title"),
                     [f"{step.title} ({self.s('result_exit_code')} {rc})",
                      self._error_summary()], keys)
            stdscr.noutrefresh()
            curses.doupdate()
            ch = stdscr.getch()
            if ch in (ord("r"), ord("R")):
                return "retry"
            if ch in (ord("s"), ord("S")):
                return "skip"
            if ch in (ord("a"), ord("A"), 27):
                return "abort"
