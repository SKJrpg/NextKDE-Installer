"""Units: what the ledger records, with Space to switch one through kosctl."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from ... import manage
from .management import ManageScreen


class UnitsScreen(ManageScreen):
    CONTEXT = "list.units"

    def __init__(self, strings, **kwargs) -> None:
        super().__init__(strings, **kwargs)
        self.units = []

    def head(self) -> Text:
        return Text(self.strings("units_title"), style="bold")

    def fetch(self):
        return manage.units(self.app.paths.source_root)

    def fill(self, data) -> None:
        self.units = list(data)
        if not self.units:
            self.note(self.strings("units_none"))
        self.fill_list([Option(self._row(unit), id=unit.name) for unit in self.units])

    def _row(self, unit) -> Text:
        glyphs = ("+", "-") if self.strings.ascii else ("✔", "·")
        text = Text(f"{glyphs[0] if unit.installed else glyphs[1]} ")
        text.append(f"{unit.name:<12}")
        text.append(f"{unit.version:<10}", style=self.app.secondary_style)
        text.append(f"{unit.mode:<8}", style=self.app.secondary_style)
        text.append(self.strings("on" if unit.installed else "off"),
                    style="green" if unit.installed else self.app.secondary_style)
        return text

    def current(self):
        option = self.query_one("#manage_list", OptionList).highlighted_option
        if option is None:
            return None
        return next((unit for unit in self.units if unit.name == option.id), None)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.action_unit_toggle()

    def action_unit_toggle(self) -> None:
        unit = self.current()
        if unit is None or self.busy:
            return
        verb = "off" if unit.installed else "on"
        if unit.name == "core" and verb == "off":
            # The backend has no way back except a full uninstall.
            self.note(self.strings("unit_core_locked"), "red")
            return
        self.start_action(f"kosctl {verb} {unit.name}",
                          manage.kosctl(self.app.paths.source_root, verb, unit.name))
