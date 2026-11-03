"""Snapshots: create one, or roll back to the selected id after confirming."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from ... import manage
from ..widgets.confirm import ConfirmDialog
from .management import ManageScreen


class SnapshotsScreen(ManageScreen):
    KEYS = (("c", "create", "key_create"), ("escape", "back", "key_back"),
            ("ctrl+c", "cancel_action", "key_cancel"))

    def __init__(self, strings, **kwargs) -> None:
        super().__init__(strings, **kwargs)
        self.snapshots = []

    def head(self) -> Text:
        return Text(self.strings("snapshots_title"), style="bold")

    def fetch(self):
        return manage.snapshots(self.app.paths.source_root)

    def fill(self, data) -> None:
        self.snapshots = list(data)
        if not self.snapshots:
            self.note(self.strings("snapshots_none"))
        self.fill_list([Option(self._row(snapshot), id=snapshot.id)
                        for snapshot in self.snapshots])

    def _row(self, snapshot) -> Text:
        text = Text(f"{snapshot.id:<24}")
        text.append(f"{snapshot.created_at:<20}", style=self.app.secondary_style)
        text.append(snapshot.note)
        return text

    def current(self):
        option = self.query_one("#manage_list", OptionList).highlighted_option
        if option is None:
            return None
        return next((s for s in self.snapshots if s.id == option.id), None)

    def action_create(self) -> None:
        if self.busy:
            return
        self.start_action(
            "kosctl snapshot",
            manage.kosctl(self.app.paths.source_root, "snapshot", "from installer"))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        snapshot = self.current()
        if snapshot is None or self.busy:
            return
        self.app.push_screen(
            ConfirmDialog(self.strings, self.strings("manage_snapshots"),
                          f"{self.strings('confirm_rollback')}\n{snapshot.id}"),
            callback=lambda yes: self._rollback(snapshot, yes))

    def _rollback(self, snapshot, yes: bool | None) -> None:
        if yes:
            self.start_action(
                f"kosctl rollback {snapshot.id}",
                manage.kosctl(self.app.paths.source_root, "rollback", snapshot.id))
