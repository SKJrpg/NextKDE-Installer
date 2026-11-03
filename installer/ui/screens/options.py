"""Options: source channel, the required core, apps and advanced toggles."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widgets import Checkbox, RadioButton, RadioSet, Static

from ...backend.models import ACTIVATION_START, INSTALL_APPS, INSTALL_LOCKSCREEN
from ...plan import ALL_APPS
from . import WizardScreen

SOURCES = ("stable", "main", "local")
WIDE_AT = 110

# Focused row id -> the description that explains it.
DETAILS = {"core": "detail_core", "lockscreen": "detail_lockscreen",
           "spatial": "detail_spatial", "start": "detail_start"}


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
                radio: bool = False, disabled: bool = False,
                capability: str | None = None) -> Checkbox | RadioButton:
            reason = ""
            if (capability is not None and self.app.backend is not None
                    and not self.app.backend.has(capability)):
                # design §7.4: the option is unusable, and the reason is text.
                value, disabled = False, True
                reason = " · " + s("cap_unavailable") % capability
            self._labels[ident] = label
            kind = SourceRow if radio else CheckRow
            return kind(self._row(label + reason, value, radio), id=ident,
                        value=value, disabled=disabled, compact=True)

        with Container(id="options_split"):
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
                    yield row(s("app_" + name), "app_" + name, name in opts.app_set,
                              capability=INSTALL_APPS)
                yield Static(s("group_advanced"), classes="group")
                yield row(s("opt_lockscreen"), "lockscreen", opts.lockscreen,
                          capability=INSTALL_LOCKSCREEN)
                yield row(s("opt_spatial"), "spatial", opts.spatial)
                yield row(s("opt_start"), "start", opts.start,
                          capability=ACTIVATION_START)
            with VerticalScroll(id="option_detail"):
                yield Static(id="option_detail_text")

    def _detail(self, ident: str) -> Text:
        s = self.strings
        if ident.startswith("source_"):
            name = ident.removeprefix("source_")
            heading = s("source_" + name)
            parts = [s("detail_source"), s("source_" + name + "_note")]
        elif ident.startswith("app_"):
            heading = s("app_" + ident.removeprefix("app_"))
            parts = [s("detail_apps"), s("apps_impact")]
        else:
            heading = {"core": s("core_shell"), "lockscreen": s("opt_lockscreen"),
                       "spatial": s("opt_spatial"), "start": s("opt_start")}.get(
                           ident, s("options_head"))
            parts = [s(DETAILS.get(ident, "detail_apps"))]
            if ident == "spatial":
                parts.append(s("opt_spatial_hint"))
        text = Text(heading, style="bold")
        text.append("\n")
        for index, part in enumerate(parts):
            if index:
                text.append("\n")
            text.append(part, style=self.app.secondary_style)
        return text

    def _show_detail(self, ident: str | None = None) -> None:
        """Show the focused row's explanation; with no row, the chosen source's."""
        known = bool(ident) and (ident.startswith(("source_", "app_")) or ident in DETAILS)
        if not known:
            ident = "source_" + self.app.opts.source
        self.query_one("#option_detail_text", Static).update(self._detail(ident))

    def _apply_layout(self, width: int, height: int) -> None:
        wide = width >= WIDE_AT
        self.query_one("#options_split").set_class(wide, "-wide")
        detail = self.query_one("#option_detail")
        detail.set_class(wide, "-wide")
        # On a short narrow screen the list needs the rows more than the prose.
        detail.set_class(not wide and height < 24, "-hidden")

    def on_descendant_focus(self, event) -> None:
        if event.widget.id:
            self._show_detail(event.widget.id)

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
        self._apply_layout(self.app.size.width, self.app.size.height)
        self._show_detail("source_" + self.app.opts.source)

    def on_resize(self, event) -> None:
        self._apply_layout(event.size.width, event.size.height)

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
        self._show_detail("source_" + source)

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

        if self.app.backend_error:
            # design §7.4: an incompatible interface stops before Review.
            self.notify(self.strings("backend_incompatible") % self.app.backend_error,
                        severity="error")
            return
        self.app.push_screen(ReviewScreen(self.strings))

    def action_back(self) -> None:
        self.app.pop_screen()
