"""Header, step sidebar and footer shared by every wizard screen.

Screen construction happens after the app exists, so the footer labels are
localized here instead of in a class-level ``BINDINGS`` tuple.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from ...strings import Strings

STEPS = ("step_welcome", "step_system", "step_options", "step_review", "step_install")


class WizardScreen(Screen):
    """One wizard step inside the fixed chrome."""

    STEP = 0
    # (keys, action, string key for the footer description)
    KEYS: tuple[tuple[str, str, str], ...] = ()

    def __init__(self, strings: Strings, **kwargs) -> None:
        super().__init__(**kwargs)
        self.strings = strings
        for keys, action, label in self.KEYS:
            self._bindings.bind(keys, action, strings(label))

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="body"):
            yield Static(self._sidebar(), id="sidebar")
            with Vertical(id="main"):
                yield from self.body()
        yield Footer()

    def body(self):
        """The widgets of this step, mounted inside #main."""
        return iter(())

    def _sidebar(self) -> Text:
        text = Text()
        for index, key in enumerate(STEPS):
            label = self.strings(key)
            if index == self.STEP:
                text.append(f"▸ {label}", style="bold")
            elif index < self.STEP:
                text.append(f"✔ {label}", style="dim")
            else:
                text.append(f"  {label}", style="dim")
            text.append("\n" if index < len(STEPS) - 1 else "")
        return text
