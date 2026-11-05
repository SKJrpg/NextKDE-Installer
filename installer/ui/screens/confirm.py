"""Confirm: the last page before anything changes.

Enter here is the confirmation itself, so the page opens with "back" selected:
installing takes one more deliberate move of the selection. ``1``/``2`` only
move it; they never install.
"""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import RadioButton, RadioSet, Static

from . import ChoicePasses, CursorKeys, WizardScreen


class PickRow(ChoicePasses, RadioButton):
    """A radio row whose marker is text; Enter belongs to the page."""

    BUTTON_LEFT = BUTTON_INNER = BUTTON_RIGHT = ""


class PickSet(CursorKeys, RadioSet):
    """Arrows and h/l/j/k move the choice; Enter confirms it."""


class ConfirmScreen(WizardScreen):
    STEP = 3
    JUMP = False
    CONTEXT = "wizard.confirm"

    def __init__(self, strings, steps: int = 0, **kwargs) -> None:
        super().__init__(strings, **kwargs)
        self.steps = steps
        self.choice = "back"      # the safe half of the choice is the default

    def body(self) -> ComposeResult:
        yield Static(self._summary(), id="confirm_page")
        with PickSet(id="confirm_pick", compact=True):
            yield PickRow(self._row(False, "install"), id="install")
            yield PickRow(self._row(True, "back"), id="back", value=True)

    def on_mount(self) -> None:
        self.query_one("#back", RadioButton).focus()

    # -- drawing -----------------------------------------------------------
    def _row(self, chosen: bool, key: str) -> Text:
        on, off = ("(*)", "( )") if self.strings.ascii else ("(•)", "( )")
        text = Text(on if chosen else off, style="bold" if chosen else None)
        text.append(" " + self._numbered(key))
        return text

    def _numbered(self, key: str) -> str:
        """`[1] 开始安装` — the number is the slot, not the trigger."""
        number = "1" if key == "install" else "2"
        return f"[{number}] {self.strings('confirm_' + key)}"

    def _summary(self) -> Text:
        s, opts = self.strings, self.app.opts
        prepared = self.app.prepared
        if prepared is not None:
            source = (s("label_ref"), f"{prepared.ref} · {prepared.commit[:8]}")
        else:
            source = (s("label_source"), s("source_" + opts.source))
        pairs = [source, (s("label_path"), s("review_target"))]
        width = max(cell_len(label) for label, _ in pairs) + 2
        text = Text(s("confirm_heading"), style="bold")
        text.append("\n\n")
        if self.steps:
            text.append(s("confirm_summary") % self.steps + "\n")
        for label, value in pairs:
            text.append(f"{label:<{width}}", style=self.app.secondary_style)
            text.append(value + "\n")
        text.append("\n" + s("review_side_takeover"), style="yellow")
        return text

    # -- keys --------------------------------------------------------------
    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id != "confirm_pick" or event.pressed.id is None:
            return
        self.choice = event.pressed.id
        for button in event.radio_set.query(RadioButton):
            button.label = self._row(button.id == self.choice, button.id)

    def action_confirm_pick(self, choice: int) -> None:
        """A number moves the selection; Enter is still what acts on it."""
        self.query_one("#install" if choice == 1 else "#back", RadioButton).value = True

    def action_confirm_move(self, step: int) -> None:
        """h/l and j/k move the choice, like the arrow keys do."""
        rows = [self.query_one("#" + name, RadioButton) for name in ("install", "back")]
        current = 0 if self.choice == "install" else 1
        index = max(0, min(current + step, len(rows) - 1))
        rows[index].value = True

    def action_review_install(self) -> None:
        if self.choice == "install":
            self.app.start_install()
        else:
            self.app.pop_screen()

    def action_wizard_back(self) -> None:
        self.app.pop_screen()
