"""Logs: pick a file, then read it in a scrollable, read-only viewer."""

from __future__ import annotations

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.widgets import OptionList, RichLog, Static
from textual.widgets.option_list import Option

from ... import manage
from . import ChromeScreen
from .management import ManageScreen


class LogsScreen(ManageScreen):
    CONTEXT = "list.logs"

    def __init__(self, strings, **kwargs) -> None:
        super().__init__(strings, **kwargs)
        self.files = []

    def head(self) -> Text:
        return Text(self.strings("log_title"), style="bold")

    def fetch(self):
        return manage.logs(self.app.paths.log_dir)

    def fill(self, data) -> None:
        self.files = list(data)
        if not self.files:
            self.note(self.strings("logs_none"))
        self.fill_list([Option(path.name, id=str(path)) for path in self.files])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.action_logs_open()

    def action_logs_open(self) -> None:
        option = self.query_one("#manage_list", OptionList).highlighted_option
        path = next((p for p in self.files
                     if option is not None and str(p) == option.id), None)
        if path is not None:
            self.app.push_screen(LogViewerScreen(self.strings, path))


class LogViewerScreen(ChromeScreen):
    """One log file: the only keys are scrolling and Esc."""

    CONTEXT = "log.view"

    def __init__(self, strings, path, **kwargs) -> None:
        super().__init__(strings, **kwargs)
        self.path = path

    def body(self) -> ComposeResult:
        yield Static(Text(str(self.path), style="bold"), id="manage_head")
        yield RichLog(id="log_view", max_lines=None, wrap=False)

    def on_mount(self) -> None:
        self.reader = self.read()

    @work(thread=True, exit_on_error=False)
    def read(self) -> None:
        try:
            lines = self.path.read_text(encoding="utf-8",
                                        errors="replace").splitlines()
        except OSError as error:
            lines = [str(error)]
        try:
            self.app.call_from_thread(self._show, lines)
        except RuntimeError:
            pass

    def _show(self, lines: list[str]) -> None:
        if not self.is_mounted:
            return
        log = self.query_one("#log_view", RichLog)
        log.clear()
        for line in lines:
            log.write(line)

    def action_wizard_back(self) -> None:
        self.app.pop_screen()
