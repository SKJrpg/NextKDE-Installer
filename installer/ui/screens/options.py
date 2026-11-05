"""Options: source channel, the required core, apps and advanced toggles.

Tab pages forward here (it is a page key now), so the form has two blocks:
the source group is its own cursor (arrows choose, Enter steps down to the
options below), and the lower block is one cursor of its own (its first row
goes back up to the chosen source). Space toggles checkboxes only.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widgets import Checkbox, RadioButton, Static

from ...backend.models import ACTIVATION_START, INSTALL_APPS, INSTALL_LOCKSCREEN
from ...plan import ALL_APPS
from . import ChoicePasses, EnterPasses, WizardScreen

SOURCES = ("stable", "main", "local")
WIDE_AT = 110

# Focused row id -> the description that explains it.
DETAILS = {"core": "detail_core", "lockscreen": "detail_lockscreen",
           "spatial": "detail_spatial", "start": "detail_start"}

SOURCE_ROWS = tuple("source_" + name for name in SOURCES)
# The disabled core row is deliberately absent: it is not reachable.
LOWER_ROWS = (tuple("app_" + name for name in ALL_APPS)
              + ("lockscreen", "spatial", "start"))


class CheckRow(EnterPasses, Checkbox):
    """A checkbox whose state is the text marker, not a colour-only glyph."""

    BUTTON_LEFT = BUTTON_INNER = BUTTON_RIGHT = ""
    context = "option.check"


class SourceRow(ChoicePasses, RadioButton):
    """The same, for the source radio rows.

    No radio set: the cursor is the page's, and moving onto a source row
    selects it, so the marker and the value never disagree.
    """

    BUTTON_LEFT = BUTTON_INNER = BUTTON_RIGHT = ""
    context = "option.source"

    async def _on_click(self, _event) -> None:
        # A radio is a choice, not a toggle: clicking never unchecks it.
        self.value = True


class OptionsScreen(WizardScreen):
    STEP = 2
    CONTEXT = "wizard.options"

    def __init__(self, strings, **kwargs) -> None:
        super().__init__(strings, **kwargs)
        self._labels: dict[str, str] = {}

    def body(self) -> ComposeResult:
        s = self.strings
        opts = self.app.opts
        self._labels = {}

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
                with Container(id="sources"):
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
        self._apply_layout(self.app.size.width, self.app.size.height)
        first = self.query_one("#source_" + self.app.opts.source, RadioButton)
        first.value = True
        self._show_detail("source_" + self.app.opts.source)
        # The form always has a row: the footer describes what it can do.
        first.focus()

    def on_resize(self, event) -> None:
        super().on_resize(event)
        self._apply_layout(event.size.width, event.size.height)

    def on_radio_button_changed(self, event: RadioButton.Changed) -> None:
        """A source was chosen (click, j/k or Enter): it is the only choice.

        Unchecked events are the ones this screen posts to clear the others;
        acting on them would undo the choice just made.
        """
        row = event.radio_button
        if event.value and row.id is not None and row.id.startswith("source_"):
            self._select_source(row.id.removeprefix("source_"))

    def _select_source(self, source: str) -> None:
        ident = "source_" + source
        for row in self.query(SourceRow):
            if row.value != (row.id == ident):
                row.value = row.id == ident
            self._relabel(row, radio=True)
        if source != self.app.opts.source:
            self.app.opts.source = source
            self.app.invalidate_prepared()
        self._show_detail(ident)

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

    # -- two blocks: the source choice, then the options below -------------
    def _rows(self, idents) -> list[Checkbox | RadioButton]:
        rows = []
        for ident in idents:
            found = self.query("#" + ident)
            widget = found.first() if found else None
            if widget is not None and not widget.disabled:
                rows.append(widget)
        return rows

    def _source_rows(self) -> list[RadioButton]:
        return self._rows(SOURCE_ROWS)

    def _lower_rows(self) -> list[Checkbox]:
        return self._rows(LOWER_ROWS)

    def _selected_source(self) -> RadioButton:
        return self.query_one("#source_" + self.app.opts.source, RadioButton)

    def action_option_pick(self, step: int) -> None:
        """Inside 安装来源 the arrows only change the source; no crossing."""
        rows = self._source_rows()
        if not rows:
            return
        current = self.focused if self.focused in rows else None
        if current is not None:
            index = rows.index(current) + step
        else:
            index = next((i for i, row in enumerate(rows) if row.value), 0)
        target = rows[max(0, min(index, len(rows) - 1))]
        target.focus()
        self._select_source(target.id.removeprefix("source_"))

    def action_option_below(self) -> None:
        """Enter on a source steps down into the options below."""
        rows = self._lower_rows()
        if rows:
            rows[0].focus()

    def action_option_move(self, step: int) -> None:
        """The lower block keeps its own cursor; its first row leads back up."""
        rows = self._lower_rows()
        if not rows:
            return
        current = self.focused
        if current not in rows:
            rows[0].focus()
            return
        index = rows.index(current)
        if index == 0 and step < 0:
            self._selected_source().focus()
            return
        rows[max(0, min(index + step, len(rows) - 1))].focus()

    def action_option_activate(self) -> None:
        """Enter on a lower row toggles its checkbox."""
        row = self.focused
        if isinstance(row, CheckRow) and not row.disabled:
            row.value = not row.value

    def action_option_toggle(self) -> None:
        """Space keeps its checkbox meaning; it never selects a source."""
        widget = self.focused
        if isinstance(widget, CheckRow) and not widget.disabled:
            widget.value = not widget.value

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
