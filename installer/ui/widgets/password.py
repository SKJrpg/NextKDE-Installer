"""The one password prompt: asked once per run, only when sudo needs it."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static


class PasswordDialog(ModalScreen[str | None]):
    BINDINGS = [("escape", "cancel", "escape")]

    def __init__(self, strings, **kwargs) -> None:
        super().__init__(**kwargs)
        self.strings = strings

    def compose(self) -> ComposeResult:
        s = self.strings
        with Vertical(id="confirm_box"):
            yield Static(s("sudo_password_title"), id="confirm_title")
            yield Static(s("sudo_password_body"), id="confirm_body")
            yield Input(password=True, id="sudo_password")
            with Horizontal(id="confirm_buttons"):
                yield Button(s("cancel"), id="confirm_cancel")
                yield Button(s("key_continue"), id="confirm_ok", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#sudo_password", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm_ok":
            self.dismiss(self.query_one("#sudo_password", Input).value)
        elif event.button.id == "confirm_cancel":
            self.action_cancel()
