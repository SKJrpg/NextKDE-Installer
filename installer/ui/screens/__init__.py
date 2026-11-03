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


class ChromeScreen(Screen):
    """Header and footer with localized key labels; the management area."""

    # (keys, action, string key for the footer description[, key display[, show]])
    KEYS: tuple[tuple, ...] = ()

    def __init__(self, strings: Strings, **kwargs) -> None:
        super().__init__(**kwargs)
        self.strings = strings
        self._base_bindings = self._bindings.copy()
        self._bind_keys()

    def _bind_keys(self) -> None:
        """(Re)bind KEYS with the current language's footer words."""
        self._bindings = self._base_bindings.copy()
        for entry in self.KEYS:
            keys, action, label, *rest = entry
            display = rest[0] if rest else None
            if display and self.strings.ascii:
                display = display.replace("←", "left").replace("→", "right") \
                                 .replace("↑", "up").replace("↓", "down")
            show = rest[1] if len(rest) > 1 else True
            for key in keys.split(","):
                # Our binding must win over the screen's own (e.g. tab).
                self._bindings.key_to_bindings.pop(key.strip(), None)
            self._bindings.bind(keys, action, self.strings(label) if show else "",
                                key_display=display)

    def apply_language(self, strings: Strings) -> None:
        self.strings = strings
        self._bind_keys()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield from self.body()
        yield Footer()

    def body(self):
        """The widgets of this screen, between header and footer."""
        return iter(())


class WizardScreen(ChromeScreen):
    """One wizard step inside the fixed chrome."""

    STEP = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="body"):
            yield Static(self._sidebar(), id="sidebar")
            with Vertical(id="main"):
                yield from self.body()
        yield Footer()

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
