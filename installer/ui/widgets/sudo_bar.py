"""The sudo prompt, inline above the footer: a bar, not a dialog.

One request at a time. The bar is hidden until a blocked sudo call needs an
answer, takes the cursor, and disappears as soon as it has one; the typed
value lives only in the field and is cleared when the bar goes away.
"""

from __future__ import annotations

from typing import Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, Static


class SudoInput(Input):
    """Not focusable until the bar is shown, so a hidden bar takes no focus."""

    can_focus = False


class SudoBar(Vertical):
    """A compact title, reason and masked field; hidden by default."""

    def __init__(self, strings, **kwargs) -> None:
        super().__init__(**kwargs)
        self.strings = strings
        self._answer: Callable[[str | None], None] | None = None
        self._previous = None          # focus to return to
        self.display = False

    def compose(self) -> ComposeResult:
        s = self.strings
        quiet = getattr(self.app, "secondary_style", "dim")
        with Horizontal(id="sudo_head"):
            yield Static(Text(s("sudo_password_title"), style="bold"), id="sudo_title")
            yield Static(Text(s("sudo_bar_hint"), style=quiet), id="sudo_hint")
        yield Static(Text(s("sudo_password_body"), style=quiet), id="sudo_body")
        yield SudoInput(password=True, id="sudo_input",
                        placeholder=s("sudo_password_prompt"))

    def ask(self, answer) -> None:
        """Show the bar for one request and put the cursor in the field."""
        self._previous = self.app.focused
        self._answer = answer
        self.display = True
        field = self.query_one("#sudo_input", SudoInput)
        field.can_focus = True
        field.value = ""
        field.focus()

    def hide(self) -> None:
        """Dismiss the bar, drop the typed value and give the focus back."""
        if not self.display:
            return
        self._answer = None
        self.display = False
        field = self.query_one("#sudo_input", SudoInput)
        field.value = ""
        field.can_focus = False
        previous, self._previous = self._previous, None
        if previous is not None and previous.is_mounted:
            previous.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._submit(self.query_one("#sudo_input", SudoInput).value)

    def on_key(self, event) -> None:
        if self.display and event.key == "escape":
            event.stop()
            self._submit(None)

    def _submit(self, password: str | None) -> None:
        answer, self._answer = self._answer, None
        if answer is not None:
            answer(password or None)
