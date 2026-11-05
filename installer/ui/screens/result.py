"""Result: what happened, the log tail, and the way out."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Static

from . import WizardScreen


class ResultScreen(WizardScreen):
    STEP = 5
    JUMP = False       # the wizard has ended; retry and quit are the ways out
    CONTEXT = "wizard.result"

    def __init__(self, strings, result: str, exit_code: int = 0,
                 failed_title: str = "", log_path=None, log_tail=(),
                 steps=(), **kwargs) -> None:
        super().__init__(strings, **kwargs)
        self.result = result          # ok | failed | cancelled
        self.exit_code = exit_code
        self.failed_title = failed_title
        self.log_path = log_path
        self.log_tail = list(log_tail)
        self.steps = list(steps)

    def body(self) -> ComposeResult:
        yield Static(id="result_head")
        with VerticalScroll(id="result_body", can_focus=False):
            yield Static(id="result_text")
        with Horizontal(id="actions"):
            if self.result != "ok":
                yield Button(self.strings("retry"), id="retry")
            yield Button(self.strings("quit"), id="quit", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#result_head", Static).update(self._head())
        self.query_one("#result_text", Static).update(self._body())
        # Enter presses the safe default: retry when something failed, else quit.
        self.query_one("#retry" if self.result != "ok" else "#quit", Button).focus()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "result_retry":
            return self.result != "ok"     # nothing to retry after a success
        return True

    def _head(self) -> Text:
        s = self.strings
        if self.result == "ok":
            return Text(f"✔ {s('success_title')}", style="bold green")
        if self.result == "cancelled":
            return Text(f"⚠ {s('cancelled')}", style="bold yellow")
        return Text(f"✖ {s('failure_title')}", style="bold red")

    def _body(self) -> Text:
        s = self.strings
        quiet = self.app.secondary_style
        text = Text()
        if self.result == "ok":
            text.append(s("result_ran") + "\n", style="bold")
            for step in self.steps:
                if step.argv:
                    text.append(f"✔ {step.title}\n", style="green")
            text.append("\n")
            text.append(s("next_steps") + "\n", style="yellow")
        elif self.result == "cancelled":
            text.append(s("result_cancelled") + "\n", style="yellow")
            if self.failed_title:
                text.append(f"{s('cancelled')}: {self.failed_title}\n", style=quiet)
        else:
            if self.failed_title:
                text.append(f"{s('failed')}: {self.failed_title}\n", style="bold red")
            text.append(f"{s('result_exit_code')}: {self.exit_code}\n")
            text.append(s("result_retry_safe") + "\n", style=quiet)
        text.append("\n")
        text.append(s("log_path") + str(self.log_path or "") + "\n", style=quiet)
        if self.result != "ok":
            text.append("\n" + s("result_tail") + "\n", style="bold")
            if self.log_tail:
                for line in self.log_tail:
                    text.append(f"  {line}\n", style=quiet)
            else:
                text.append(f"  {s('result_none_logged')}\n", style=quiet)
        return text

    def action_result_retry(self) -> None:
        if self.result != "ok":
            self.dismiss("retry")

    def action_log_open(self) -> None:
        from .logs import LogViewerScreen

        if self.log_path is not None:
            self.app.push_screen(LogViewerScreen(self.strings, self.log_path))

    def action_app_manage(self) -> None:
        from .management import ManagementScreen

        self.app.push_screen(ManagementScreen(self.strings))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "retry":
            self.dismiss("retry")
        elif event.button.id == "quit":
            self.dismiss("quit")
