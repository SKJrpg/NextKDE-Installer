"""Dashboard renderer: one curses screen at a time, driven by the same plan."""

from __future__ import annotations

import curses
import locale
import time
import unicodedata
from pathlib import Path

from .. import VERSION
from ..detect import System, detect, method_label
from ..plan import Options, Step, build_plan, proxy_url
from ..runner import StepRunner, classify


LOGO = (
    "███╗   ██╗███████╗██╗  ██╗████████╗    ██╗  ██╗██████╗ ███████╗",
    "████╗  ██║██╔════╝╚██╗██╔╝╚══██╔══╝    ██║ ██╔╝██╔══██╗██╔════╝",
    "██╔██╗ ██║█████╗   ╚███╔╝    ██║       █████╔╝ ██║  ██║█████╗",
    "██║╚██╗██║██╔══╝   ██╔██╗    ██║       ██╔═██╗ ██║  ██║██╔══╝",
    "██║ ╚████║███████╗██╔╝ ██╗   ██║       ██║  ██╗██████╔╝███████╗",
    "╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝   ╚═╝       ╚═╝  ╚═╝╚═════╝ ╚══════╝",
)

SIDEBAR = 24
MIN_W, MIN_H = 66, 20

_CYAN, _GREEN, _YELLOW, _RED, _DIM = 1, 2, 3, 4, 5


def _display_width(text: str) -> int:
    """Terminal cells a string occupies (CJK counts as two)."""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _clip(text: str, cells: int) -> str:
    """Cut text to the cells available; curses would otherwise wrap it out of frame."""
    if cells <= 0:
        return ""
    if _display_width(text) <= cells:
        return text
    kept, used = [], 0
    for char in text:
        width = 2 if unicodedata.east_asian_width(char) in "WF" else 1
        if used + width > cells - 1:
            break
        kept.append(char)
        used += width
    return "".join(kept) + "…"


class UI:
    def __init__(self, system: System, root: Path, strings, log_dir: Path) -> None:
        self.system = system
        self.root = Path(root)
        self.s = strings
        self.log_dir = Path(log_dir)
        self.opts = Options()
        self.steps: list[Step] = build_plan(system.family, self.opts, self.root)
        self.screen = 0
        self.row = 0
        self.log_lines: list[tuple[str, str]] = []
        self.current: Step | None = None
        self.phase = ""
        self.step_index = 0
        self.result = ""
        self.failed: Step | None = None
        self.visited: set[int] = set()
        self.spin = 0
        self.log_path = self.log_dir / time.strftime("install-%Y%m%d-%H%M%S.log")
        self.cancel_requested = False
        self._drawn_screen = -1

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
            if ch in (curses.KEY_F5,) and self.screen == 1:
                self.system = detect()
                self.steps = build_plan(self.system.family, self.opts, self.root)
                continue
            if ch in (ord("q"), 27) and self.screen in (0, 5):
                return self._exit_code()
            if self.screen == 0:
                if ch in (10, 13, curses.KEY_ENTER):
                    self.screen = 1
                elif ch in (ord("q"), 27):
                    return 0
            elif self.screen == 1:
                if ch in (10, 13, curses.KEY_ENTER):
                    self.screen = 2
                    self.visited.add(1)
                elif ch == 27:
                    self.screen = 0
            elif self.screen == 2:
                if ch in (10, 13, curses.KEY_ENTER):
                    self.steps = build_plan(self.system.family, self.opts, self.root)
                    self.screen = 3
                    self.visited.add(2)
                elif ch == 27:
                    self.screen = 1
                else:
                    self._options_key(ch)
            elif self.screen == 3:
                if ch in (10, 13, curses.KEY_ENTER):
                    self.visited.add(3)
                    self.screen = 4
                    self._install_loop(stdscr)
                    self.screen = 5
                elif ch == 27:
                    self.screen = 2
            else:  # result
                if self.result == "failed" and ch in (ord("r"), ord("R")):
                    self.screen = 4
                    self._install_loop(stdscr)
                    self.screen = 5
                elif ch in (10, 13, curses.KEY_ENTER, ord("q"), 27):
                    return self._exit_code()

    def _exit_code(self) -> int:
        if self.result == "ok":
            return 0
        if self.result == "cancelled":
            return 130
        return 1 if self.result == "failed" else 0

    # -- drawing --------------------------------------------------------
    def _attr(self, color: int = 0, bold: bool = False) -> int:
        attr = curses.color_pair(color) if curses.has_colors() and color else 0
        return attr | (curses.A_BOLD if bold else 0)

    def _put(self, stdscr, y: int, x: int, text: str, attr: int = 0, width: int | None = None) -> None:
        h, w = stdscr.getmaxyx()
        if y < 0 or y >= h or x < 0 or x >= w or not text:
            return
        limit = (w - x) if width is None else min(width, w - x)
        limit -= 1
        if limit <= 0:
            return
        text = _clip(text, limit)
        try:
            stdscr.addnstr(y, x, text, limit, attr)
        except curses.error:
            pass

    def _draw(self, stdscr) -> None:
        if self.screen != self._drawn_screen:
            # A screen change replaces the whole view; without this, curses
            # "optimises" the repaint into scrolls and leaves stale rows.
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
        body_top, body_bottom = 2, h - 2
        sidebar = SIDEBAR if (w >= 100 and self.screen != 0) else 0
        if sidebar:
            self._sidebar(stdscr, body_top, body_bottom, sidebar)
        x = sidebar + 2 if sidebar else 1
        width = w - x - 1
        screen = self.screen
        if screen == 0:
            self._welcome(stdscr, body_top, body_bottom, x, width)
        elif screen == 1:
            self._environment(stdscr, body_top, body_bottom, x, width)
        elif screen == 2:
            self._options(stdscr, body_top, body_bottom, x, width)
        elif screen == 3:
            self._review(stdscr, body_top, body_bottom, x, width)
        elif screen == 4:
            self._installation(stdscr, body_top, body_bottom, x, width)
        else:
            self._result(stdscr, body_top, body_bottom, x, width)
        stdscr.noutrefresh()
        curses.doupdate()

    def _header(self, stdscr, h: int, w: int) -> None:
        self._put(stdscr, 0, 1, f"{self.s('title')} 0.1", self._attr(_CYAN, True))
        right = f"{self.system.label} · {self.system.arch}"
        self._put(stdscr, 0, max(1, w - len(right) - 1), right, self._attr(_DIM))
        try:
            stdscr.hline(1, 0, curses.ACS_HLINE, w)
        except curses.error:
            pass

    def _footer(self, stdscr, h: int, w: int) -> None:
        try:
            stdscr.hline(h - 2, 0, curses.ACS_HLINE, w)
        except curses.error:
            pass
        self._put(stdscr, h - 1, 1, self.s(self._hint_key()), self._attr(_DIM))

    def _hint_key(self) -> str:
        return {
            0: "hint_welcome",
            1: "hint_environment",
            2: "hint_options",
            3: "hint_review",
            4: "hint_install",
        }.get(self.screen, "hint_result")

    def _sidebar(self, stdscr, top: int, bottom: int, width: int) -> None:
        steps = [
            (1, "env_title"),
            (2, "options_title"),
            (3, "review_title"),
            (4, "install_title"),
            (5, "success_title"),
        ]
        y = top + 1
        for index, key in steps:
            if index == self.screen:
                glyph, attr = "◐", self._attr(_CYAN, True)
            elif index == 4 and self.result == "failed":
                glyph, attr = "✖", self._attr(_RED)
            elif index in self.visited:
                glyph, attr = "✔", self._attr(_GREEN)
            else:
                glyph, attr = "○", self._attr(_DIM)
            self._put(stdscr, y, 2, f"{glyph} {self.s(key)}", attr, width - 3)
            y += 1
        y += 1
        self._put(stdscr, y, 2, self.s("method"), self._attr(_DIM), width - 3)
        self._put(stdscr, y + 1, 2, self.system.family or "unknown", self._attr(_CYAN), width - 3)
        try:
            stdscr.vline(top, width, curses.ACS_VLINE, bottom - top)
        except curses.error:
            pass

    def _welcome(self, stdscr, top: int, bottom: int, x: int, width: int) -> None:
        y = top + 2
        for line in LOGO:
            self._put(stdscr, y, x, line, self._attr(_CYAN, True), max(10, width))
            y += 1
        y += 1
        self._put(stdscr, y, x, self.s("subtitle"), self._attr(_DIM), width)
        y += 2
        rows = (
            (self.s("label_system"), f"{self.system.label} · {self.system.arch}"),
            (self.s("method"), method_label(self.s, self.system.method)),
            (self.s("label_target"), self.s("target_value")),
        )
        for label, value in rows:
            pad = " " * max(1, 10 - _display_width(label))
            self._put(stdscr, y, x, label + pad, self._attr(_DIM), 11)
            self._put(stdscr, y, x + 10, value, 0, max(10, width - 10))
            y += 1
        y += 2
        self._put(stdscr, y, x, f"Enter  {self.s('start')}", self._attr(_CYAN, True), width)
        self._put(stdscr, y + 1, x, f"q      {self.s('quit')}", self._attr(_DIM), width)

    def _environment(self, stdscr, top: int, bottom: int, x: int, width: int) -> None:
        y = top
        self._put(stdscr, y, x, self.s("env_title"), self._attr(_CYAN, True), width)
        y += 2
        colors = {"PASS": _GREEN, "WARN": _YELLOW, "FAIL": _RED}
        for probe in self.system.probes:
            if y >= bottom:
                break
            color = colors.get(probe.status, 0)
            self._put(stdscr, y, x, f"[{probe.status}]", self._attr(color, True), 7)
            self._put(stdscr, y, x + 8, f"{self.s(probe.key)}: {probe.detail}", 0,
                      max(10, width - 9))
            y += 1
            if probe.status != "PASS" and probe.remedy and y < bottom:
                self._put(stdscr, y, x + 8, probe.remedy, self._attr(_DIM), max(10, width - 9))
                y += 1
        y += 1
        if y < bottom:
            self._put(stdscr, y, x, self.s("method") + ": " + method_label(self.s, self.system.method),
                      self._attr(_CYAN), width)

    def _options(self, stdscr, top: int, bottom: int, x: int, width: int) -> None:
        rows = [
            ("opt_source", self.opts.source, "source"),
            ("opt_apps", self._onoff(self.opts.apps), "apps"),
            ("opt_lockscreen", self._onoff(self.opts.lockscreen), "lockscreen"),
            ("opt_start", self._onoff(self.opts.start), "start"),
            ("opt_all", self._onoff(self.opts.install_all), "all"),
            ("opt_proxy", self._proxy_label(), "proxy"),
        ]
        y = top
        self._put(stdscr, y, x, self.s("options_title"), self._attr(_CYAN, True), width)
        y += 2
        for index, (key, value, _name) in enumerate(rows):
            disabled = index == 5 and not proxy_url()
            if index == self.row and not disabled:
                attr = self._attr(_CYAN, True)
            elif disabled:
                attr = self._attr(_DIM)
            else:
                attr = 0
            prefix = "▶ " if index == self.row else "  "
            self._put(stdscr, y, x, f"{prefix}{self.s(key)}: {value}", attr, width)
            y += 1
        y += 1

    def _review(self, stdscr, top: int, bottom: int, x: int, width: int) -> None:
        y = top
        self._put(stdscr, y, x, self.s("review_title"), self._attr(_CYAN, True), width)
        y += 2
        if not self.steps:
            self._put(stdscr, y, x, self.s("review_none"), self._attr(_YELLOW), width)
            return
        self._put(stdscr, y, x, self.s("review_warn"), self._attr(_DIM), width)
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

    def _installation(self, stdscr, top: int, bottom: int, x: int, width: int) -> None:
        total = len(self.steps)
        done = min(self.step_index, total)
        task = self.current.title if self.current else self.s("phase_idle")
        self._put(stdscr, top, x, self.s("install_title"), self._attr(_CYAN, True), width)
        self._put(stdscr, top, x + max(20, width - 8), f"{done}/{total}", self._attr(_DIM), 8)
        self._put(stdscr, top + 1, x, task, 0, width)
        if self.phase:
            self._put(stdscr, top + 1, x + len(task) + 2, f"· {self.phase}", self._attr(_DIM),
                      max(6, width - len(task) - 3))
        bar_w = max(10, min(width - 8, 48))
        filled = int(bar_w * (done / total)) if total else 0
        bar = "█" * filled + "░" * (bar_w - filled)
        self._put(stdscr, top + 2, x, bar, self._attr(_CYAN), bar_w + 1)
        percent = int(100 * done / total) if total else 0
        self._put(stdscr, top + 2, x + bar_w + 2, f"{percent:>3}%", self._attr(_DIM), 6)

        log_top = top + 5
        height = max(3, bottom - log_top)
        visible = self.log_lines[-height:]
        for offset, (level, text) in enumerate(visible):
            color = {"ERROR": _RED, "WARN": _YELLOW, "OK": _GREEN}.get(level, 0)
            self._put(stdscr, log_top + offset, x, text, self._attr(color), width)

        if self.cancel_requested:
            self._put(stdscr, bottom - 1, x, self.s("cancel_confirm") + " [y/N]",
                      self._attr(_YELLOW, True), width)

    def _result(self, stdscr, top: int, bottom: int, x: int, width: int) -> None:
        ok = self.result == "ok"
        title = self.s("success_title") if ok else self.s("failure_title")
        self._put(stdscr, top, x, ("✔ " if ok else "✖ ") + title,
                  self._attr(_GREEN if ok else _RED, True), width)
        y = top + 2
        self._put(stdscr, y, x, self.s("log_hint") + str(self.log_path), self._attr(_DIM), width)
        y += 2
        if ok:
            self._put(stdscr, y, x, self.s("next_steps"), 0, width)
            y += 2
            self._put(stdscr, y, x, "./tools/kosctl start", self._attr(_CYAN), width)
            y += 1
            self._put(stdscr, y, x, "./tools/kosctl version", 0, width)
        else:
            if self.failed:
                self._put(stdscr, y, x, f"{self.s('failed')}: {self.failed.title}", self._attr(_RED), width)
                y += 1
                self._put(stdscr, y, x + 2, "$ " + " ".join(self.failed.argv), self._attr(_DIM), width)
                y += 1
            self._put(stdscr, y + 1, x,
                      f"[r] {self.s('retry')}  [Enter] {self.s('quit')}",
                      self._attr(_CYAN), width)
        y += 2
        tail = [line for _level, line in self.log_lines[-6:]]
        for line in tail:
            if y < bottom:
                self._put(stdscr, y, x, line, self._attr(_DIM), width)
                y += 1

    # -- interaction ----------------------------------------------------
    def _onoff(self, value: bool) -> str:
        return self.s("on") if value else self.s("off")

    def _proxy_label(self) -> str:
        url = proxy_url()
        if not url:
            return self.s("unset")
        return f"{self._onoff(self.opts.proxy)} · {url.split('://')[-1]}"

    def _options_key(self, ch: int) -> None:
        if ch in (curses.KEY_UP, ord("k")):
            self.row = (self.row - 1) % 6
        elif ch in (curses.KEY_DOWN, ord("j")):
            self.row = (self.row + 1) % 6
        elif ch in (ord(" "), 10, 13):
            self._toggle(self.row)
        elif ch in (curses.KEY_LEFT, curses.KEY_RIGHT):
            if self.row == 0:
                self.opts.source = "main" if self.opts.source == "stable" else "stable"

    def _toggle(self, row: int) -> None:
        if row == 0:
            self.opts.source = "main" if self.opts.source == "stable" else "stable"
        elif row == 1:
            self.opts.apps = not self.opts.apps
        elif row == 2:
            self.opts.lockscreen = not self.opts.lockscreen
        elif row == 3:
            self.opts.start = not self.opts.start
        elif row == 4:
            self.opts.install_all = not self.opts.install_all
        elif row == 5 and proxy_url():
            self.opts.proxy = not self.opts.proxy

    # -- execution ------------------------------------------------------
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
                    now = time.monotonic()
                    if now - last_draw > 0.1:
                        self.spin += 1
                        self._draw(stdscr)
                        last_draw = now
                    ch = stdscr.getch()
                    if ch == curses.KEY_RESIZE:
                        continue
                    if ch == 3:  # Ctrl+C
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
        self.visited.add(4)
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
            prompt = f"[{self.s('failed')}] {step.title} (exit {rc})  [r] {self.s('retry')}  [s] {self.s('skip')}  [a] {self.s('abort')}"
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
