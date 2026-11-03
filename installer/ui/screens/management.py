"""Management: the entry list, its counts, and one backend action at a time.

Every action runs through the app's session worker (never a subprocess on the
event loop) and streams its log into the pane under the list. A successful
action reloads the list it changed; a failed one keeps the list and leaves the
error tail visible.
"""

from __future__ import annotations

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.widgets import OptionList, RichLog, Static
from textual.widgets.option_list import Option

from ... import manage
from ...core.events import Event
from ..widgets.confirm import ConfirmDialog
from . import ChromeScreen


class ManageScreen(ChromeScreen):
    """A list from ``manage`` with the action log pane beneath it."""

    def __init__(self, strings, **kwargs) -> None:
        super().__init__(strings, **kwargs)
        self.busy = False          # True while an action worker is running
        self.generation = 0        # drops a reload's answer if a newer one began

    # -- layout ----------------------------------------------------------
    def body(self) -> ComposeResult:
        yield Static(id="manage_head")
        yield OptionList(id="manage_list")
        yield Static(id="action_status")
        yield RichLog(id="action_log", max_lines=500, wrap=False)

    def on_mount(self) -> None:
        self.query_one("#manage_head", Static).update(self.head())
        self.reload()

    def head(self) -> Text:
        return Text(self.strings("nav_manage"), style="bold")

    # -- data in (worker: manage shells out) -----------------------------
    def fetch(self):
        """The list to show; runs in a thread, so it may shell out."""
        return []

    def fill(self, data) -> None:
        """Paint ``data`` onto the widgets; runs on the event loop."""

    @work(thread=True, exit_on_error=False)
    def load(self, generation: int) -> None:
        try:
            data = self.fetch()
        except Exception as error:      # a broken backend must not kill the UI
            data = error
        try:
            self.app.call_from_thread(self._loaded, generation, data)
        except RuntimeError:
            pass                        # the screen went away first

    def _loaded(self, generation: int, data) -> None:
        if not self.is_mounted or generation != self.generation:
            return
        if isinstance(data, Exception):
            self.note(str(data), "red")
            return
        self.fill(data)

    def reload(self) -> None:
        self.generation += 1
        self.load(self.generation)

    def fill_list(self, options: list[Option]) -> None:
        """Replace the rows, keeping the highlight where it was."""
        list_ = self.query_one("#manage_list", OptionList)
        index = list_.highlighted or 0
        list_.set_options(options)
        if options:
            list_.highlighted = min(index, len(options) - 1)

    def note(self, text: str, style: str = "dim") -> None:
        self.query_one("#action_status", Static).update(Text(text, style=style))

    # -- one action at a time --------------------------------------------
    def start_action(self, title: str, step) -> None:
        if self.busy:            # one backend action at a time
            return
        self.app.start_action(self, title, [step])

    def action_started(self, title: str, log_path) -> None:
        self.busy = True
        self.query_one("#action_log", RichLog).clear()
        self.note(title + "  " + str(log_path), "bold")

    def handle(self, event: Event) -> None:
        if event.kind == "log":
            self.query_one("#action_log", RichLog).write(event.text)
        elif event.kind == "stage":
            self.note(event.text, "bold")

    def note_cancel(self) -> None:
        self.note(self.strings("install_cancelling"), "yellow")

    def handle_action_done(self, session, code: int) -> None:
        self.busy = False
        if code == 0:
            self.note(self.strings("action_ok"), "green")
            self.reload()
            return
        word = "cancelled" if code == 130 else "action_failed"
        self.note(f"{self.strings(word)} ({code})", "red")
        log = self.query_one("#action_log", RichLog)
        if not log.lines:       # nothing streamed: the tail is all there is
            for _level, text in session.tail[-4:]:
                log.write(text)

    def action_cancel_action(self) -> None:
        if self.busy:
            self.app.cancel_action()

    def action_back(self) -> None:
        self.app.pop_screen()


class ManagementScreen(ManageScreen):
    KEYS = (("escape", "back", "key_back"),
            ("ctrl+c", "cancel_action", "key_cancel"))

    def fetch(self):
        paths = self.app.paths
        return manage.units(paths.source_root), manage.snapshots(paths.source_root)

    def fill(self, data) -> None:
        self.units, self.snapshots = data
        entries = (
            ("units", self.strings("manage_units"), str(len(self.units))),
            ("snapshots", self.strings("manage_snapshots"), str(len(self.snapshots))),
            ("doctor", self.strings("manage_doctor"), ""),
            ("logs", self.strings("manage_logs"), ""),
            ("uninstall", self.strings("manage_uninstall"), ""),
        )
        self.fill_list([Option(self._row(label, value), id=key)
                        for key, label, value in entries])

    def _row(self, label: str, value: str) -> Text:
        text = Text(f"{label:<14}")
        text.append(value, style="bold")
        return text

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        from .logs import LogsScreen
        from .snapshots import SnapshotsScreen
        from .units import UnitsScreen

        if event.option_id == "units":
            self.app.push_screen(UnitsScreen(self.strings),
                                 callback=lambda _: self.reload())
        elif event.option_id == "snapshots":
            self.app.push_screen(SnapshotsScreen(self.strings),
                                 callback=lambda _: self.reload())
        elif event.option_id == "logs":
            self.app.push_screen(LogsScreen(self.strings))
        elif event.option_id == "doctor":
            self.start_action("kosctl doctor",
                              manage.kosctl(self.app.paths.source_root, "doctor"))
        elif event.option_id == "uninstall":
            self.confirm_uninstall()

    def confirm_uninstall(self) -> None:
        self.app.push_screen(
            ConfirmDialog(self.strings, self.strings("manage_uninstall"),
                          self.strings("confirm_uninstall"), word="uninstall",
                          confirm_variant="error"),
            callback=self._uninstall)

    def _uninstall(self, yes: bool | None) -> None:
        if yes:
            self.start_action("kosctl uninstall",
                              manage.kosctl(self.app.paths.source_root, "uninstall"))
