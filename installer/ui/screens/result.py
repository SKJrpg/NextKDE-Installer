"""Result: what happened, the log tail, and the way out."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Static

from . import WizardScreen


class ResultScreen(WizardScreen):
    STEP = 5
    KEYS = (("r", "retry", "key_retry"), ("enter", "quit", "key_exit"))

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
        with VerticalScroll(id="result_body"):
            yield Static(id="result_text")
        with Horizontal(id="actions"):
            if self.result != "ok":
                yield Button(self.strings("retry"), id="retry")
            yield Button(self.strings("quit"), id="quit", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#result_head", Static).update(self._head())
        self.query_one("#result_text", Static).update(self._body())

    def _head(self) -> Text:
        s = self.strings
        if self.result == "ok":
            return Text(f"✔ {s('success_title')}", style="bold green")
        if self.result == "cancelled":
            return Text(f"⚠ {s('cancelled')}", style="bold yellow")
        return Text(f"✖ {s('failure_title')}", style="bold red")

    def _body(self) -> Text:
        s = self.strings
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
                text.append(f"{s('cancelled')}: {self.failed_title}\n", style="dim")
        else:
            if self.failed_title:
                text.append(f"{s('failed')}: {self.failed_title}\n", style="bold red")
            text.append(f"{s('result_exit_code')}: {self.exit_code}\n")
            text.append(s("result_retry_safe") + "\n", style="dim")
        text.append("\n")
        text.append(s("log_path") + str(self.log_path or "") + "\n", style="dim")
        if self.result != "ok":
            text.append("\n" + s("result_tail") + "\n", style="bold")
            if self.log_tail:
                for line in self.log_tail:
                    text.append(f"  {line}\n", style="dim")
            else:
                text.append(f"  {s('result_none_logged')}\n", style="dim")
        return text

    def action_retry(self) -> None:
        if self.result != "ok":
            self.dismiss("retry")

    def action_quit(self) -> None:
        self.dismiss("quit")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "retry":
            self.dismiss("retry")
        elif event.button.id == "quit":
            self.dismiss("quit")
