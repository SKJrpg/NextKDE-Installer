"""The help overlay: the keys of the screen underneath, and nothing else.

Its rows come from that screen's own key table, the same one the footer is
built from, so a hint that is offered is a key that works.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


class HelpScreen(ModalScreen[None]):
    """Read-only: Esc, or any other key, closes it."""

    def __init__(self, strings, rows, **kwargs) -> None:
        super().__init__(**kwargs)
        self.strings = strings
        self.rows = list(rows)

    def compose(self) -> ComposeResult:
        with Vertical(id="help_box"):
            yield Static(self.strings("help_title"), id="help_title")
            yield Static(self._body(), id="help_body")
            yield Static(self.strings("help_close"), id="help_close")

    def _body(self) -> Text:
        text = Text()
        width = max((len(keys) for keys, _ in self.rows), default=0) + 2
        for index, (keys, label) in enumerate(self.rows):
            if index:
                text.append("\n")
            text.append(f"{keys:<{width}}", style="bold")
            text.append(label)
        return text

    def on_key(self, event) -> None:
        event.stop()
        self.dismiss(None)
