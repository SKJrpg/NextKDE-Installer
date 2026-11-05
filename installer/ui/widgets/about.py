"""About: the version, the interpreter and the directories in use.

One box, no settings: the theme and language live in the command menu, and a
second options page would only disagree with the wizard's own one.
"""

from __future__ import annotations

import platform

from rich.cells import cell_len
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from ... import VERSION


class AboutScreen(ModalScreen[None]):
    """Read-only: any key closes it, like the help overlay."""

    def compose(self) -> ComposeResult:
        with Vertical(id="about_box"):
            yield Static(self.app.strings("about_title"), id="about_title")
            yield Static(self._body(), id="about_body")
            yield Static(self.app.strings("help_close"), id="about_close")

    def _body(self) -> Text:
        s, app = self.app.strings, self.app
        source = (app.opts.local_path if app.opts.source == "local"
                  and app.opts.local_path else app.paths.source_root)
        pairs = [
            (s("about_version"), f"NextKDE Installer {VERSION}"),
            (s("about_python"), platform.python_version()),
            (s("about_installer"), str(app.paths.installer_root)),
            (s("about_source"), str(source)),
            (s("about_state"), str(app.paths.state_root)),
        ]
        width = max(cell_len(label) for label, _ in pairs) + 2
        text = Text()
        for index, (label, value) in enumerate(pairs):
            text.append(label + " " * (width - cell_len(label)),
                        style=app.secondary_style)
            text.append(value)
            if index < len(pairs) - 1:
                text.append("\n")
        return text

    def on_key(self, event) -> None:
        event.stop()
        self.dismiss(None)
