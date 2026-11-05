"""The command menu: every action that is not a page key, in one popup.

A screen lists the commands it can run (``ChromeScreen.commands``); the menu
only draws them and answers with the chosen one. Rows keep their place when
disabled and say why; the shortcut column is the key the page already offers.

A command with ``choices`` is one row with a pending horizontal picker: left
and right move the mark, Enter applies, Esc leaves it alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option


@dataclass(frozen=True)
class Choice:
    """One value of a horizontal picker and what applying it runs."""

    label: str
    run: Callable[[], object]


@dataclass(frozen=True)
class Command:
    """One menu row; ``run`` (or the pending choice) is used after it closes."""

    id: str
    label: str
    run: Callable[[], object] | None = None
    shortcut: str = ""
    enabled: bool = True
    reason: str = ""
    choices: tuple[Choice, ...] = ()
    selected: int = 0       # the choice to start on


class CommandMenu(ModalScreen[Command | tuple[Callable[[], object], ...] | None]):
    BINDINGS = [
        ("escape", "cancel", "escape"),
        ("j", "cursor_down", ""),
        ("k", "cursor_up", ""),
        ("left", "choice_left", ""),
        ("h", "choice_left", ""),
        ("right", "choice_right", ""),
        ("l", "choice_right", ""),
    ]

    def __init__(self, strings, commands, **kwargs) -> None:
        super().__init__(**kwargs)
        self.strings = strings
        self.commands = list(commands)
        self.pending = [command.selected for command in self.commands]

    def compose(self) -> ComposeResult:
        with Vertical(id="command_box"):
            yield Static(self.strings("cmd_title"), id="command_title")
            yield Static(Text(self.strings("cmd_keys"),
                              style=getattr(self.app, "secondary_style", "dim")),
                         id="command_keys")
            yield OptionList(*self._rows(), id="command_list")

    def _row_text(self, index: int) -> Text:
        command = self.commands[index]
        quiet = getattr(self.app, "secondary_style", "dim")
        text = Text()
        text.append(command.label)
        if command.choices:
            text.append("  ")
            for choice_index, choice in enumerate(command.choices):
                if choice_index:
                    text.append("  ")
                chosen = choice_index == self.pending[index]
                text.append(f"[{choice.label}]" if chosen else choice.label,
                            style="bold" if chosen else None)
        if command.shortcut:
            text.append("  " + command.shortcut, style=quiet)
        if command.reason:
            text.append("  " + command.reason, style=quiet)
        return text

    def _rows(self) -> list[Option]:
        return [Option(self._row_text(index), id=command.id,
                       disabled=not command.enabled)
                for index, command in enumerate(self.commands)]

    def on_mount(self) -> None:
        listing = self.query_one("#command_list", OptionList)
        listing.highlighted = next(
            (index for index, command in enumerate(self.commands) if command.enabled), 0)
        listing.focus()

    # -- pending choices ---------------------------------------------------
    def _move_choice(self, step: int) -> None:
        listing = self.query_one("#command_list", OptionList)
        index = listing.highlighted
        if index is None:
            return
        command = self.commands[index]
        if not command.choices:
            return
        moved = max(0, min(self.pending[index] + step, len(command.choices) - 1))
        if moved != self.pending[index]:
            self.pending[index] = moved
            listing.replace_option_prompt_at_index(index, self._row_text(index))

    def action_choice_left(self) -> None:
        self._move_choice(-1)

    def action_choice_right(self) -> None:
        self._move_choice(1)

    def _pending_runs(self) -> tuple[Callable[[], object], ...]:
        """Every changed picker, in row order; other rows apply nothing."""
        return tuple(command.choices[self.pending[index]].run
                     for index, command in enumerate(self.commands)
                     if command.choices and self.pending[index] != command.selected)

    # -- rows and closing --------------------------------------------------
    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        command = self.commands[event.option_index]
        if command.choices:
            self.dismiss(self._pending_runs())    # Enter applies, empty is fine
            return
        if command.enabled:
            self.dismiss(command)

    def action_cursor_down(self) -> None:
        self.query_one("#command_list", OptionList).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one("#command_list", OptionList).action_cursor_up()

    def action_cancel(self) -> None:
        self.dismiss(None)
