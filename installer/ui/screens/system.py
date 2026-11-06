"""System checks: the probe list with its explanation, re-runnable with F5."""

from __future__ import annotations

from rich.cells import cell_len, set_cell_size
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widgets import Static

from ...detect import Probe, detect
from ..widgets.commands import Command
from . import WizardScreen

GLYPHS = {"PASS": "✔", "WARN": "⚠", "FAIL": "✖"}
ASCII_GLYPHS = {"PASS": "+", "WARN": "!", "FAIL": "x"}

# The install steps themselves resolve these; everything else is the user's.
FIXABLE = ("probe_packages", "probe_quickshell")

WIDE_AT = 110
POINTER = ("›", ">")


class SystemScreen(WizardScreen):
    STEP = 1
    CONTEXT = "wizard.checks"

    def __init__(self, strings, **kwargs) -> None:
        super().__init__(strings, **kwargs)
        self.row = 0
        self.rows: list[Static] = []

    def body(self) -> ComposeResult:
        yield Static(self._summary(), id="summary")
        with Container(id="checks_split"):
            yield VerticalScroll(id="probes", can_focus=False)
            with VerticalScroll(id="probe_detail", can_focus=False):
                yield Static(id="probe_detail_text")

    def on_mount(self) -> None:
        self._apply_layout(self.app.size.width)
        self._fill()
        self.call_after_refresh(self._paint_rows)   # the real list width exists then

    def on_resize(self, event) -> None:
        self._apply_layout(event.size.width)
        if self.rows:
            self.call_after_refresh(self._paint_rows)

    def _apply_layout(self, width: int) -> None:
        wide = width >= WIDE_AT
        self.query_one("#checks_split").set_class(wide, "-wide")
        self.query_one("#probe_detail").set_class(wide, "-wide")

    def _status_word(self, status: str) -> str:
        return self.strings(f"status_{status.lower()}").upper()

    def _glyph(self, status: str) -> str:
        return (ASCII_GLYPHS if self.strings.ascii else GLYPHS).get(status, "?")

    def _summary(self) -> Text:
        probes = self.app.system.probes
        counts = tuple(sum(1 for p in probes if p.status == status)
                       for status in ("PASS", "WARN", "FAIL"))
        text = Text(self.strings("system_head"), style="bold")
        text.append("\n")
        text.append(self.strings("system_counts") % counts, style=self.app.secondary_style)
        return text

    def _name_width(self) -> int:
        probes = self.app.system.probes
        return min(20, max([cell_len(self.strings(p.key)) for p in probes] or [4]) + 2)

    def _list_width(self) -> int:
        """Cells the row really has; the fallback covers the first paint."""
        width = self.query_one("#probes", VerticalScroll).content_size.width
        return width if width > 0 else max(20, self.app.size.width - 26)

    def _clip(self, value: str, width: int) -> str:
        if width <= 0:
            return ""
        if cell_len(value) <= width:
            return value
        tail = "..." if self.strings.ascii else "…"
        return set_cell_size(value, max(0, width - cell_len(tail))) + tail

    def _row_text(self, probe: Probe, index: int) -> Text:
        word = self._status_word(probe.status)
        name = self.strings(probe.key)
        quiet = self.app.secondary_style
        text = Text()
        text.append(POINTER[1 if self.strings.ascii else 0] if index == self.row else "  ",
                    style="bold")
        text.append(f" {self._glyph(probe.status)} ", style="bold")
        text.append(word + " " * max(1, 6 - cell_len(word)), style="bold")
        text.append(name + " " * max(2, self._name_width() - cell_len(name)))
        # The full value lives in the detail pane; the row must stay one line.
        text.append(self._clip(probe.detail, self._list_width() - cell_len(text.plain)),
                    style=quiet)
        return text

    def _note(self, probe: Probe) -> str:
        """The OS note names the detected family and the install path it takes."""
        if probe.key == "probe_os":
            family = self.app.system.family or "unknown"
            return self.strings("os_note_" + family)
        return self.strings("why_" + probe.key)

    def _detail(self, probe: Probe) -> Text:
        s = self.strings
        pairs = [
            (s("check_what"), s(probe.key)),
            (s("check_status"), self._status_word(probe.status)),
            (s("check_result"), probe.detail),
            (s("check_why"), self._note(probe)),
        ]
        if probe.status != "PASS":
            pairs.append((s("check_fixable"),
                          s("check_fix_yes") if probe.key in FIXABLE
                          else s("check_fix_no")))
            if probe.remedy:
                # Prefer the UI-language pair; detect.py's English text is the
                # fallback for a probe that has none.
                text = s(f"remedy_{probe.key}")
                pairs.append((s("check_remedy"),
                              probe.remedy if text.startswith("remedy_") else text))
        text = Text()
        for index, (label, value) in enumerate(pairs):
            text.append(f"{label}: ", style=self.app.secondary_style)
            text.append(value)
            if index < len(pairs) - 1:
                text.append("\n")
        return text

    def _fill(self) -> None:
        probes = self.app.system.probes
        container = self.query_one("#probes", VerticalScroll)
        container.remove_children()
        self.row = min(self.row, max(0, len(probes) - 1))
        self.rows = [Static(self._row_text(probe, index))
                     for index, probe in enumerate(probes)]
        if self.rows:
            container.mount_all(self.rows)
        self._show_detail()

    def _paint_rows(self) -> None:
        probes = self.app.system.probes
        for index, row in enumerate(self.rows):
            row.update(self._row_text(probes[index], index))

    def _show_detail(self) -> None:
        probes = self.app.system.probes
        text = self._detail(probes[self.row]) if probes else Text(
            self.strings("check_none"), style=self.app.secondary_style)
        self.query_one("#probe_detail_text", Static).update(text)

    def action_checks_move(self, step: int) -> None:
        probes = self.app.system.probes
        if not probes:
            return
        # A short probe list is a ring: down past the last row returns to the
        # first, and up from the first goes to the last.
        self.row = (self.row + step) % len(probes)
        self._paint_rows()
        self._show_detail()
        if 0 <= self.row < len(self.rows):
            self.query_one("#probes", VerticalScroll).scroll_to_widget(
                self.rows[self.row], animate=False)

    def context_commands(self) -> list[Command]:
        return [Command("refresh", self.strings("cmd_refresh"),
                        self.action_check_refresh, shortcut="ctrl+r")]

    async def action_check_refresh(self) -> None:
        self.app.system = detect(root=self.app.paths.source_root)
        container = self.query_one("#probes", VerticalScroll)
        await container.remove_children()
        self.row = 0
        self.rows = [Static(self._row_text(probe, index))
                     for index, probe in enumerate(self.app.system.probes)]
        await container.mount_all(self.rows)
        self.query_one("#summary", Static).update(self._summary())
        self._show_detail()
        self.call_after_refresh(self._paint_rows)

    def action_wizard_next(self) -> None:
        from .options import OptionsScreen

        self.app.push_screen(OptionsScreen(self.strings))

    def action_wizard_back(self) -> None:
        self.app.pop_screen()
