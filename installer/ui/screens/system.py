"""System checks: the probe list, read-only, re-runnable with F5."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from ...detect import Probe, detect
from . import WizardScreen

GLYPHS = {"PASS": "✔", "WARN": "⚠", "FAIL": "✖"}
ASCII_GLYPHS = {"PASS": "+", "WARN": "!", "FAIL": "x"}


class SystemScreen(WizardScreen):
    STEP = 1
    KEYS = (("f5", "refresh", "key_refresh"), ("escape", "back", "key_back"))

    def body(self) -> ComposeResult:
        yield Static(self._summary(), id="summary")
        yield VerticalScroll(id="probes")

    def on_mount(self) -> None:
        self._fill()

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
        text.append(self.strings("system_counts") % counts, style="dim")
        return text

    def _row(self, probe: Probe) -> Static:
        text = Text()
        text.append(f"{self._glyph(probe.status)} ", style="bold")
        text.append(f"{self._status_word(probe.status):<5}", style="bold")
        text.append(f"{self.strings(probe.key)}  ")
        text.append(probe.detail, style="dim")
        return Static(text)

    def _fill(self) -> None:
        rows = [self._row(probe) for probe in self.app.system.probes]
        self.query_one("#probes", VerticalScroll).mount_all(rows)

    async def action_refresh(self) -> None:
        self.app.system = detect(root=self.app.paths.source_root)
        container = self.query_one("#probes", VerticalScroll)
        await container.remove_children()
        await container.mount_all([self._row(p) for p in self.app.system.probes])
        self.query_one("#summary", Static).update(self._summary())

    def action_back(self) -> None:
        self.app.pop_screen()
