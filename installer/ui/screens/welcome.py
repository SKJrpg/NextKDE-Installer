"""Welcome: what this is, what was detected, and the key that moves on."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import Static

from . import WizardScreen


class WelcomeScreen(WizardScreen):
    STEP = 0
    KEYS = (("enter", "open_system", "key_open"), ("q", "quit", "key_quit"))

    def body(self) -> ComposeResult:
        yield Static(self.strings("welcome_intro"), id="intro")
        yield Static(self._facts(), id="facts")

    def _facts(self) -> Text:
        s = self.strings
        system = self.app.system
        session = next((p.detail for p in system.probes if p.key == "probe_session"), "?")
        pairs = (
            (s("label_distro"), system.label),
            (s("label_arch"), system.arch),
            (s("label_session"), session),
            (s("label_path"), s("review_target")),
        )
        text = Text()
        for index, (label, value) in enumerate(pairs):
            text.append(f"{label:<16}", style="dim")
            text.append(value)
            if index < len(pairs) - 1:
                text.append("\n")
        return text

    def action_open_system(self) -> None:
        from .system import SystemScreen

        self.app.push_screen(SystemScreen(self.strings))

    def action_quit(self) -> None:
        self.app.exit()
