"""Options: source channel, the required core, apps and advanced toggles.

Focus model: Tab/Shift+Tab move between groups, arrows inside one, Space
toggles, Enter belongs to the page. The rows therefore keep Enter for the
screen (``EnterPasses``) instead of swallowing it with Textual's default.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widgets import Checkbox, RadioButton, RadioSet, Static

from ...backend.models import ACTIVATION_START, INSTALL_APPS, INSTALL_LOCKSCREEN
from ...plan import ALL_APPS
from . import CursorKeys, EnterPasses, WizardScreen

SOURCES = ("stable", "main", "local")
WIDE_AT = 110

# Focused row id -> the description that explains it.
DETAILS = {"core": "detail_core", "lockscreen": "detail_lockscreen",
           "spatial": "detail_spatial", "start": "detail_start"}

GROUPS = (
    ("sources", ("source_stable", "source_main", "source_local")),
    ("apps", tuple("app_" + name for name in ALL_APPS)),
    ("advanced", ("lockscreen", "spatial", "start")),
)


class CheckRow(EnterPasses, Checkbox):
    """A checkbox whose state is the text marker, not a colour-only glyph."""

    BUTTON_LEFT = BUTTON_INNER = BUTTON_RIGHT = ""
    context = "option.check"


class SourceRow(EnterPasses, RadioButton):
    """The same, for the source radio rows."""

    BUTTON_LEFT = BUTTON_INNER = BUTTON_RIGHT = ""
    context = "option.radio"


class SourceSet(CursorKeys, RadioSet):
    """Arrows and j/k move the choice; Enter is the page's."""

    context = "option.radio"


class OptionsScreen(WizardScreen):
    STEP = 2
    CONTEXT = "wizard.options"

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
            with VerticalScroll(id="options", can_focus=False):
                yield Static(s("options_head"), id="options_head")
                yield Static(s("group_source"), classes="group")
                with SourceSet(id="sources", compact=True):
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
            with VerticalScroll(id="option_detail", can_focus=False):
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
        super().on_descendant_focus(event)
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
        # The form always has a row: the footer describes what it can do.
        self.query_one("#source_" + self.app.opts.source, RadioButton).focus()

    def on_resize(self, event) -> None:
        super().on_resize(event)
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

    # -- focus: Tab between groups, arrows inside one ---------------------
    def _widget(self, ident: str):
        found = self.query("#" + ident)
        return found.first() if found else None

    def _usable(self, ident: str):
        widget = self._widget(ident)
        return widget if widget is not None and not widget.disabled else None

    def _group_of(self, ident: str | None) -> str | None:
        """The group a focused widget belongs to; the radio set is its group."""
        for name, idents in GROUPS:
            if ident == name or ident in idents:
                return name
        return None

    def _focus_group(self, step: int) -> None:
        names = [name for name, _ in GROUPS]
        current = self._group_of(self.focused.id if self.focused else None)
        index = names.index(current) if current in names else (-1 if step > 0 else len(names))
        order = range(index + step, len(names), step) if step > 0 \
            else range(index + step, -1, -1)
        for position in order:
            if self._focus_first(names[position]):
                return

    def _focus_first(self, group: str) -> bool:
        for ident in dict(GROUPS)[group]:
            widget = self._usable(ident)
            if widget is not None:
                widget.focus()
                return True
        return False

    def _focus_sibling(self, step: int) -> None:
        group = self._group_of(self.focused.id if self.focused else None)
        if group is None or group == "sources":
            return              # the radio set owns its own arrows
        rows = [widget for widget in (self._usable(ident)
                                      for ident in dict(GROUPS)[group])
                if widget is not None]
        if self.focused not in rows:
            return
        index = rows.index(self.focused) + step
        if 0 <= index < len(rows):
            rows[index].focus()

    def action_focus_next(self) -> None:
        self._focus_group(1)

    def action_focus_prev(self) -> None:
        self._focus_group(-1)

    def action_option_move(self, step: int) -> None:
        self._focus_sibling(step)

    def action_option_pick(self, step: int) -> None:
        """Arrows and j/k pick a source; the marker moves with the choice."""
        rows = [row for row in self.query_one("#sources", SourceSet).query(SourceRow)
                if not row.disabled]
        if not rows:
            return
        current = next((index for index, row in enumerate(rows) if row.value), 0)
        index = max(0, min(current + step, len(rows) - 1))
        rows[index].value = True

    def action_option_toggle(self) -> None:
        widget = self.focused
        if isinstance(widget, Checkbox) and not widget.disabled:
            widget.value = not widget.value
        elif isinstance(widget, RadioButton) and not widget.disabled:
            widget.value = True

    def action_wizard_next(self) -> None:
        from .review import ReviewScreen

        if self.app.backend_error:
            # design §7.4: an incompatible interface stops before Review.
            self.notify(self.strings("backend_incompatible") % self.app.backend_error,
                        severity="error")
            return
        self.app.push_screen(ReviewScreen(self.strings))

    def action_wizard_back(self) -> None:
        self.app.pop_screen()
