"""The command menu: every action that is not a page key, in one popup.

A screen lists the commands it can run (``ChromeScreen.commands``); the menu
only draws them and answers with the chosen one. Rows keep their place when
disabled and say why; the shortcut column is the key the page already offers.
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
class Command:
    """One menu row; ``run`` is called after the menu closes."""

    id: str
    label: str
    run: Callable[[], object]
    shortcut: str = ""
    enabled: bool = True
    reason: str = ""
    current: bool = False       # the active theme or language


class CommandMenu(ModalScreen[Command | None]):
    BINDINGS = [
        ("escape", "cancel", "escape"),
        ("j", "cursor_down", ""),
        ("k", "cursor_up", ""),
    ]

    def __init__(self, strings, commands, **kwargs) -> None:
        super().__init__(**kwargs)
        self.strings = strings
        self.commands = list(commands)
        self._by_id = {command.id: command for command in self.commands}

    def compose(self) -> ComposeResult:
        with Vertical(id="command_box"):
            yield Static(self.strings("cmd_title"), id="command_title")
            yield OptionList(*self._rows(), id="command_list")

    def _rows(self) -> list[Option]:
        quiet = getattr(self.app, "secondary_style", "dim")
        marker = "(*)" if self.strings.ascii else "(•)"
        rows = []
        for command in self.commands:
            text = Text()
            text.append(f"{marker} " if command.current else "    ",
                        style="bold" if command.current else None)
            text.append(command.label)
            if command.shortcut:
                text.append("  " + command.shortcut, style=quiet)
            if command.reason:
                text.append("  " + command.reason, style=quiet)
            rows.append(Option(text, id=command.id, disabled=not command.enabled))
        return rows

    def on_mount(self) -> None:
        listing = self.query_one("#command_list", OptionList)
        listing.highlighted = next(
            (index for index, command in enumerate(self.commands) if command.enabled), 0)
        listing.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        command = self._by_id.get(event.option_id or "")
        if command is not None and command.enabled:
            self.dismiss(command)

    def action_cursor_down(self) -> None:
        self.query_one("#command_list", OptionList).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one("#command_list", OptionList).action_cursor_up()

    def action_cancel(self) -> None:
        self.dismiss(None)
