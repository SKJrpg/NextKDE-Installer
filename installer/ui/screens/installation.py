"""Installation: the stage list, honest progress, the live log and cancel."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, LoadingIndicator, ProgressBar, RichLog, Static

from ...core.events import Event
from . import WizardScreen

UNICODE = {"done": "✔", "current": "▸", "waiting": "·", "failed": "✖",
           "skipped": "·"}
ASCII = {"done": "+", "current": ">", "waiting": ".", "failed": "x",
         "skipped": "."}


class InstallationScreen(WizardScreen):
    STEP = 4
    KEYS = (("ctrl+c", "cancel", "key_cancel"),)

    def __init__(self, strings, steps=(), log_path=None, **kwargs) -> None:
        super().__init__(strings, **kwargs)
        self.steps = list(steps)
        self.log_path = log_path
        self.states: list[str] = ["waiting"] * len(self.steps)
        self.state = ""            # header word while nothing has happened
        self.current = ""          # title of the running stage
        self.ready = False         # False until on_mount has filled the widgets
        self.pending: list[Event] = []
        self.pending_stages = None

    def body(self) -> ComposeResult:
        with Horizontal(id="install_head_row"):
            yield Static(id="install_head")
            yield LoadingIndicator(id="activity")
        with VerticalScroll(id="stages_box"):
            yield Static(id="stages")
        yield ProgressBar(id="progress", total=None)
        yield Static(id="progress_state")
        yield RichLog(id="log", max_lines=2000, wrap=False)
        yield Static(id="log_path")
        yield Button(self.strings("cancel"), id="cancel", variant="error")

    def on_mount(self) -> None:
        self.ready = True
        self._paint()
        self.query_one("#progress", ProgressBar).update(total=None)
        self.query_one("#progress_state", Static).update(
            self.strings("install_no_progress"))
        if self.pending_stages is not None:
            self.start_stages(*self.pending_stages)
            self.pending_stages = None
        queued, self.pending = self.pending, []
        for event in queued:
            self._apply(event)

    # -- data in ---------------------------------------------------------
    def start_stages(self, steps, log_path) -> None:
        """Replace the preparation placeholder with the real plan."""
        if not self.ready:
            self.pending_stages = (steps, log_path)
            return
        self.steps = list(steps)
        self.states = ["waiting"] * len(self.steps)
        self.log_path = log_path
        self.current = ""
        log = self.query_one("#log", RichLog)
        log.clear()
        self._paint()
        self.query_one("#progress", ProgressBar).update(total=None, progress=0)
        self.query_one("#progress_state", Static).update(
            self.strings("install_no_progress"))

    def handle(self, event: Event) -> None:
        if not self.ready:
            self.pending.append(event)
            return
        self._apply(event)

    def _apply(self, event: Event) -> None:
        if event.kind == "stage":
            self._on_stage(event)
        elif event.kind == "log":
            self.query_one("#log", RichLog).write(event.text)
        elif event.kind == "failed":
            if 1 <= event.index <= len(self.states):
                self.states[event.index - 1] = "failed"
            self.current = ""
            self.state = "install_failed"
            self.query_one("#progress", ProgressBar).update(total=None)
            self._paint()
            self.stop_activity()
        elif event.kind == "cancelled":
            for index, state in enumerate(self.states):
                if state == "current":
                    self.states[index] = "failed"
            self.state = "cancelled"
            self.query_one("#progress", ProgressBar).update(total=None)
            self._paint()
            self.stop_activity()
        elif event.kind == "done":
            for index, step in enumerate(self.steps):
                if self.states[index] not in ("failed", "skipped"):
                    self.states[index] = "skipped" if not step.argv else "done"
            self.current = ""
            self.state = "install_done"
            self.query_one("#progress", ProgressBar).update(total=100, progress=100)
            self.query_one("#progress_state", Static).update("100%")
            self._paint()
            self.stop_activity()

    def stop_activity(self) -> None:
        """The spinner means "still running"; drop it the moment that is untrue."""
        for indicator in self.query("#activity"):
            indicator.remove()

    def note_cancel(self) -> None:
        self.state = "install_cancelling"
        self._paint()

    def _on_stage(self, event: Event) -> None:
        bar = self.query_one("#progress", ProgressBar)
        if not self.steps:
            # Source preparation: one streamed clone, no plan yet.
            self.current = event.text
            self.state = "prepare_running"
            self._paint()
        else:
            for index in range(max(0, event.index - 1)):
                if index < len(self.states) and self.states[index] not in ("failed",
                                                                          "skipped"):
                    self.states[index] = ("skipped" if not self.steps[index].argv
                                          else "done")
            if 1 <= event.index <= len(self.states):
                self.states[event.index - 1] = "current"
            self.current = event.text
            self.state = "install_running"
            self._paint()
        if event.fraction is not None:
            bar.update(total=100, progress=event.fraction * 100)
            label = f"{int(event.fraction * 100):3d}%"
        else:
            bar.update(total=None)
            label = self.strings("install_no_progress")
        self.query_one("#progress_state", Static).update(label)

    # -- drawing ---------------------------------------------------------
    def _paint(self) -> None:
        s = self.strings
        self.query_one("#install_head", Static).update(self._head())
        self.query_one("#stages", Static).update(self._stage_text())
        self.query_one("#log_path", Static).update(
            Text(s("log_path") + str(self.log_path or ""), style="dim"))

    def _head(self) -> Text:
        s = self.strings
        if self.state:
            word = s(self.state)
        elif self.steps:
            word = s("install_running")
        else:
            word = s("prepare_running")
        text = Text(word, style="bold")
        if self.current and self.steps:
            text.append(f" · {self.current}", style="bold")
        return text

    def _stage_text(self) -> Text:
        s = self.strings
        glyphs = ASCII if s.ascii else UNICODE
        text = Text()
        if not self.steps:
            if self.current:
                text.append(f"{glyphs['current']} {self.current}\n", style="bold")
            return text  # the header already says the source is being prepared
        for index, step in enumerate(self.steps):
            state = self.states[index]
            text.append(f"{glyphs[state]} {index + 1}. {step.title}", style=(
                "bold" if state == "current" else "red" if state == "failed"
                else "green" if state == "done" else "dim"))
            text.append(f"  [{s('stage_' + ('running' if state == 'current' else state))}]",
                        style="dim")
            if index < len(self.steps) - 1:
                text.append("\n")
        return text

    # -- cancel ----------------------------------------------------------
    def action_cancel(self) -> None:
        self.app.cancel_install()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.app.cancel_install()
