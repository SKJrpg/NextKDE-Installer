"""Options: source channel, the required core, apps and advanced toggles."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Checkbox, RadioButton, RadioSet, Static

from ...plan import ALL_APPS
from . import WizardScreen

SOURCES = ("stable", "main", "local")


class OptionsScreen(WizardScreen):
    STEP = 2
    KEYS = (("enter", "next", "key_continue"), ("escape", "back", "key_back"))

    def body(self) -> ComposeResult:
        s = self.strings
        opts = self.app.opts
        with VerticalScroll(id="options"):
            yield Static(s("options_head"), id="options_head")
            yield Static(s("group_source"), classes="group")
            with RadioSet(id="sources", compact=True):
                for name in SOURCES:
                    yield RadioButton(s("source_" + name), id="source_" + name)
            yield Static(s("group_core"), classes="group")
            yield Checkbox(f"{s('core_shell')} · {s('label_required')}",
                           id="core", value=True, disabled=True,
                           compact=True)
            yield Static(s("group_optional"), classes="group")
            for name in ALL_APPS:
                yield Checkbox(s("app_" + name), id="app_" + name,
                               value=name in opts.app_set, compact=True)
            yield Static(s("group_advanced"), classes="group")
            yield Checkbox(s("opt_lockscreen"), id="lockscreen",
                           value=opts.lockscreen, compact=True)
            yield Checkbox(s("opt_spatial"), id="spatial",
                           value=opts.spatial, compact=True)
            yield Checkbox(s("opt_start"), id="start", value=opts.start, compact=True)

    def on_mount(self) -> None:
        self.query_one("#source_" + self.app.opts.source, RadioButton).value = True

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id != "sources" or event.pressed.id is None:
            return
        source = event.pressed.id.removeprefix("source_")
        if source != self.app.opts.source:
            self.app.opts.source = source
            self.app.invalidate_prepared()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        box = event.checkbox
        if box.id is None or box.id == "core":
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
