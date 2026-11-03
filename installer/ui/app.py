"""The Textual installer: fixed chrome, one screen per wizard step.

Preparation and installation run in thread workers; every line they produce
arrives as a :class:`~installer.core.events.Event` and is handed to the active
screen on the event loop, so nothing blocks the UI and progress is only ever
what the runner really reported.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque

from textual import work
from textual.app import App

from .. import VERSION, workflow
from ..core.events import Event
from ..core.session import InstallSession
from ..detect import System, detect
from ..paths import Paths
from ..plan import Options, build_plan
from ..strings import Strings, choose_language
from .screens.installation import InstallationScreen
from .screens.result import ResultScreen
from .screens.review import ReviewScreen
from .screens.welcome import WelcomeScreen


class KosApp(App):
    CSS_PATH = "theme/app.tcss"

    def __init__(self, lang: str | None = None, system: System | None = None,
                 paths: Paths | None = None, *, prepare=None,
                 session_factory=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.lang, _ = choose_language(lang)
        self.strings = Strings(self.lang)
        self.paths = paths or Paths.resolve()
        self.system = system or detect(root=self.paths.source_root)
        self.title = f"{self.strings('title')} · NextKDE"
        self.sub_title = f"v{VERSION}"

        self.opts = Options()
        self.prepared = None            # PreparedSource, once obtained
        self.preparation = None         # the workflow.Preparation it came from
        self.prepare_error = ""
        self.steps = []
        self.exit_code = 0
        self.cancel_event = threading.Event()
        self.session = None             # the last InstallSession
        self.install_worker = None
        self.prepare_worker = None
        self.log_tail: deque[str] = deque(maxlen=8)
        self.log_path = self._new_log_path()
        self.prepare_log_path = self.paths.log_dir / "prepare.log"
        # Injected by tests: preparation and the object that runs a plan.
        self._prepare_fn = prepare or workflow.begin
        self._session_factory = session_factory

    def on_mount(self) -> None:
        self.push_screen(WelcomeScreen(self.strings))

    # -- wizard state ----------------------------------------------------
    def invalidate_prepared(self) -> None:
        self.prepared = None
        self.prepare_error = ""

    def plan_steps(self):
        return build_plan(self.system.family, self.opts, self.paths, self.prepared)

    def _new_log_path(self):
        return self.paths.log_dir / time.strftime("install-%Y%m%d-%H%M%S.log")

    def start_install(self) -> None:
        """Enter from Review: prepare the source if needed, then run the plan."""
        mode = workflow.MODES.get(self.opts.source)
        prepared = self.prepared if (self.prepared is not None
                                     and self.prepared.mode == mode) else None
        self.prepared = prepared
        self.prepare_error = ""
        self.exit_code = 0
        self.cancel_event = threading.Event()
        self.log_tail.clear()
        self.log_path = self._new_log_path()
        if prepared is not None:
            self.steps = build_plan(self.system.family, self.opts, self.paths,
                                    prepared)
            self.push_screen(InstallationScreen(self.strings, self.steps,
                                                self.log_path))
            self.install_worker = self._run_install(str(prepared.path))
        else:
            self.steps = []
            self.push_screen(InstallationScreen(self.strings, (),
                                                self.prepare_log_path))
            self.prepare_worker = self._run_prepare()

    def _new_session(self, steps, log_path, root):
        if self._session_factory is not None:
            return self._session_factory(steps, log_path, root)
        return InstallSession(self.paths, steps, log_path, root=root)

    # -- workers ---------------------------------------------------------
    @work(thread=True, exit_on_error=False)
    def _run_prepare(self) -> None:
        try:
            preparation = self._prepare_fn(self.opts.source, self.opts, self.paths)
            if preparation.steps:
                # Stream the one clone step; finish() then verifies it in place.
                # The clone targets an absolute path, so any existing directory
                # will do as cwd; the temporary's parent is created already.
                root = (preparation.temporary.parent if preparation.temporary
                        else self.paths.source_root)
                session = self._new_session(preparation.steps,
                                            self.prepare_log_path, root)
                code = session.run(self._emit, self.cancel_event)
                if code == 130:
                    self._call(self._prepare_cancelled)
                    return
                if code:
                    detail = session.tail[-1][1] if getattr(session, "tail", None) else ""
                    raise ValueError(detail or self.strings("prepare_failed"))
            prepared = preparation.finish()
        except Exception as error:  # any failure returns to Review with the reason
            self._call(self._prepare_failed, str(error))
            return
        self._call(self._prepare_ok, preparation, prepared)

    @work(thread=True, exit_on_error=False)
    def _run_install(self, root: str) -> None:
        session = self._new_session(self.steps, self.log_path, root)
        self.session = session
        try:
            code = session.run(self._emit, self.cancel_event)
        except Exception as error:  # the session handles step failures itself
            self.log_tail.append(str(error))
            code = 1
        self._call(self._install_finished, session, code)

    def _emit(self, event: Event) -> None:
        """From a worker thread: move the event onto the event loop."""
        try:
            self.call_from_thread(self._event, event)
        except RuntimeError:
            pass  # the app is shutting down; the session still reaps its child

    def _call(self, callback, *args) -> None:
        try:
            self.call_from_thread(callback, *args)
        except RuntimeError:
            pass

    # -- worker results (event loop) -------------------------------------
    def _event(self, event: Event) -> None:
        if event.kind == "log":
            self.log_tail.append(event.text)
        if isinstance(self.screen, InstallationScreen):
            self.screen.handle(event)

    def _prepare_ok(self, preparation, prepared) -> None:
        self.preparation = preparation
        self.prepared = prepared
        self.steps = build_plan(self.system.family, self.opts, self.paths, prepared)
        if isinstance(self.screen, InstallationScreen):
            self.screen.start_stages(self.steps, self.log_path)
        self.install_worker = self._run_install(str(prepared.path))

    def _prepare_failed(self, error: str) -> None:
        self.prepare_error = error
        if isinstance(self.screen, InstallationScreen):
            self.pop_screen()
        if isinstance(self.screen, ReviewScreen):
            self.screen.reload()

    def _prepare_cancelled(self) -> None:
        """Cancelling the clone is a cancelled install, not a failed one."""
        if isinstance(self.screen, InstallationScreen):
            self.pop_screen()
        self.exit_code = 130
        self.push_screen(
            ResultScreen(self.strings, "cancelled", exit_code=130,
                         log_path=self.prepare_log_path),
            callback=self._result_dismissed)

    def _install_finished(self, session, code: int) -> None:
        self.exit_code = code
        result = getattr(session, "result", "")
        if not result:
            result = "cancelled" if code == 130 else "failed" if code else "ok"
        index = getattr(session, "failed_index", None)
        failed_title = (self.steps[index - 1].title
                        if index and 1 <= index <= len(self.steps) else "")
        self.push_screen(
            ResultScreen(self.strings, result, exit_code=code,
                         failed_title=failed_title, log_path=self.log_path,
                         log_tail=list(self.log_tail), steps=self.steps),
            callback=self._result_dismissed)

    def _result_dismissed(self, value: str | None) -> None:
        if value == "retry":
            below = self._screen_stack[-2] if len(self._screen_stack) > 1 else None
            if isinstance(below, InstallationScreen):
                self.pop_screen()  # drop Installation, back to Review
            if isinstance(self.screen, ReviewScreen):
                self.screen.reload()
        elif value == "quit":
            self.exit(self.exit_code)

    # -- cancel and quit -------------------------------------------------
    def cancel_install(self) -> None:
        self.cancel_event.set()
        if isinstance(self.screen, InstallationScreen):
            self.screen.note_cancel()

    async def action_quit(self) -> None:
        """Cancel any running worker and wait until its child is reaped."""
        self.cancel_event.set()
        for worker in (self.install_worker, self.prepare_worker):
            if worker is not None and not worker.is_finished:
                try:
                    await asyncio.wait_for(worker.wait(), timeout=10)
                except Exception:
                    pass
        self.exit(self.exit_code)

    async def on_unmount(self) -> None:
        # Last resort: never leave an install child running behind a closed UI.
        self.cancel_event.set()
        for worker in (self.install_worker, self.prepare_worker):
            if worker is not None and not worker.is_finished:
                try:
                    await asyncio.wait_for(worker.wait(), timeout=10)
                except Exception:
                    pass


def main() -> int:
    KosApp().run()
    return 0
