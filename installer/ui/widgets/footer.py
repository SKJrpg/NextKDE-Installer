"""The one-line hint bar, built from the key rows rather than Textual's merge.

Textual's own Footer reads the focused widget's bindings, so a row that also
scrolls would hide the page's hint. This reads ``keymap.resolve()`` directly:
what it prints is exactly what the screen offers.
"""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from .. import keymap


class KeyFooter(Static):
    """Left-aligned hints, one line, space between items."""

    def on_mount(self) -> None:
        screen = self.screen
        if hasattr(screen, "paint_footer"):
            screen.paint_footer()

    def show(self, rows: list[keymap.Row], strings) -> None:
        text = Text()
        for row in rows:
            action = row.action
            if action.hidden or not action.label:
                continue
            if len(text):
                text.append("  ")
            key = row.display or keymap.display_key(row.keys[0], strings.ascii)
            text.append(keymap.display_key(key, strings.ascii), style="bold")
            text.append(" " + strings(action.label))
        self.update(text)
