"""The local checkout path prompt: type or edit one, validated in a worker.

Not a file browser: one field, ``~`` is expanded, and the submitted path goes
through the same ``inspect_local`` the install uses. A failure keeps the dialog
open and shows the reason; Esc leaves the previous choice untouched.
"""

from __future__ import annotations

from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from ...source import manager
from ...source.models import PreparedSource


class LocalPathDialog(ModalScreen[PreparedSource | None]):
    BINDINGS = [("escape", "cancel", "escape")]

    def __init__(self, strings, start: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self.strings = strings
        self.start = start
        self._checking = False

    def compose(self) -> ComposeResult:
        s = self.strings
        with Vertical(id="path_box"):
            yield Static(s("local_path_title"), id="path_title")
            yield Static(s("local_path_body"), id="path_body")
            yield Input(value=self.start, id="path_input")
            yield Static("", id="path_error")
            with Horizontal(id="path_buttons"):
                yield Button(s("cancel"), id="path_cancel")
                yield Button(s("local_path_use"), id="path_ok", variant="primary")

    def on_mount(self) -> None:
        self.call_after_refresh(self._focus_input)

    def _focus_input(self) -> None:
        for field in self.query("#path_input"):
            field.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_accept()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "path_ok":
            self.action_accept()
        elif event.button.id == "path_cancel":
            self.action_cancel()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_accept(self) -> None:
        if self._checking:
            return
        raw = self.query_one("#path_input", Input).value.strip()
        if not raw:
            self.query_one("#path_error", Static).update(self.strings("local_path_empty"))
            return
        self._checking = True
        self.query_one("#path_error", Static).update(self.strings("local_path_checking"))
        self.check_path(raw)

    @work(thread=True, exit_on_error=False)
    def check_path(self, raw: str) -> None:
        """Git runs off the event loop; the dialog stays up until it answers."""
        try:
            source = manager.inspect_local(Path(raw).expanduser())
            error = ""
        except (OSError, ValueError) as failure:
            source, error = None, str(failure)
        self.app.call_from_thread(self._checked, source, error)

    def _checked(self, source, error: str) -> None:
        self._checking = False
        if not self.is_mounted:
            return
        if source is not None:
            self.dismiss(source)
            return
        self.query_one("#path_error", Static).update(error)
        self.query_one("#path_input", Input).focus()
