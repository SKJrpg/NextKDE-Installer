"""The one confirmation dialog: rollback and uninstall both go through it.

With a ``word`` the Confirm button stays disabled until that word is typed, so
a destructive action cannot be started by a stray Enter.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static


class ConfirmDialog(ModalScreen[bool]):
    BINDINGS = [
        ("escape", "cancel", "escape"),
        # The buttons sit side by side; arrows and the Vim pairs choose between
        # them. A focused text field keeps its own letters and arrows.
        ("left", "app.focus_previous", "left"),
        ("right", "app.focus_next", "right"),
        ("h", "app.focus_previous", "h"),
        ("l", "app.focus_next", "l"),
        ("k", "app.focus_previous", "k"),
        ("j", "app.focus_next", "j"),
    ]

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if self.word and action.startswith("app.focus_"):
            return None        # the word field owns its letters
        return True

    def __init__(self, strings, heading: str, body: str, word: str = "",
                 confirm_variant: str = "primary", confirm_label: str = "",
                 cancel_label: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self.strings = strings
        self.heading, self.body_text = heading, body
        self.word = word
        self.confirm_variant = confirm_variant
        # Named after what they do, so "cancel" never means "yes".
        self.confirm_label = confirm_label or strings("confirm")
        self.cancel_label = cancel_label or strings("cancel")

    def compose(self) -> ComposeResult:
        s = self.strings
        with Vertical(id="confirm_box"):
            yield Static(self.heading, id="confirm_title")
            yield Static(self.body_text, id="confirm_body")
            if self.word:
                # The installer app sets it from its mode; a plain App (tests) has none.
                quiet = getattr(self.app, "secondary_style", "dim")
                yield Static(Text(s("confirm_uninstall_word"), style=quiet),
                             id="confirm_hint")
                yield Input(id="confirm_word")
            if not self.word:
                quiet = getattr(self.app, "secondary_style", "dim")
                yield Static(Text(self.strings("dialog_keys"), style=quiet),
                             id="confirm_keys")
            with Horizontal(id="confirm_buttons"):
                yield Button(self.cancel_label, id="confirm_cancel")
                yield Button(self.confirm_label, id="confirm_ok",
                             variant=self.confirm_variant, disabled=bool(self.word))

    def on_mount(self) -> None:
        # The typed word when there is one; otherwise the safe choice, so a
        # stray Enter never confirms a destructive action.
        self.query_one("#confirm_word" if self.word else "#confirm_cancel").focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "confirm_word":
            self.query_one("#confirm_ok", Button).disabled = (
                event.value.strip() != self.word)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "confirm_word":
            self.action_confirm()

    def action_confirm(self) -> None:
        if not self.query_one("#confirm_ok", Button).disabled:
            self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm_ok":
            self.action_confirm()
        elif event.button.id == "confirm_cancel":
            self.action_cancel()
