"""The sudo prompt, inline above the footer: a bar, not a dialog.

One request at a time. The bar is hidden until a blocked sudo call needs an
answer, takes the cursor, and disappears as soon as it has one; the typed
value lives only in the field and is cleared when the bar goes away.
"""

from __future__ import annotations

import getpass
from typing import Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, Static

from ...strings import nerd_font_available


class SudoInput(Input):
    """Not focusable until shown, and silent: no characters, not even their count."""

    can_focus = False

    @property
    def _value(self) -> Text:
        # Textual's password mode paints one bullet per character; the sudo bar
        # echoes nothing at all, so neither the secret nor its length is shown.
        return Text("", no_wrap=True, overflow="ignore", end="")

    # Input draws its cursor as a styled space and restarts the blink on every
    # focus or key. A password field should not reveal where it is: keep it
    # hidden through the whole focus/blink cycle.
    def _restart_blink(self) -> None:
        self._cursor_visible = False
        timer = getattr(self, "_blink_timer", None)
        if timer is not None:
            timer.pause()

    def _toggle_cursor(self) -> None:
        self._cursor_visible = False

    def _pause_blink(self, visible: bool = False) -> None:
        self._cursor_visible = False
        timer = getattr(self, "_blink_timer", None)
        if timer is not None:
            timer.pause()


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
            yield Static(Text(s("sudo_password_body"), style=quiet), id="sudo_body")
            yield Static(Text(s("sudo_bar_hint"), style=quiet), id="sudo_hint")
        with Horizontal(id="sudo_input_row"):
            yield Static(Text(self._prompt(), style="bold"), id="sudo_prompt")
            yield SudoInput(password=True, id="sudo_input", placeholder="")

    def on_mount(self) -> None:
        self._fit_hint()

    def on_resize(self, event) -> None:
        self._fit_hint()

    def _fit_hint(self) -> None:
        """At 66 columns the reason and the hint cannot share a line."""
        hints = self.query("#sudo_hint")
        if hints:
            hints.first().display = self.app.size.width >= 80

    def _prompt(self) -> str:
        """The classic sudo prompt; the lock only when a Nerd Font is around."""
        prompt = self.strings("sudo_prompt") % getpass.getuser()
        return prompt + ("\uf023 " if nerd_font_available() else "")

    def ask(self, answer) -> None:
        """Show the bar for one request and put the cursor in the field."""
        self._previous = self.app.focused
        self._answer = answer
        self.display = True
        self._fit_hint()
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
