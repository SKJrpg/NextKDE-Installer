"""The Textual installer: fixed chrome, one screen per wizard step."""

from __future__ import annotations

from textual.app import App

from .. import VERSION
from ..detect import System, detect
from ..paths import Paths
from ..strings import Strings, choose_language
from .screens.welcome import WelcomeScreen


class KosApp(App):
    CSS_PATH = "theme/app.tcss"

    def __init__(self, lang: str | None = None, system: System | None = None,
                 paths: Paths | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.lang, _ = choose_language(lang)
        self.strings = Strings(self.lang)
        self.paths = paths or Paths.resolve()
        self.system = system or detect(root=self.paths.source_root)
        self.title = f"{self.strings('title')} · NextKDE"
        self.sub_title = f"v{VERSION}"

    def on_mount(self) -> None:
        self.push_screen(WelcomeScreen(self.strings))


def main() -> int:
    KosApp().run()
    return 0
