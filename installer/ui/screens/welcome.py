"""Welcome: what this is, the language, and the key that moves on."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import Static

from . import WizardScreen


class WelcomeScreen(WizardScreen):
    STEP = 0
    CONTEXT = "wizard.welcome"
    QUIT_DIRECT = True      # nothing has run yet

    def body(self) -> ComposeResult:
        yield Static(self.strings("welcome_intro"), id="intro")
        yield Static(self._language(), id="language")

    def _language(self) -> Text:
        s = self.strings
        on, off = ("(*)", "( )") if s.ascii else ("(•)", "( )")
        text = Text()
        text.append(s("label_language"), style=self.app.secondary_style)
        text.append("  ")
        for index, (code, name) in enumerate((("zh", "中文"), ("en", "English"))):
            if index:
                text.append("  ")
            text.append(on if self.app.lang == code else off,
                        style="bold" if self.app.lang == code else None)
            text.append(" " + name)
        return text

    async def action_welcome_language(self) -> None:
        await self.app.set_language("en" if self.app.lang == "zh" else "zh")

    def action_wizard_next(self) -> None:
        from .system import SystemScreen

        self.app.push_screen(SystemScreen(self.strings))

    def action_app_manage(self) -> None:
        from .management import ManagementScreen

        self.app.push_screen(ManagementScreen(self.strings))
