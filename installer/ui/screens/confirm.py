"""Confirm: the last page before anything changes.

Y installs, N goes back. Nothing else does anything here: Enter, Tab, the
arrows and the digits are inert, so a stray key cannot leave the page or start
the install. Shift+Tab and Esc are aliases for N.
"""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from . import WizardScreen


class ConfirmScreen(WizardScreen):
    STEP = 3
    JUMP = False
    CONTEXT = "wizard.confirm"

    def __init__(self, strings, steps: int = 0, **kwargs) -> None:
        super().__init__(strings, **kwargs)
        self.steps = steps

    def body(self) -> ComposeResult:
        with VerticalScroll(id="confirm_scroll", can_focus=False):
            yield Static(self._summary(), id="confirm_page")
        yield Static(self._prompt(), id="confirm_prompt")

    # -- drawing -----------------------------------------------------------
    def _prompt(self) -> Text:
        """`Y 确认（开始安装）    N 取消（返回上一步）` — the whole page."""
        s = self.strings
        return Text.assemble(
            ("Y", "bold"), " " + s("confirm_yes"),
            "    ",
            ("N", "bold"), " " + s("confirm_no"),
        )

    def _summary(self) -> Text:
        s, opts = self.strings, self.app.opts
        prepared = self.app.prepared or self.app.resolved_source
        if prepared is not None:
            ref = prepared.ref
            if prepared.tag:
                ref = f"{ref} ({prepared.tag})"
            source = (s("label_ref"), f"{ref} · {prepared.commit[:8]}")
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
        missing = self.app.system.missing_packages
        if missing:
            text.append("\n" + s("confirm_deps") % ", ".join(missing), style="yellow")
        text.append("\n" + s("review_side_takeover"), style="yellow")
        return text

    # -- keys --------------------------------------------------------------
    def action_confirm_install(self) -> None:
        """Y: the one install path, and only on this page."""
        self.app.start_install()

    def action_confirm_back(self) -> None:
        """N, Esc and Shift+Tab all go back to the plan."""
        self.app.pop_screen()
