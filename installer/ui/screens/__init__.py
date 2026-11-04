"""Header, step sidebar and footer shared by every wizard screen.

Screen construction happens after the app exists, so the footer labels are
localized here instead of in a class-level ``BINDINGS`` tuple. One per-screen
key table feeds both the footer and the help overlay, so the two cannot drift.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from ...strings import Strings
from ..widgets.help import HelpScreen

STEPS = ("step_welcome", "step_system", "step_options", "step_review", "step_install")

# Keys for the sidebar step of the same number: 1 is Welcome, 5 is Installation.
JUMP_KEYS = ("1", "2", "3", "4", "5")

# Every screen offers the same way to see its own keys.
HELP_KEY = ("question_mark", "help", "key_help", "?")


class ChromeScreen(Screen):
    """Header and footer with localized key labels; the management area."""

    # (keys, action, string key for the footer description[, key display[, show]])
    KEYS: tuple[tuple, ...] = ()

    def __init__(self, strings: Strings, **kwargs) -> None:
        super().__init__(**kwargs)
        self.strings = strings
        self._base_bindings = self._bindings.copy()
        self._bind_keys()

    def keys(self) -> tuple[tuple, ...]:
        """This screen's key rows, help included: footer and overlay share them."""
        return (*self.KEYS, HELP_KEY)

    def _display(self, display: str | None) -> str | None:
        if display and self.strings.ascii:
            return (display.replace("←", "left").replace("→", "right")
                    .replace("↑", "up").replace("↓", "down").replace("–", "-"))
        return display

    def _bind_keys(self) -> None:
        """(Re)bind the rows with the current language's footer words."""
        self._bindings = self._base_bindings.copy()
        for entry in self.keys():
            keys, action, label, *rest = entry
            display = rest[0] if rest else None
            show = rest[1] if len(rest) > 1 else True
            for key in keys.split(","):
                # Our binding must win over the screen's own (e.g. tab).
                self._bindings.key_to_bindings.pop(key.strip(), None)
            self._bindings.bind(keys, action, self.strings(label) if show else "",
                                key_display=self._display(display))

    def help_rows(self) -> list[tuple[str, str]]:
        """(keys, description) for the overlay: what the footer has, spelled out."""
        rows = []
        for keys, action, label, *rest in self.keys():
            display = rest[0] if rest else keys
            show = rest[1] if len(rest) > 1 else True
            if not show or action == "help":
                continue
            if self.check_action(action.split("(")[0], ()) is False:
                continue  # the action is unavailable here, so its key is too
            rows.append((self._display(display) or keys, self.strings(label)))
        return rows

    def action_help(self) -> None:
        self.app.push_screen(HelpScreen(self.strings, self.help_rows()))

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
    # Jumping back is safe only where no worker is running behind the screen.
    JUMP = True

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
                text.append(f"✔ {label}", style=self.app.secondary_style)
            else:
                text.append(f"  {label}", style=self.app.secondary_style)
            text.append("\n" if index < len(STEPS) - 1 else "")
        return text

    # -- navigation ------------------------------------------------------
    def _reachable(self, index: int) -> bool:
        return 0 <= index < len(STEPS) and index <= self.STEP

    def goto_step(self, index: int) -> None:
        """Move to a step already done or current; a later one does nothing.

        Each pop is started, not awaited: awaiting one from inside a key handler
        would wait for the very screen handling the key.
        """
        if not self.JUMP or index == self.STEP or not self._reachable(index):
            return
        while isinstance(self.app.screen, WizardScreen) and self.app.screen.STEP > index:
            self.app.pop_screen()

    async def on_key(self, event) -> None:
        if self.JUMP and event.key in JUMP_KEYS:
            event.stop()
            self.goto_step(int(event.key) - 1)

    async def on_click(self, event) -> None:
        # The sidebar is a column of steps; row 0 sits under its top padding.
        if event.widget is not None and event.widget.id == "sidebar":
            self.goto_step(event.y - 1)

    def help_rows(self) -> list[tuple[str, str]]:
        rows = super().help_rows()
        if self.JUMP and self.STEP:
            rows.append((self._display("1–5") or "1-5", self.strings("key_jump")))
        return rows
