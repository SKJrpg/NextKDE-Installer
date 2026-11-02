"""Menu-driven installer and manager, in the shape archinstall uses: one list
of settings with their current values, sub-pages for the ones that need them,
and a single Install action at the bottom.

Screens: Menu, System checks, Review, Install, Result, Manage, Units,
Snapshots, Action (one command with its output), Log.
"""

from __future__ import annotations

import curses
import locale
import time
import unicodedata
from pathlib import Path

from .. import VERSION
from ..detect import System, detect, method_label
from .. import manage
from ..plan import (ALL_APPS, Options, Step, apps_missing, build_plan, git_state,
                    latest_release, proxy_url)
from ..runner import StepRunner, classify

LOGO = (
    "███╗   ██╗███████╗██╗  ██╗████████╗    ██╗  ██╗██████╗ ███████╗",
    "████╗  ██║██╔════╝╚██╗██╔╝╚══██╔══╝    ██║ ██╔╝██╔══██╗██╔════╝",
    "██╔██╗ ██║█████╗   ╚███╔╝    ██║       █████╔╝ ██║  ██║█████╗",
    "██║╚██╗██║██╔══╝   ██╔██╗    ██║       ██╔═██╗ ██║  ██║██╔══╝",
    "██║ ╚████║███████╗██╔╝ ██╗   ██║       ██║  ██╗██████╔╝███████╗",
    "╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝   ╚═╝       ╚═╝  ╚═╝╚═════╝ ╚══════╝",
)

MIN_W, MIN_H = 66, 20
_CYAN, _GREEN, _YELLOW, _RED, _DIM = 1, 2, 3, 4, 5


def _width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _clip(text: str, cells: int) -> str:
    if cells <= 0:
        return ""
    if _width(text) <= cells:
        return text
    kept, used = [], 0
    for char in text:
        width = 2 if unicodedata.east_asian_width(char) in "WF" else 1
        if used + width > cells - 1:
            break
        kept.append(char)
        used += width
    return "".join(kept) + "…"



def _wide(char: str) -> int:
    return 2 if unicodedata.east_asian_width(char) in "WF" else 1


_NO_LINE_START = "、。，；：）」』】！？!?,.;:)]}"


def _wrap(text: str, cells: int) -> list[str]:
    """Wrap by display width, without breaking Latin words or starting a line
    with CJK punctuation."""
    lines = []
    while text:
        used, cut = 0, 0
        for index, char in enumerate(text):
            if used + _wide(char) > cells:
                break
            used += _wide(char)
            cut = index + 1
        cut = max(cut, 1)
        chunk, rest = text[:cut], text[cut:]
        if rest and not rest[0].isspace() and not _is_cjk(rest[0]) and not _is_cjk(chunk[-1]):
            # A Latin word straddles the cut. Moving the whole word down beats
            # splitting "sudo" into "s" + "udo"; the nearest space is useless
            # here because mixed CJK text can be a whole phrase without one.
            word_start = len(chunk)
            while word_start > 0 and (chunk[word_start - 1].isalnum()
                                      or chunk[word_start - 1] in "-_"):
                word_start -= 1
            if 0 < len(chunk) - word_start <= 16:
                chunk, rest = text[:word_start], text[word_start:]
            else:
                space = chunk.rfind(" ")
                if space > 0 and len(chunk) - space <= 24 and not any(
                        _is_cjk(char) for char in chunk[space + 1:]):
                    chunk, rest = text[:space], text[space + 1:]
        if rest and rest[0] in _NO_LINE_START:
            chunk, rest = chunk + rest[0], rest[1:]
        lines.append(chunk.rstrip())
        text = rest.lstrip()
    return lines


def _is_cjk(char: str) -> bool:
    return unicodedata.east_asian_width(char) in "WF"


class UI:
    (WELCOME, VERSION, MENU, SYSTEM, REVIEW, INSTALL, RESULT, MANAGE, UNITS,
     SNAPSHOTS, ACTION, LOG) = range(12)

    def __init__(self, system: System, root, strings, log_dir,
                 lang_explicit: bool = False) -> None:
        self.system = system
        self.root = Path(root)
        self.s = strings
        self.log_dir = Path(log_dir)
        self.opts = Options()
        self.steps: list[Step] = build_plan(system.family, self.opts, self.root)
        self.screen = self.WELCOME
        self.row = 0
        self.lang_row = 0 if strings.lang == "zh" else 1
        self.branch_row = 0 if self.opts.source == "main" else 1
        self.welcome_row = self.lang_row
        self.latest_tag = latest_release(self.root)
        self.focus = 0  # 0 = left menu, 1 = the submenu inside the right column
        self.sub_row = 0
        self.sys_row = 0
        self.deps_row = 0
        self.apps_expanded = False
        self.rows: list[tuple[str, str, str, str]] = []
        self.log_lines: list[tuple[str, str]] = []
        self.current: Step | None = None
        self.phase = ""
        self.step_index = 0
        self.current_progress = 0.0
        self.app_deps: list[str] = []
        self.result = ""
        self.failed: Step | None = None
        self.cancel_requested = False
        self._drawn_screen = -1
        self.log_path = self.log_dir / time.strftime("install-%Y%m%d-%H%M%S.log")
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
        self.log_scroll = 0
        self.confirm = ""
        self.confirm_action = ""
        self.log_return = self.MANAGE
        branch, dirty = git_state(self.root)
        self.source_applies = branch == "main" and not dirty

    # -- entry ----------------------------------------------------------
    def run(self) -> int:
        locale.setlocale(locale.LC_ALL, "")
        return curses.wrapper(self._loop)

    def _loop(self, stdscr) -> int:
        curses.curs_set(0)
        stdscr.keypad(True)
        if curses.has_colors():
            curses.start_color()
            try:
                curses.use_default_colors()
                bg = -1
            except curses.error:
                bg = curses.COLOR_BLACK
            curses.init_pair(_CYAN, curses.COLOR_CYAN, bg)
            curses.init_pair(_GREEN, curses.COLOR_GREEN, bg)
            curses.init_pair(_YELLOW, curses.COLOR_YELLOW, bg)
            curses.init_pair(_RED, curses.COLOR_RED, bg)
            curses.init_pair(_DIM, curses.COLOR_WHITE, bg)

        while True:
            self._draw(stdscr)
            ch = stdscr.getch()
            if ch == curses.KEY_RESIZE:
                continue
            handler = {
                self.WELCOME: self._welcome_key,
                self.VERSION: self._version_key,
                self.MENU: self._menu_key,
                self.SYSTEM: self._system_key,
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
    LANGUAGES = ("zh", "en")
    SOURCES = ("main", "stable")

    def _welcome_key(self, stdscr, ch) -> int | None:
        if ch in (curses.KEY_UP, ord("k")):
            self.lang_row = (self.lang_row - 1) % len(self.LANGUAGES)
        elif ch in (curses.KEY_DOWN, ord("j")):
            self.lang_row = (self.lang_row + 1) % len(self.LANGUAGES)
        elif ch in (10, 13, curses.KEY_ENTER):
            from ..strings import Strings

            self.s = Strings(self.LANGUAGES[self.lang_row])
            self.screen = self.VERSION
        elif ch in (ord("q"), 27):
            return 0
        return None

    def _version_key(self, stdscr, ch) -> int | None:
        if ch in (curses.KEY_UP, ord("k")):
            self.branch_row = (self.branch_row - 1) % len(self.SOURCES)
        elif ch in (curses.KEY_DOWN, ord("j")):
            self.branch_row = (self.branch_row + 1) % len(self.SOURCES)
        elif ch in (10, 13, curses.KEY_ENTER):
            self.opts.source = self.SOURCES[self.branch_row]
            self.screen = self.MENU
        elif ch == 27:
            self.screen = self.WELCOME
        elif ch in (ord("q"),):
            return 0
        return None

    # -- menu -----------------------------------------------------------
    def _menu_rows(self) -> list[tuple[str, str, str, str]]:
        """(key, label, value, kind) for the fixed left column."""
        return [
            ("system", self.s("row_system"), "", "screen:SYSTEM"),
            ("settings", self.s("row_settings"), "", "menu"),
            ("manage", self.s("row_manage"), "", "screen:MANAGE"),
            ("install", self.s("row_install"), "", "review"),
        ]

    def _sub_rows(self) -> list[tuple[str, str, str, str]]:
        """Children of the focused left item, shown in the middle column."""
        key = self.rows[self.row][0] if self.rows else ""
        if key != "settings":
            return []
        rows = []
        if self.source_applies:
            rows.append(("source", self.s("opt_source"), self.opts.source, "cycle"))
        marker = " ▼" if self.apps_expanded else " ▶"
        rows += [
            ("apps", self.s("opt_apps") + marker, "", "expand"),
            *([("app:" + name,
                "  " + ("└─ " if index == len(ALL_APPS) - 1 else "├─ ")
                + self.s("app_" + name),
                self._onoff(name in self.opts.app_set), "app")
               for index, name in enumerate(ALL_APPS)] if self.apps_expanded else []),
            ("lockscreen", self.s("opt_lockscreen"), self._onoff(self.opts.lockscreen), "toggle"),
            ("spatial", self.s("opt_spatial"), self._onoff(self.opts.spatial), "toggle"),
            ("start", self.s("opt_start"), self._onoff(self.opts.start), "toggle"),
        ]
        return rows

    def _deps_summary(self) -> str:
        data = self.deps_data
        if not data or not data.packages:
            return ""
        ok = sum(1 for _name, good in data.packages if good)
        return f"{ok}/{len(data.packages)}"

    def _onoff(self, value: bool) -> str:
        return "[x]" if value else "[ ]"

    def _menu_key(self, stdscr, ch) -> int | None:
        self.rows = self._menu_rows()
        self.sub = self._sub_rows()
        if ch in (curses.KEY_PPAGE, curses.KEY_NPAGE) and self.rows \
                and self.rows[self.row][0] == "system":
            self.deps_row = max(0, self.deps_row + (-10 if ch == curses.KEY_PPAGE else 10))
            return None
        if ch in (ord("q"),):
            return 0
        if ch == 27:
            if self.focus:
                self.focus = 0
                return None
            return 0
        if ch in (curses.KEY_UP, ord("k")):
            if self.focus:
                self.sub_row = max(0, self.sub_row - 1)
            else:
                self.row = (self.row - 1) % len(self.rows)
            return None
        if ch in (curses.KEY_DOWN, ord("j")):
            if self.focus:
                self.sub_row = min(len(self.sub) - 1, self.sub_row + 1) if self.sub else 0
            else:
                self.row = (self.row + 1) % len(self.rows)
            return None
        if ch in (curses.KEY_RIGHT,):
            if not self.focus and self.sub:
                self.focus = 1
            return None
        if ch in (curses.KEY_LEFT,):
            self.focus = 0
            return None
        if ch in (ord(" "), 10, 13, curses.KEY_ENTER):
            if self.focus and self.sub:
                key, _label, _value, kind = self.sub[self.sub_row]
                if kind in ("toggle", "cycle", "app"):
                    self._cycle(key, kind)
                elif kind == "expand":
                    self.apps_expanded = not self.apps_expanded
                return None
            key, _label, _value, kind = self.rows[self.row]
            if kind == "menu":
                if self.sub:
                    self.focus = 1
                    self.sub_row = min(self.sub_row, len(self.sub) - 1)
            elif kind in ("toggle", "cycle"):
                self._cycle(key, kind)
            elif kind == "review":
                self.steps = build_plan(self.system.family, self.opts, self.root)
                self.app_deps = apps_missing(self.root) if self.opts.apps else []
                self.screen = self.REVIEW
            elif kind.startswith("screen:"):
                target = getattr(self, kind.split(":", 1)[1])
                if target == self.MANAGE:
                    self._enter_manage()
                elif target == self.SYSTEM:
                    self._load_deps()
                    self.screen = target
                else:
                    self.screen = target
            return None
        if ch == curses.KEY_F5:
            self.system = detect(root=self.root)
        return None

    def _cycle(self, key: str, kind: str) -> None:
        if key == "source":
            self.opts.source = "main" if self.opts.source == "stable" else "stable"
        elif key == "apps":
            self.opts.apps = not self.opts.apps
        elif key.startswith("app:"):
            name = key.split(":", 1)[1]
            if name in self.opts.app_set:
                self.opts.app_set.discard(name)
            else:
                self.opts.app_set.add(name)
            self.opts.apps = bool(self.opts.app_set)
        elif key == "lockscreen":
            self.opts.lockscreen = not self.opts.lockscreen
        elif key == "spatial":
            self.opts.spatial = not self.opts.spatial
        elif key == "start":
            self.opts.start = not self.opts.start

    # -- system checks --------------------------------------------------
    def _system_key(self, stdscr, ch) -> int | None:
        if ch in (curses.KEY_UP, ord("k")):
            self.sys_row = max(0, self.sys_row - 1)
        elif ch in (curses.KEY_DOWN, ord("j")):
            self.sys_row += 1
        elif ch == curses.KEY_PPAGE:
            self.deps_row = max(0, self.deps_row - 10)
        elif ch == curses.KEY_NPAGE:
            self.deps_row += 10
        elif ch in (10, 13, 27, curses.KEY_ENTER, ord("q")):
            self.screen = self.MENU
        elif ch == curses.KEY_F5:
            self.system = detect(root=self.root)
            self._load_deps()
        self.sys_row = min(self.sys_row, max(0, len(self.system.probes) - 1))
        return None

    def _load_deps(self) -> None:
        """Prefer the guide's list (docs/GettingStarted.md); kosctl is the fallback."""
        self.deps_data = manage.deps_from_docs(self.root, self.system.family or "")
        if not self.deps_data.packages:
            self.deps_data = manage.deps(self.root)
        self.deps_row = 0

    # -- review / install -----------------------------------------------
    def _review_key(self, stdscr, ch) -> int | None:
        if ch in (ord("i"), ord("I")):
            missing = [name for name, good in (self.deps_data.packages if self.deps_data else [])
                       if not good]
            if missing:
                self._run_action(stdscr, "kosctl deps --install",
                                 [manage.kosctl(self.root, "deps", "--install")], self.REVIEW)
                self._load_deps()
            return None
        if ch in (10, 13, curses.KEY_ENTER):
            self.screen = self.INSTALL
            self._install_loop(stdscr)
            self.screen = self.RESULT
        elif ch == 27:
            self.screen = self.WELCOME
        return None

    def _result_key(self, stdscr, ch) -> int | None:
        if self.result == "failed" and ch in (ord("r"), ord("R")):
            self.screen = self.INSTALL
            self._install_loop(stdscr)
            self.screen = self.RESULT
        elif ch in (ord("l"), ord("L")):
            self._open_install_log()
        elif ch in (ord("m"), ord("M")):
            self._enter_manage()
        elif ch in (10, 13, curses.KEY_ENTER, ord("q"), 27):
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

    def _enter_manage(self) -> None:
        self.units = manage.units(self.root)
        self.snapshots = manage.snapshots(self.root)
        self.row = 0
        self.screen = self.MANAGE

    def _manage_key(self, stdscr, ch) -> int | None:
        if self.confirm:
            self._resolve_confirm(stdscr, ch in (ord("y"), ord("Y")))
            return None
        rows = self._manage_rows()
        if ch in (curses.KEY_UP, ord("k")):
            self.row = (self.row - 1) % len(rows)
        elif ch in (curses.KEY_DOWN, ord("j")):
            self.row = (self.row + 1) % len(rows)
        elif ch == 27:
            self.screen = self.RESULT if self.result else self.MENU
        elif ch in (10, 13, curses.KEY_ENTER):
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
            if ch in (27, 10, 13, curses.KEY_ENTER):
                self.screen = self.MANAGE
            return None
        if ch in (curses.KEY_UP, ord("k")):
            self.row = (self.row - 1) % len(self.units)
        elif ch in (curses.KEY_DOWN, ord("j")):
            self.row = (self.row + 1) % len(self.units)
        elif ch == 27:
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
        elif ch in (10, 13, curses.KEY_ENTER):
            self.screen = self.MANAGE
        return None

    def _snapshots_key(self, stdscr, ch) -> int | None:
        if self.confirm:
            self._resolve_confirm(stdscr, ch in (ord("y"), ord("Y")))
            return None
        if ch == 27:
            self.screen = self.MANAGE
            return None
        if ch == ord(" "):
            self._run_action(stdscr, "kosctl snapshot",
                             [manage.kosctl(self.root, "snapshot", "from installer")],
                             self.SNAPSHOTS)
            return None
        if not self.snapshots:
            return None
        if ch in (curses.KEY_UP, ord("k")):
            self.row = (self.row - 1) % len(self.snapshots)
        elif ch in (curses.KEY_DOWN, ord("j")):
            self.row = (self.row + 1) % len(self.snapshots)
        elif ch in (10, 13, curses.KEY_ENTER):
            self.confirm = self.s("confirm_rollback")
            self.confirm_action = "rollback"
        return None

    def _confirm_then(self, question: str, action: str) -> None:
        if action == "uninstall":
            self._run_action("kosctl uninstall", [manage.kosctl(self.root, "uninstall")],
                             self.MANAGE)
        elif action == "rollback" and self.snapshots:
            snapshot_id = self.snapshots[self.row].id
            self._run_action(stdscr, f"kosctl rollback {snapshot_id}",
                             [manage.kosctl(self.root, "rollback", snapshot_id)],
                             self.SNAPSHOTS)
        del question

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
        self._show_log(self.log_path)

    def _open_logs(self) -> None:
        files = manage.logs(self.log_dir)
        self.log_return = self.MANAGE
        if not files:
            self.picker = []
            self.log_text = [self.s("logs_none")]
            self.log_scroll = 0
            self.screen = self.LOG
            return
        self.picker = [(str(path), path.name) for path in files]
        self.row = 0
        self.screen = self.LOG

    def _show_log(self, path: Path) -> None:  # noqa: D401 - keeps the sort order
        try:
            self.log_text = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as error:
            self.log_text = [str(error)]
        self.log_scroll = max(0, len(self.log_text) - 10)
        self.picker = []
        self.screen = self.LOG

    def _log_key(self, stdscr, ch) -> int | None:
        if self.picker:  # choosing a file
            if ch in (curses.KEY_UP, ord("k")):
                self.row = (self.row - 1) % len(self.picker)
            elif ch in (curses.KEY_DOWN, ord("j")):
                self.row = (self.row + 1) % len(self.picker)
            elif ch in (10, 13, curses.KEY_ENTER):
                self._show_log(Path(self.picker[self.row][0]))
            elif ch == 27:
                self.screen = self.MANAGE
            return None
        if ch == 27:
            self.screen = self.MANAGE if self.result != "" else self.RESULT
            return None
        if ch in (curses.KEY_UP, ord("k")):
            self.log_scroll = max(0, self.log_scroll - 1)
        elif ch in (curses.KEY_DOWN, ord("j")):
            self.log_scroll = min(max(0, len(self.log_text) - 1), self.log_scroll + 1)
        elif ch == curses.KEY_PPAGE:
            self.log_scroll = max(0, self.log_scroll - 10)
        elif ch == curses.KEY_NPAGE:
            self.log_scroll += 10
        return None

    # -- drawing ---------------------------------------------------------
    def _attr(self, color: int = 0, bold: bool = False) -> int:
        attr = curses.color_pair(color) if curses.has_colors() and color else 0
        return attr | (curses.A_BOLD if bold else 0)

    def _put(self, stdscr, y: int, x: int, text: str, attr: int = 0, width: int | None = None) -> None:
        h, w = stdscr.getmaxyx()
        if y < 0 or y >= h or x < 0 or x >= w or not text:
            return
        limit = ((w - x) if width is None else min(width, w - x)) - 1
        if limit <= 0:
            return
        try:
            stdscr.addnstr(y, x, _clip(text, limit), limit, attr)
        except curses.error:
            pass

    @staticmethod
    def _columns(width: int) -> tuple[int, int, int] | None:
        """(left width, right x, right width) or None when the terminal is narrow."""
        if width < 88:
            return None
        # Cap the whole block: on a 280-column terminal an uncapped split pushes
        # the values and the detail text to opposite edges and the columns stop
        # reading as columns.
        usable = min(width, 100)
        left = 40
        return left, left + 4, usable - left - 4

    def _detail(self, stdscr, top: int, bottom: int, x: int, width: int, lines: list[str]) -> None:
        try:
            stdscr.vline(top, x - 2, curses.ACS_VLINE, max(0, bottom - top))
        except curses.error:
            pass
        y = top
        for line in lines:
            for chunk in _wrap(line, max(1, width - 2)):
                if y >= bottom:
                    return
                self._put(stdscr, y, x, chunk, self._attr(_DIM), width)
                y += 1
            y += 0

    def _draw_confirm(self, stdscr, bottom: int, x: int, width: int) -> None:
        if self.confirm:
            self._put(stdscr, bottom - 1, x, f"{self.confirm} [y/N]",
                      self._attr(_YELLOW, True), width)

    def _draw(self, stdscr) -> None:
        if self.screen != self._drawn_screen:
            stdscr.clearok(True)
            self._drawn_screen = self.screen
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        if h < MIN_H or w < MIN_W:
            self._put(stdscr, 0, 0, self.s("title"), self._attr(_CYAN, True))
            self._put(stdscr, 2, 0, f"terminal too small: need {MIN_W}x{MIN_H}, have {w}x{h}",
                      self._attr(_YELLOW))
            stdscr.noutrefresh()
            curses.doupdate()
            return
        self._header(stdscr, h, w)
        self._footer(stdscr, h, w)
        top, bottom = 2, h - 2
        x, width = 1, w - 2
        screen = self.screen
        if screen == self.WELCOME:
            self._welcome(stdscr, top, bottom, x, width)
        elif screen == self.VERSION:
            self._version(stdscr, top, bottom, x, width)
        elif screen == self.MENU:
            self._menu(stdscr, top, bottom, x, width)
        elif screen == self.SYSTEM:
            self._system(stdscr, top, bottom, x, width)
        elif screen == self.REVIEW:
            self._review(stdscr, top, bottom, x, width)
        elif screen == self.INSTALL:
            self._installation(stdscr, top, bottom, x, width)
        elif screen == self.RESULT:
            self._result(stdscr, top, bottom, x, width)
        elif screen == self.MANAGE:
            self._manage(stdscr, top, bottom, x, width)
            self._draw_confirm(stdscr, bottom, x, width)
        elif screen == self.UNITS:
            self._units(stdscr, top, bottom, x, width)
        elif screen == self.SNAPSHOTS:
            self._snapshots(stdscr, top, bottom, x, width)
            self._draw_confirm(stdscr, bottom, x, width)
        elif screen == self.ACTION:
            self._action(stdscr, top, bottom, x, width)
        elif screen == self.LOG:
            self._log(stdscr, top, bottom, x, width)
        stdscr.noutrefresh()
        curses.doupdate()

    def _header(self, stdscr, h: int, w: int) -> None:
        # The header is a constant: it must not change when the language does.
        title = "KOS Installer"
        if self.opts.source == "main":
            branch = "main"
        else:
            branch = f"release {self.latest_tag}" if self.latest_tag else "release"
        # No installer version here: the header names the release being installed.
        self._put(stdscr, 0, 1, f"{title} · {branch}", self._attr(_CYAN, True))
        right = f"{self.system.label} · {self.system.arch}"
        self._put(stdscr, 0, max(1, w - _width(right) - 1), right, self._attr(_DIM))
        try:
            stdscr.hline(1, 0, curses.ACS_HLINE, w)
        except curses.error:
            pass

    def _footer(self, stdscr, h: int, w: int) -> None:
        try:
            stdscr.hline(h - 2, 0, curses.ACS_HLINE, w)
        except curses.error:
            pass
        if self.screen == self.WELCOME:
            self._put(stdscr, h - 1, 1, "↑↓ select · Enter continue · q quit", self._attr(_DIM))
            return
        key = {
            self.WELCOME: "hint_welcome",
            self.VERSION: "hint_version",
            self.MENU: "hint_menu",
            self.SYSTEM: "hint_system",
            self.REVIEW: "hint_review",
            self.INSTALL: "hint_install",
            self.RESULT: "hint_result",
            self.MANAGE: "hint_manage",
            self.UNITS: "hint_units",
            self.SNAPSHOTS: "hint_snapshots",
            self.ACTION: "action_hint",
            self.LOG: "log_hint",
        }.get(self.screen, "hint_menu")
        self._put(stdscr, h - 1, 1, self.s(key), self._attr(_DIM))

    def _welcome(self, stdscr, top: int, bottom: int, x: int, width: int) -> None:
        y = top + 2
        for line in LOGO:
            self._put(stdscr, y, x, line, self._attr(_CYAN, True), max(10, width))
            y += 1
        y += 2
        self._put(stdscr, y, x, "Select language", self._attr(_DIM), width)
        y += 1
        for index, lang in enumerate(self.LANGUAGES):
            focused = index == self.lang_row
            label = "中文" if lang == "zh" else "English"
            prefix = "❯ " if focused else "  "
            attr = self._attr(_CYAN, True) if focused else 0
            self._put(stdscr, y, x, f"{prefix}{label}", attr, width)
            y += 1

    def _version(self, stdscr, top: int, bottom: int, x: int, width: int) -> None:
        y = top + 2
        self._put(stdscr, y, x, self.s("welcome_version"), self._attr(_CYAN, True), width)
        y += 2
        for offset, source in enumerate(self.SOURCES):
            focused = offset == self.branch_row
            key = "branch_main" if source == "main" else "branch_release"
            label = self.s(key)
            if source != "main" and self.latest_tag:
                label = f"{label} {self.latest_tag}"
            prefix = "❯ " if focused else "  "
            attr = self._attr(_CYAN, True) if focused else 0
            self._put(stdscr, y, x, f"{prefix}{label}", attr, width)
            y += 1

    def _menu(self, stdscr, top: int, bottom: int, x: int, width: int) -> None:
        y = top + 1
        cols = self._columns(width)
        usable = min(width, 118)
        left_w = 40
        mid_x, mid_w = left_w + 4, 24
        detail_x = mid_x + mid_w + 3
        detail_w = max(20, usable - detail_x)
        self.rows = self._menu_rows()
        sub = self._sub_rows()
        rows_y = y
        for index, (key, label, value, _kind) in enumerate(self.rows):
            selected = index == self.row
            if selected and self.focus == 0:
                attr = self._attr(_CYAN, True)
            elif selected:
                attr = self._attr(_DIM)  # focus is in the submenu, not here
            else:
                attr = 0
            prefix = "❯ " if selected else "  "
            line = f"{prefix}{label}"
            if value:
                pad = max(1, left_w - _width(line) - _width(value) - 2)
                line = f"{line}{' ' * pad}{value}"
            self._put(stdscr, y, x, line, attr, left_w - 1)
            y += 1

        focused_key = self.rows[self.row][0]
        if sub:
            # The right column splits: children in the middle, their detail
            # further right. The left column never changes.
            try:
                # same span as the detail separator, or the two lines end unevenly
                stdscr.vline(rows_y, mid_x - 2, curses.ACS_VLINE, max(0, bottom - 2 - rows_y))
            except curses.error:
                pass
            sy = rows_y
            for index, (key, label, value, _kind) in enumerate(sub):
                selected = index == self.sub_row and self.focus == 1
                attr = (self._attr(_CYAN, True) if selected
                        else self._attr(_DIM) if self.focus == 0 else 0)
                prefix = "❯ " if selected else "  "
                line = f"{prefix}{label}"
                if value:
                    pad = max(1, mid_w - _width(line) - _width(value) - 2)
                    line = f"{line}{' ' * pad}{value}"
                self._put(stdscr, sy, mid_x, line, attr, mid_w - 1)
                sy += 1
            focused_key = sub[self.sub_row][0]
            value = sub[self.sub_row][2]
            detail_key = "apps" if focused_key.startswith("app:") else focused_key
            lines = [self.s(f"detail_{detail_key}")]
            if value and not value.startswith("["):
                lines += ["", f"{self.s('detail_hint')}: {value}"]
            elif detail_key == "apps":
                lines += ["", f"{len(self.opts.app_set)}/{len(ALL_APPS)}"]
            self._detail(stdscr, rows_y, bottom - 2, detail_x, detail_w, lines)
        elif cols:
            if focused_key == "system":
                # Both blocks live in this pane, split by a rule: the checks on
                # top, the packages below (PgUp/PgDn scrolls the lower half).
                lines = []
                for probe in self.system.probes:
                    glyph = {"PASS": "✔", "WARN": "⚠", "FAIL": "✖"}.get(probe.status, "·")
                    lines.append(f"{glyph} {self.s(probe.key)}: {probe.detail}")
                data = self.deps_data
                if data and data.packages:
                    ok = sum(1 for _name, good in data.packages if good)
                    lines += ["", "─" * max(10, detail_w - 4),
                              f"{self.s('deps_title') % data.family}  "
                              f"{self.s('deps_summary') % (ok, len(data.packages))}"]
                    lines += [f"{'✔' if good else '✖'} {name}"
                              for name, good in data.packages[self.deps_row:]]
            else:
                lines = [self.s(f"detail_{focused_key}")]
            self._detail(stdscr, rows_y, bottom - 2, left_w + 4, detail_w, lines)

        y = max(y, rows_y + len(self.rows)) + 1
        self._put(stdscr, y, x, self.s("review_target"), self._attr(_DIM), width)
        y += 1
        proxy = proxy_url()
        if proxy:
            self._put(stdscr, y, x, f"{self.s('opt_proxy')}: {proxy.split('://')[-1]}",
                      self._attr(_DIM), width)

    def _system(self, stdscr, top: int, bottom: int, x: int, width: int) -> None:
        y = top + 1
        self._put(stdscr, y, x, self.s("system_title"), self._attr(_CYAN, True), width)
        y += 2
        probes = self.system.probes
        self.sys_row = min(self.sys_row, max(0, len(probes) - 1))
        cols = self._columns(width)
        left_w = cols[0] if cols else width
        value_col = min(28, max((_width(f"  {self.s(probe.key)}") for probe in probes),
                               default=0) + 3)
        for index, probe in enumerate(probes):
            selected = index == self.sys_row
            color = {"PASS": _GREEN, "WARN": _YELLOW, "FAIL": _RED}.get(probe.status, 0)
            glyph = {"PASS": "✔", "WARN": "⚠", "FAIL": "✖"}.get(probe.status, "·")
            prefix = "❯ " if selected else "  "
            line = f"{prefix}{glyph} {self.s(probe.key)}"
            pad = 2 if _width(line) >= value_col else value_col - _width(line)
            attr = self._attr(_CYAN, True) if selected else self._attr(color)
            self._put(stdscr, y, x, f"{line}{' ' * pad}{probe.detail}", attr, left_w - 1)
            y += 1

        if not cols:
            return
        _left, right_x, right_w = cols
        try:
            stdscr.vline(top, right_x - 2, curses.ACS_VLINE, max(0, bottom - top))
        except curses.error:
            pass
        # Upper half: why the focused check matters.
        ry = top + 3
        probe = probes[self.sys_row] if probes else None
        if probe is not None:
            for chunk in _wrap(self.s(f"why_{probe.key}"), max(10, right_w - 2)):
                if ry >= bottom - 10:
                    break
                self._put(stdscr, ry, right_x, chunk, self._attr(_DIM), right_w)
                ry += 1
            if probe.remedy and probe.status != "PASS":
                for chunk in _wrap(probe.remedy, max(10, right_w - 2)):
                    if ry >= bottom - 10:
                        break
                    self._put(stdscr, ry, right_x, chunk, self._attr(_YELLOW), right_w)
                    ry += 1
        # Rule between the two halves.
        try:
            stdscr.hline(ry + 1, right_x, curses.ACS_HLINE, max(1, right_w - 1))
        except curses.error:
            pass
        ry += 2
        data = self.deps_data
        if not data or not data.packages:
            self._put(stdscr, ry, right_x, self.s("deps_empty"), self._attr(_YELLOW), right_w)
            return
        ok = sum(1 for _name, good in data.packages if good)
        self._put(stdscr, ry, right_x,
                  f"{self.s('deps_title') % data.family}  "
                  f"{self.s('deps_summary') % (ok, len(data.packages))}",
                  self._attr(_CYAN, True), right_w)
        ry += 1
        height = max(1, bottom - ry - 1)
        start = min(self.deps_row, max(0, len(data.packages) - height))
        for name, good in data.packages[start:start + height]:
            self._put(stdscr, ry, right_x, f"{'✔' if good else '✖'} {name}",
                      self._attr(_GREEN if good else _RED), right_w)
            ry += 1
        if len(data.packages) > height:
            self._put(stdscr, bottom - 1, right_x, self.s("deps_scroll_hint"),
                      self._attr(_DIM), right_w)

    def _review(self, stdscr, top: int, bottom: int, x: int, width: int) -> None:
        y = top + 1
        self._put(stdscr, y, x, self.s("review_title"), self._attr(_CYAN, True), width)
        y += 2
        if self.opts.apps:
            if self.app_deps:
                self._put(stdscr, y, x, f"{self.s('review_apps_missing')}: {', '.join(self.app_deps)}",
                          self._attr(_YELLOW), width)
            else:
                self._put(stdscr, y, x, self.s("review_apps_ok"), self._attr(_DIM), width)
            y += 1
        missing = [name for name, good in (self.deps_data.packages if self.deps_data else [])
                   if not good]
        if missing:
            listed = ", ".join(missing[:6]) + (f" +{len(missing) - 6}" if len(missing) > 6 else "")
            self._put(stdscr, y, x, self.s("review_deps_missing") % listed, self._attr(_RED), width)
            y += 1
            self._put(stdscr, y, x, self.s("review_deps_hint"), self._attr(_CYAN), width)
            y += 1
        elif self.deps_data and self.deps_data.packages:
            self._put(stdscr, y, x, self.s("review_deps_ok"), self._attr(_DIM), width)
            y += 1
        if not self.steps:
            self._put(stdscr, y, x, self.s("review_none"), self._attr(_YELLOW), width)
            return
        self._put(stdscr, y, x, self.s("review_warn"), 0, width)
        y += 1
        for index, step in enumerate(self.steps, 1):
            if y >= bottom - 1:
                break
            self._put(stdscr, y, x, f"{index}. {step.title}", 0, width)
            y += 1
            if step.argv:
                self._put(stdscr, y, x + 3, "$ " + " ".join(step.argv), self._attr(_DIM),
                          max(10, width - 3))
                y += 1
            elif step.note:
                self._put(stdscr, y, x + 3, self.s(step.note), self._attr(_YELLOW),
                          max(10, width - 3))
                y += 1
        y += 1
        self._put(stdscr, y, x, self.s("review_takeover_short"), self._attr(_DIM), width)

    def _installation(self, stdscr, top: int, bottom: int, x: int, width: int) -> None:
        work = [step for step in self.steps if step.argv]
        total = len(work)
        done = sum(1 for step in self.steps[: self.step_index] if step.argv)
        fraction = (done + self.current_progress) / total if total else 0.0
        task = self.current.title if self.current else self.s("phase_idle")
        self._put(stdscr, top, x, self.s("install_title"), self._attr(_CYAN, True), width)
        self._put(stdscr, top, x + max(20, width - 8), f"{done}/{total}", self._attr(_DIM), 8)
        self._put(stdscr, top + 1, x, task, 0, width)
        if self.phase:
            self._put(stdscr, top + 1, x + _width(task) + 2, f"· {self.phase}",
                      self._attr(_DIM), max(6, width - _width(task) - 3))
        bar_w = max(10, min(width - 8, 48))
        filled = int(bar_w * fraction)
        self._put(stdscr, top + 2, x, "█" * filled + "░" * (bar_w - filled),
                  self._attr(_CYAN), bar_w + 1)
        self._put(stdscr, top + 2, x + bar_w + 2, f"{int(100 * fraction):>3}%", self._attr(_DIM), 6)
        log_top = top + 5
        height = max(3, bottom - log_top)
        for offset, (level, text) in enumerate(self.log_lines[-height:]):
            color = {"ERROR": _RED, "WARN": _YELLOW, "OK": _GREEN}.get(level, 0)
            self._put(stdscr, log_top + offset, x, text, self._attr(color), width)
        if self.cancel_requested:
            self._put(stdscr, bottom - 1, x, self.s("cancel_confirm") + " [y/N]",
                      self._attr(_YELLOW, True), width)

    def _result(self, stdscr, top: int, bottom: int, x: int, width: int) -> None:
        ok = self.result == "ok"
        title = self.s("success_title") if ok else self.s("failure_title")
        self._put(stdscr, top + 1, x, ("✅ " if ok else "❌ ") + title,
                  self._attr(_GREEN if ok else _RED, True), width)
        y = top + 3
        self._put(stdscr, y, x, self.s("log_hint") + str(self.log_path), self._attr(_DIM), width)
        y += 2
        if ok:
            self._put(stdscr, y, x, self.s("next_steps"), 0, width)
            y += 2
            self._put(stdscr, y, x, "./tools/kosctl start", self._attr(_CYAN), width)
            y += 1
            self._put(stdscr, y, x, "./tools/kosctl version", 0, width)
            y += 2
            self._put(stdscr, y, x, "[m] manage  [l] log  [Enter] quit", self._attr(_CYAN), width)
        else:
            if self.failed:
                self._put(stdscr, y, x, f"{self.s('failed')}: {self.failed.title}",
                          self._attr(_RED), width)
                y += 1
                self._put(stdscr, y, x + 2, "$ " + " ".join(self.failed.argv), self._attr(_DIM),
                          width)
                y += 1
            self._put(stdscr, y + 1, x, f"[r] {self.s('retry')}  [l] log  [m] manage  [Enter] {self.s('quit')}",
                      self._attr(_CYAN), width)
        y += 2
        for line in [line for _level, line in self.log_lines[-5:]]:
            if y < bottom:
                self._put(stdscr, y, x, line, self._attr(_DIM), width)
                y += 1

    def _manage(self, stdscr, top: int, bottom: int, x: int, width: int) -> None:
        y = top + 1
        self._put(stdscr, y, x, self.s("row_manage"), self._attr(_CYAN, True), width)
        y += 2
        if not self.units:
            self._put(stdscr, y, x, self.s("manage_empty"), self._attr(_YELLOW), width)
            y += 2
        rows = self._manage_rows()
        for index, (_key, label) in enumerate(rows):
            selected = index == self.row
            attr = self._attr(_CYAN, True) if selected else 0
            prefix = "❯ " if selected else "  "
            value = ""
            if _key == "units":
                value = f"{len(self.units)}"
            elif _key == "snapshots":
                value = f"{len(self.snapshots)}"
            line = f"{prefix}{label}"
            if value:
                panel = min(width, 78)
                pad = max(2, panel - _width(line) - _width(value) - 2)
                line = f"{line}{' ' * pad}{value}"
            self._put(stdscr, y, x, line, attr, width)
            y += 1

    def _units(self, stdscr, top: int, bottom: int, x: int, width: int) -> None:
        y = top + 1
        cols = self._columns(width)
        self._put(stdscr, y, x, self.s("units_title"), self._attr(_CYAN, True), width)
        y += 2
        if not self.units:
            self._put(stdscr, y, x, self.s("units_none"), self._attr(_YELLOW), width)
            return
        left_w = cols[0] if cols else min(width, 60)
        for index, unit in enumerate(self.units):
            selected = index == self.row
            attr = self._attr(_CYAN, True) if selected else 0
            prefix = "❯ " if selected else "  "
            state = self.s("on") if unit.installed else self.s("off")
            version = unit.version if unit.installed else "-"
            line = (f"{prefix}{unit.name:<12} {state:<4} {version:<12} {unit.paths:>3} paths")
            self._put(stdscr, y, x, line, attr, left_w)
            y += 1
        if cols:
            _left, right_x, right_w = cols
            unit = self.units[self.row]
            detail = [f"{unit.name}", ""]
            detail.append(f"{self.s('on') if unit.installed else self.s('off')}"
                          + (f" · {unit.installed_at}" if unit.installed else ""))
            if unit.installed:
                detail.append(f"{unit.mode} · {unit.paths} paths")
                if unit.name == "core":
                    detail.append("")
                    detail.append("core cannot be switched off; use uninstall.")
                else:
                    detail.append("")
                    detail.append("Space: off removes exactly the recorded paths.")
            self._detail(stdscr, top + 4, bottom - 2, right_x, right_w, detail)

    def _snapshots(self, stdscr, top: int, bottom: int, x: int, width: int) -> None:
        y = top + 1
        cols = self._columns(width)
        self._put(stdscr, y, x, self.s("snapshots_title"), self._attr(_CYAN, True), width)
        y += 2
        self._put(stdscr, y, x, f"[Space] {self.s('snapshots_create')}", self._attr(_DIM), width)
        y += 2
        if not self.snapshots:
            self._put(stdscr, y, x, self.s("snapshots_none"), self._attr(_YELLOW), width)
            return
        left_w = cols[0] if cols else min(width, 60)
        for index, snap in enumerate(self.snapshots):
            selected = index == self.row
            attr = self._attr(_CYAN, True) if selected else 0
            prefix = "❯ " if selected else "  "
            self._put(stdscr, y, x, f"{prefix}{snap.id}", attr, left_w)
            y += 1
        if cols:
            _left, right_x, right_w = cols
            snap = self.snapshots[self.row]
            detail = [snap.id, "", snap.created_at]
            if snap.note:
                detail += ["", snap.note]
            if snap.trees:
                detail += ["", snap.trees]
            self._detail(stdscr, top + 4, bottom - 2, right_x, right_w, detail)

    def _action(self, stdscr, top: int, bottom: int, x: int, width: int) -> None:
        y = top + 1
        state = {"running": "…", "done": "✅", "failed": "❌"}.get(self.action_state, "")
        color = {"done": _GREEN, "failed": _RED}.get(self.action_state, _CYAN)
        self._put(stdscr, y, x, f"{state} {self.action_title}", self._attr(color, True), width)
        y += 2
        height = max(3, bottom - y)
        for offset, (level, text) in enumerate(self.log_lines[-height:]):
            line_color = {"ERROR": _RED, "WARN": _YELLOW, "OK": _GREEN}.get(level, 0)
            self._put(stdscr, y + offset, x, text, self._attr(line_color), width)

    def _log(self, stdscr, top: int, bottom: int, x: int, width: int) -> None:
        y = top + 1
        if self.picker:
            self._put(stdscr, y, x, self.s("log_title"), self._attr(_CYAN, True), width)
            y += 2
            for index, (_path, name) in enumerate(self.picker):
                selected = index == self.row
                attr = self._attr(_CYAN, True) if selected else 0
                self._put(stdscr, y, x, ("▶ " if selected else "  ") + name, attr, width)
                y += 1
            return
        self._put(stdscr, y, x, self.s("log_title"), self._attr(_CYAN, True), width)
        y += 2
        height = max(3, bottom - y)
        for offset, line in enumerate(self.log_text[self.log_scroll:self.log_scroll + height]):
            self._put(stdscr, y + offset, x, line, 0, width)

    # -- install execution ------------------------------------------------
    def _install_loop(self, stdscr) -> None:
        stdscr.nodelay(True)
        try:
            self._install_body(stdscr)
        finally:
            stdscr.nodelay(False)

    def _install_body(self, stdscr) -> None:
        self.steps = build_plan(self.system.family, self.opts, self.root)
        self.result = ""
        self.failed = None
        self.log_lines = []
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / time.strftime("install-%Y%m%d-%H%M%S.log")
        with self.log_path.open("w", encoding="utf-8") as log:
            log.write(f"# {self.system.label} {self.system.arch}\n")
            index = 0
            while index < len(self.steps):
                step = self.steps[index]
                self.current = step
                self.step_index = index
                self.phase = ""
                self.current_progress = 0.0
                if not step.argv:
                    note = self.s(step.note) if step.note else "-"
                    self.log_lines.append(("WARN", f"{step.title}: {note}"))
                    index += 1
                    continue
                runner = StepRunner(step, self.root, log)
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
                    self.current_progress = runner.progress or 0.0
                    now = time.monotonic()
                    if now - last_draw > 0.1:
                        self._draw(stdscr)
                        last_draw = now
                    ch = stdscr.getch()
                    if ch == curses.KEY_RESIZE:
                        continue
                    if ch == 3:
                        self.cancel_requested = True
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
                    self.log_lines.append(("ERROR", self.s("cancelled")))
                    return
                if rc != 0:
                    self.log_lines.append(("ERROR", f"{step.title}: exit {rc}"))
                    action = self._ask_failure(stdscr, step, rc)
                    if action == "retry":
                        continue
                    if action == "skip":
                        index += 1
                        continue
                    self.result = "failed"
                    self.failed = step
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
            h, w = stdscr.getmaxyx()
            prompt = (f"[{self.s('failed')}] {step.title} (exit {rc})  "
                      f"[r] {self.s('retry')}  [s] {self.s('skip')}  [a] {self.s('abort')}")
            self._put(stdscr, h - 3, 1, prompt, self._attr(_RED, True), w - 2)
            stdscr.noutrefresh()
            curses.doupdate()
            ch = stdscr.getch()
            if ch in (ord("r"), ord("R")):
                return "retry"
            if ch in (ord("s"), ord("S")):
                return "skip"
            if ch in (ord("a"), ord("A"), 27):
                return "abort"
