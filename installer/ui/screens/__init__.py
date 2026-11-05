"""Header, step sidebar and footer shared by every chrome screen.

A screen declares a context (``CONTEXT``); ``installer/ui/keymap.py`` turns it
into bindings, the footer words and the help overlay, so the three cannot
disagree. Tab pages the wizard forward and Shift+Tab back (Esc stays as an
alias); everywhere else Tab still moves focus. Quitting is Ctrl+C twice (the
app's gesture, not a table row); every other function key is Ctrl, and the
letters are Vim.
"""

from __future__ import annotations

import inspect
from functools import partial

from rich.cells import cell_len
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Header, Static

from ...strings import Strings
from .. import keymap
from ..widgets.commands import Choice, Command, CommandMenu
from ..widgets.footer import KeyFooter
from ..widgets.help import HelpScreen

STEPS = ("step_welcome", "step_system", "step_options", "step_review", "step_install")


class EnterPasses:
    """A row widget that leaves Enter to the page: only Space toggles it.

    Textual's check and radio rows bind ``enter`` themselves; the binding is
    checked before the screen's, so the key has to be dropped from the row.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._bindings.key_to_bindings.pop("enter", None)


class CursorKeys(EnterPasses):
    """A radio set whose arrows belong to the page, so moving changes the value.

    Textual's set moves an invisible cursor and waits for Space; here the
    arrow/Vim keys pick the next row, which is what the footer promises.
    Space is not a selection key here: the row under the marker is the choice.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        for key in ("up", "down", "left", "right", "space"):
            self._bindings.key_to_bindings.pop(key, None)


class ChoicePasses(EnterPasses):
    """A radio row: the page's arrows select it; Enter/Space are not needed."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._bindings.key_to_bindings.pop("space", None)


class ChromeScreen(Screen):
    """Header and footer with localized key labels; the management area."""

    CONTEXT = ""

    def __init__(self, strings: Strings, **kwargs) -> None:
        super().__init__(**kwargs)
        self.strings = strings
        self._base_bindings = self._bindings.copy()
        self._bind_keys()

    # -- the table in force here -----------------------------------------
    def contexts(self) -> set[str]:
        """This screen's context, plus the focused widget's own row context."""
        found = {self.CONTEXT}
        context = getattr(self.focused, "context", None)
        if context:
            found.add(context)
        return found

    def key_rows(self) -> list[keymap.Row]:
        """Every action available here; never trimmed, so no key goes dead."""
        return keymap.resolve(self.contexts())

    def _row_width(self, row: keymap.Row) -> int:
        """One row exactly as the footer paints it: "key label"."""
        display = (row.display
                   or keymap.display_key(row.keys[0], self.strings.ascii))
        return cell_len(display) + 1 + cell_len(self.strings(row.action.label))

    def _bind_keys(self) -> None:
        """(Re)bind the resolved rows; the footer is painted from the same rows."""
        self._bindings = self._base_bindings.copy()
        if self.CONTEXT in keymap.PAGES:
            # On a page, Tab pages; it must not fall back to focus movement
            # (Confirm deliberately binds no forward page).
            for key in ("tab", "shift+tab"):
                self._bindings.key_to_bindings.pop(key, None)
        self.paint_footer()
        for row in self.key_rows():
            if not row.targets:          # a hint for keys the widget owns
                continue
            for index, key in enumerate(row.keys + row.aliases):
                target = row.targets[index]
                if not target:
                    continue
                shown = index == 0 and not row.action.hidden and bool(row.action.label)
                # Ours wins over the screen's own default for this key.
                self._bindings.key_to_bindings.pop(key, None)
                self._bindings.bind(
                    key, target, self.strings(row.action.label) if shown else "",
                    key_display=row.action.display if shown else None,
                    priority=row.action.binding_priority)

    def _available(self, row: keymap.Row) -> bool:
        """A row the user can act on here: labelled and enabled."""
        action = row.action
        return bool(action.label
                    and self.check_action(action.id.replace(".", "_"), ()) is not False)

    def _offered(self, row: keymap.Row) -> bool:
        return self._available(row) and not row.action.hidden

    def footer_rows(self) -> list[keymap.Row]:
        """What the hint line shows: the offered rows that fit the width."""
        rows = [row for row in self.key_rows() if self._offered(row)]
        width = self.size.width
        if width <= 0:
            return rows
        return keymap.fit(rows, max(20, width - 2), self._row_width)

    def paint_footer(self) -> None:
        """Paint the hint line; a no-op until the footer widget exists."""
        footers = self.query("#footer")
        if footers:
            footers.first().show(self.footer_rows(), self.strings)

    def help_rows(self) -> list[tuple[str, str]]:
        """(key, description) for the overlay: every action available here.

        The footer shows the primaries only; the overlay adds the one-letter
        Vim aliases (j/k, h/l, g/G) so the scheme is discoverable.
        """
        ascii_only = self.strings.ascii
        rows = []
        for row in self.key_rows():
            if not self._available(row) or not row.action.label:
                continue        # a hidden guard has nothing to describe
            key = row.action.display or keymap.display_key(row.keys[0], ascii_only)
            letters = [keymap.display_key(alias, ascii_only)
                       for alias in row.aliases if len(alias) == 1]
            if letters:
                key = f"{key} {'/'.join(letters)}"
            rows.append((keymap.display_key(key, ascii_only),
                         self.strings(row.action.label)))
        return rows

    def apply_language(self, strings: Strings) -> None:
        self.strings = strings
        self._bind_keys()

    # -- the command menu -------------------------------------------------
    def commands(self) -> list[Command]:
        """Everything this page can run, in one list; subclasses add their own."""
        s, app = self.strings, self.app
        here = self.CONTEXT in keymap.MENUS
        rows = [Command("manage", s("nav_manage"), self._open_management,
                        enabled=not here,
                        reason=s("cmd_here") if here else "")]
        rows += self.context_commands()
        modes = ("system", "dark", "light")
        rows.append(Command(
            "theme", s("cmd_theme"), choices=tuple(
                Choice(s("theme_" + mode), partial(app.set_theme, mode))
                for mode in modes),
            selected=modes.index(app.theme_mode)))
        rows.append(Command(
            "lang", s("cmd_language"), choices=(
                Choice("中文", partial(app.set_language, "zh")),
                Choice("English", partial(app.set_language, "en"))),
            selected=0 if app.lang == "zh" else 1))
        rows += [
            Command("help", s("cmd_help"), self.action_help_open, shortcut="ctrl+k"),
            Command("about", s("about_title"), self._open_about),
            Command("quit", s("quit"), self._quit),
        ]
        return rows

    def context_commands(self) -> list[Command]:
        """The page's own rows, between 管理 and the shared ones."""
        return []

    def action_app_commands(self) -> None:
        self.app.push_screen(CommandMenu(self.strings, self.commands()),
                             callback=self._command_chosen)

    def _command_chosen(self, result) -> None:
        if result is None:
            return
        if isinstance(result, tuple):
            if result:              # a picker applies after the menu is gone
                self.app.run_worker(self._apply_choices(result))
            return
        value = result.run()
        if inspect.isawaitable(value):
            self.app.run_worker(value)

    async def _apply_choices(self, runs) -> None:
        for run in runs:
            value = run()
            if inspect.isawaitable(value):
                await value

    def _open_management(self) -> None:
        from .management import ManagementScreen

        self.app.push_screen(ManagementScreen(self.strings))

    def _open_about(self) -> None:
        from ..widgets.about import AboutScreen

        self.app.push_screen(AboutScreen())

    def _quit(self) -> None:
        self.app.exit(self.app.exit_code)

    # -- shared actions ---------------------------------------------------
    def action_help_open(self) -> None:
        self.app.push_screen(HelpScreen(self.strings, self.help_rows()))

    def action_run_abort(self) -> None:
        self.app.abort()

    def action_run_guard(self) -> None:
        """A running step owns Ctrl+C, so the app's quit gesture cannot fire."""

    def action_focus_next(self) -> None:
        self.app.action_focus_next()

    def action_focus_prev(self) -> None:
        self.app.action_focus_previous()

    # -- layout -----------------------------------------------------------
    def on_descendant_focus(self, event) -> None:
        # A focused row can bring its own context; the footer follows it.
        self._bind_keys()
        self.refresh_bindings()

    def on_resize(self, event) -> None:
        self._bind_keys()
        self.refresh_bindings()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield from self.body()
        yield KeyFooter(id="footer")

    def body(self):
        """The widgets of this screen, between header and footer."""
        return iter(())


class WizardScreen(ChromeScreen):
    """One wizard step inside the fixed chrome."""

    STEP = 0
    # Jumping back is safe only where no worker is running behind the screen.
    JUMP = True

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="body"):
            yield Static(self._sidebar(), id="sidebar")
            with Vertical(id="main"):
                yield from self.body()
        yield KeyFooter(id="footer")

    def _sidebar(self) -> Text:
        text = Text()
        for index, key in enumerate(STEPS):
            label = self.strings(key)
            if index == self.STEP:
                text.append(f"▸ {label}", style="bold")
            elif index < self.STEP:
                text.append(f"✔ {label}", style=self.app.secondary_style)
            else:
                text.append(f"  {label}", style=self.app.secondary_style)
            text.append("\n" if index < len(STEPS) - 1 else "")
        return text

    # -- navigation ------------------------------------------------------
    def _reachable(self, index: int) -> bool:
        return 0 <= index < len(STEPS) and index <= self.STEP

    def goto_step(self, index: int) -> None:
        """Click a step already done or current; a later one does nothing.

        Each pop is started, not awaited: awaiting one from inside a click
        handler would wait for the very screen handling the event.
        """
        if not self.JUMP or index == self.STEP or not self._reachable(index):
            return
        while isinstance(self.app.screen, WizardScreen) and self.app.screen.STEP > index:
            self.app.pop_screen()

    async def on_click(self, event) -> None:
        # The sidebar is a column of steps; row 0 sits under its top padding.
        if event.widget is not None and event.widget.id == "sidebar":
            self.goto_step(event.y - 1)
