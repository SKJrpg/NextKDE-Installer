"""Options: source channel, the required core, apps and advanced toggles."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Checkbox, RadioButton, RadioSet, Static

from ...plan import ALL_APPS
from . import WizardScreen

SOURCES = ("stable", "main", "local")


class CheckRow(Checkbox):
    """A checkbox whose state is the text marker, not a colour-only glyph."""

    BUTTON_LEFT = BUTTON_INNER = BUTTON_RIGHT = ""


class SourceRow(RadioButton):
    """The same, for the source radio rows."""

    BUTTON_LEFT = BUTTON_INNER = BUTTON_RIGHT = ""


class OptionsScreen(WizardScreen):
    STEP = 2
    KEYS = (("enter", "next", "key_continue"), ("escape", "back", "key_back"))

    def body(self) -> ComposeResult:
        s = self.strings
        opts = self.app.opts
        self._labels: dict[str, str] = {}

        def row(label: str, ident: str, value: bool, *,
                radio: bool = False, disabled: bool = False) -> Checkbox | RadioButton:
            self._labels[ident] = label
            kind = SourceRow if radio else CheckRow
            return kind(self._row(label, value, radio), id=ident, value=value,
                        disabled=disabled, compact=True)

        with VerticalScroll(id="options"):
            yield Static(s("options_head"), id="options_head")
            yield Static(s("group_source"), classes="group")
            with RadioSet(id="sources", compact=True):
                for name in SOURCES:
                    yield row(s("source_" + name), "source_" + name,
                              name == opts.source, radio=True)
            yield Static(s("group_core"), classes="group")
            yield row(f"{s('core_shell')} · {s('label_required')}", "core",
                      True, disabled=True)
            yield Static(s("group_optional"), classes="group")
            for name in ALL_APPS:
                yield row(s("app_" + name), "app_" + name, name in opts.app_set)
            yield Static(s("group_advanced"), classes="group")
            yield row(s("opt_lockscreen"), "lockscreen", opts.lockscreen)
            yield row(s("opt_spatial"), "spatial", opts.spatial)
            yield row(s("opt_start"), "start", opts.start)

    def _row(self, label: str, value: bool, radio: bool = False) -> Text:
        """Label with a state marker, so the state survives without colour."""
        if radio:
            on, off = ("(*)", "( )") if self.strings.ascii else ("(•)", "( )")
        else:
            on, off = "[x]", "[ ]"
        text = Text()
        text.append(on if value else off, style="bold" if value else None)
        text.append(" " + label)
        return text

    def _relabel(self, widget: Checkbox | RadioButton, radio: bool = False) -> None:
        if widget.id in self._labels:
            widget.label = self._row(self._labels[widget.id], widget.value, radio)

    def on_mount(self) -> None:
        self.query_one("#source_" + self.app.opts.source, RadioButton).value = True

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id != "sources":
            return
        for button in event.radio_set.query(RadioButton):
            self._relabel(button, radio=True)
        if event.pressed.id is None:
            return
        source = event.pressed.id.removeprefix("source_")
        if source != self.app.opts.source:
            self.app.opts.source = source
            self.app.invalidate_prepared()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        box = event.checkbox
        if box.id is None:
            return
        self._relabel(box)
        if box.id == "core":
            return
        if box.id.startswith("app_"):
            name = box.id.removeprefix("app_")
            if box.value:
                self.app.opts.app_set.add(name)
            else:
                self.app.opts.app_set.discard(name)
            self.app.opts.apps = bool(self.app.opts.app_set)
        else:
            setattr(self.app.opts, box.id, box.value)

    def action_next(self) -> None:
        from .review import ReviewScreen

        self.app.push_screen(ReviewScreen(self.strings))

    def action_back(self) -> None:
        self.app.pop_screen()
