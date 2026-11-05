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
from pathlib import Path

from textual import work
from textual.app import App
from textual.screen import ModalScreen

from .. import VERSION, workflow
from ..backend import contract, probe
from ..backend.models import BackendIncompatible, BackendInfo
from ..core.askpass import Askpass
from ..core.events import Event
from ..core.session import InstallSession
from ..detect import System, detect
from ..paths import Paths
from ..plan import Options, build_plan
from ..strings import Strings, choose_language
from .screens.confirm import ConfirmScreen
from .screens.installation import InstallationScreen
from .screens.result import ResultScreen
from .screens.review import ReviewScreen
from .screens.welcome import WelcomeScreen
from .theme import resolve_mode
from .widgets.confirm import ConfirmDialog
from .widgets.password import PasswordDialog


class KosApp(App, inherit_bindings=False):
    # The first Ctrl+C only warns; a second one within this window quits.
    CTRL_C_QUIT_WINDOW = 5.0
    CSS_PATH = "theme/app.tcss"
    # A developer affordance; its footer hint has no place in an installer.
    ENABLE_COMMAND_PALETTE = False
    # Inherited bindings are off, so Textual's ctrl+q quit is really gone.
    # Ctrl+C twice quits; while something runs, the screen's guard takes it.
    BINDINGS = [("ctrl+c", "help_quit", "")]

    def __init__(self, lang: str | None = None, system: System | None = None,
                 paths: Paths | None = None, *, opts: Options | None = None,
                 backend: BackendInfo | None = None,
                 prepare=None, session_factory=None, mode: str | None = None,
                 **kwargs) -> None:
        # Native ANSI so the terminal's own background and palette show through
        # instead of Textual painting its theme's colours over them.
        super().__init__(ansi_color=True, **kwargs)
        # "system" (or None) follows the terminal; --theme / KOS_THEME / COLORFGBG
        # decide which. Textual's own theme stays out of it: ansi_default is the
        # terminal's background either way. The choice is kept so the command
        # menu can mark it; only the dark flag is resolved from it.
        self.theme_mode = mode if mode in ("system", "dark", "light") else "system"
        self.dark = resolve_mode(self.theme_mode) == "dark"
        # Secondary text: dim is quieter on a dark terminal, but on a light one it
        # only fades towards white; ANSI 8 stays a readable grey there.
        self.secondary_style = "dim" if self.dark else "bright_black"
        self.lang, _ = choose_language(lang)
        self.strings = Strings(self.lang)
        self.paths = paths or Paths.resolve()
        self.system = system or detect(root=self.paths.source_root)
        self.title = f"{self.strings('title')} · NextKDE"
        self.sub_title = f"v{VERSION}"

        # The CLI/config Options: the wizard opens with those already selected.
        self.opts = opts if opts is not None else Options()
        # The backend the prepared checkout will offer: passed in by tests or a
        # caller, otherwise read once from --root, then again after preparation.
        self.backend = backend
        self.backend_error = ""
        if backend is None:
            self._detect_backend(self.paths.source_root)
        self.prepared = None            # PreparedSource, once obtained
        self.preparation = None         # the workflow.Preparation it came from
        self.prepare_error = ""
        self.steps = []
        self.exit_code = 0
        self.cancel_event = threading.Event()
        self.session = None             # the last InstallSession
        self.askpass: Askpass | None = None   # set while a run may need a sudo password
        self._dialog_token: str | None = None  # the request the open dialog answers
        self._answered: set[str] = set()       # tokens this run has already handled
        self.install_worker = None
        self.prepare_worker = None
        self.action_worker = None
        self._ctrl_c_at = 0.0          # time.monotonic() of the last Ctrl+C
        self.action_event = threading.Event()
        self.action_screen = None       # where the running action reports
        self.log_tail: deque[str] = deque(maxlen=8)
        self._log_seq = 0               # keeps two logs from the same second apart
        self.log_path = self._new_log_path()
        self.prepare_log_path = self.paths.log_dir / "prepare.log"
        # Injected by tests: preparation and the object that runs a plan.
        self._prepare_fn = prepare or workflow.begin
        self._session_factory = session_factory

    def action_help_quit(self) -> None:
        """Ctrl+C twice quits; the first press only says so.

        A modal owns its own keys (the quit/abort questions, the password
        prompt, the help overlay), so a second press there must not bypass it.
        """
        if isinstance(self.screen, ModalScreen):
            return
        now = time.monotonic()
        if now - self._ctrl_c_at <= self.CTRL_C_QUIT_WINDOW:
            self.exit()
            return
        self._ctrl_c_at = now
        self.notify(self.strings("ctrl_c_hint"))

    def on_mount(self) -> None:
        self.push_screen(WelcomeScreen(self.strings))
        # A sudo call may block at any point in a run; this answers its request.
        self.set_interval(0.15, self._poll_askpass)

    # -- wizard state ----------------------------------------------------
    def _detect_backend(self, root) -> None:
        """Read the contract or probe once; leave "unknown" for a non-product dir."""
        root = Path(root)
        if not (root / "tools" / "kosctl").is_file() and not (
                root / "packaging" / "installer-contract.json").is_file():
            return
        try:
            self.backend = contract.read(root) or probe.detect(root)
            self.backend_error = ""
        except BackendIncompatible as error:
            self.backend, self.backend_error = None, str(error)

    def invalidate_prepared(self) -> None:
        self.prepared = None
        self.prepare_error = ""

    async def set_theme(self, choice: str) -> None:
        """Switch the appearance for this session; nothing is written to disk."""
        if choice not in ("system", "dark", "light") or choice == self.theme_mode:
            return
        self.theme_mode = choice
        dark = resolve_mode(choice) == "dark"
        changed = dark != self.dark
        self.dark = dark
        self.secondary_style = "dim" if dark else "bright_black"
        if changed:
            # Secondary text embeds its style, so the page is rebuilt once.
            await self.screen.recompose()

    async def set_language(self, lang: str) -> None:
        """Switch every label now; the wizard keeps its place and its state."""
        if lang == self.lang:
            return
        self.lang = lang
        self.strings = Strings(lang)
        self.title = f"{self.strings('title')} · NextKDE"
        for screen in self._screen_stack:
            if hasattr(screen, "apply_language"):
                screen.apply_language(self.strings)
        await self.screen.recompose()
        self.screen.refresh_bindings()   # the fresh footer reads them on compose

    def _new_log_path(self, prefix: str = "install"):
        self._log_seq += 1
        return self.paths.log_dir / time.strftime(
            f"{prefix}-%Y%m%d-%H%M%S-{self._log_seq}.log")

    def start_install(self) -> None:
        """Enter from Review: run the plan; sudo asks when it needs a password."""
        prepared = self._prepared_source()
        self.prepare_error = ""
        self.exit_code = 0
        self.cancel_event = threading.Event()
        self.log_tail.clear()
        self.log_path = self._new_log_path()
        self._new_askpass()
        if prepared is not None:
            self.steps = build_plan(self.system.family, self.opts, self.paths,
                                    prepared, backend=self.backend,
                                    deps_missing=bool(self.system.missing_packages))
            self.push_screen(InstallationScreen(self.strings, self.steps,
                                                self.log_path))
            self.install_worker = self._run_install(str(prepared.path))
        else:
            self.steps = []
            # Empty it first: a failure before git starts must not show the
            # previous attempt's successful clone under "see the log".
            self.prepare_log_path.parent.mkdir(parents=True, exist_ok=True)
            self.prepare_log_path.write_text("", encoding="utf-8")
            self.push_screen(InstallationScreen(self.strings, (),
                                                self.prepare_log_path))
            self.prepare_worker = self._run_prepare()

    def _prepared_source(self):
        mode = workflow.MODES.get(self.opts.source)
        prepared = self.prepared if (self.prepared is not None
                                     and self.prepared.mode == mode) else None
        self.prepared = prepared
        return prepared

    def _new_askpass(self) -> None:
        """One channel per run: children get its env, no password exists yet."""
        self._close_askpass()
        self.askpass = Askpass()
        self._dialog_token = None
        self._answered.clear()

    def _poll_askpass(self) -> None:
        """A blocked sudo call left a request: ask for it, one dialog at a time."""
        askpass = self.askpass
        if askpass is None or self._dialog_token is not None:
            return
        token = askpass.pending()
        if token is None or token in self._answered:
            return
        self._dialog_token = token
        self.push_screen(PasswordDialog(self.strings),
                         lambda password: self._password_answer(token, password))

    def _password_answer(self, token: str, password: str | None) -> None:
        self._dialog_token = None
        askpass = self.askpass
        if askpass is None:             # the run ended while the dialog was open
            return
        self._answered.add(token)
        if password:
            askpass.answer(token, password)
        else:
            # Denied: this request and every later one fail at once, so sudo does
            # not ask three times, and the blocked step fails instead of waiting.
            self.log_tail.append(self.strings("sudo_password_missing"))
            askpass.cancel()
            self.cancel_install()
            if self.action_screen is not None:
                self.cancel_action()
        self._poll_askpass()    # a request that arrived while the dialog was open

    def _close_askpass(self) -> None:
        askpass, self.askpass = self.askpass, None
        self._dialog_token = None
        if askpass is not None:
            askpass.close()

    def _new_session(self, steps, log_path, root):
        if self._session_factory is not None:
            return self._session_factory(steps, log_path, root)
        return InstallSession(self.paths, steps, log_path, root=root,
                              extra_env=self.askpass.env if self.askpass else None)

    # -- management actions ----------------------------------------------
    def start_action(self, screen, title: str, steps) -> None:
        """One management action, off the event loop and cancellable."""
        log_path = self._new_log_path("manage")
        self.action_event = threading.Event()
        self.action_screen = screen
        self._new_askpass()
        screen.action_started(title, log_path)
        self.action_worker = self._run_action(list(steps), log_path)

    def _emit_action(self, event: Event) -> None:
        try:
            self.call_from_thread(self._action_event, event)
        except RuntimeError:
            pass

    def _action_event(self, event: Event) -> None:
        if self.action_screen is not None and self.action_screen.is_mounted:
            self.action_screen.handle(event)

    def _action_finished(self, session, code: int) -> None:
        screen, self.action_screen = self.action_screen, None
        self._close_askpass()
        if screen is not None and screen.is_mounted:
            screen.handle_action_done(session, code)

    def cancel_action(self) -> None:
        self.action_event.set()
        if self.action_screen is not None and self.action_screen.is_mounted:
            self.action_screen.note_cancel()

    # -- workers ---------------------------------------------------------
    @work(thread=True, exit_on_error=False)
    def _run_action(self, steps, log_path) -> None:
        session = self._new_session(steps, log_path, str(self.paths.source_root))
        try:
            code = session.run(self._emit_action, self.action_event)
        except Exception as error:      # the session handles step failures itself
            session.tail = (session.tail + [("ERROR", str(error))])[-8:]
            code = 1
        self._call(self._action_finished, session, code)

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
        # The prepared workspace is the real backend, not the --root stand-in.
        self._detect_backend(prepared.path)
        if self.backend_error:
            self._prepare_failed(self.strings("backend_incompatible") % self.backend_error)
            return
        self.steps = build_plan(self.system.family, self.opts, self.paths, prepared,
                                backend=self.backend,
                                deps_missing=bool(self.system.missing_packages))
        if isinstance(self.screen, InstallationScreen):
            self.screen.start_stages(self.steps, self.log_path)
        self.install_worker = self._run_install(str(prepared.path))

    def _back_to_review(self) -> None:
        """Pop the run pages; a failure belongs on the plan, not the confirm page."""
        while isinstance(self.screen, (InstallationScreen, ConfirmScreen)):
            self.pop_screen()
        if isinstance(self.screen, ReviewScreen):
            self.screen.reload()

    def _prepare_failed(self, error: str) -> None:
        if isinstance(self.screen, ConfirmDialog):
            # The failure happened while the abort question was open: let it
            # close first, or its pop lands on the wrong screen.
            self.set_timer(0.1, lambda: self._prepare_failed(error))
            return
        self.prepare_error = error
        self._close_askpass()
        self._back_to_review()

    def _prepare_cancelled(self) -> None:
        """Cancelling the clone is a cancelled install, not a failed one."""
        if isinstance(self.screen, ConfirmDialog):
            # The abort question is still closing; its pop would remove the
            # Result screen pushed underneath it. Wait for the answer.
            self.set_timer(0.1, self._prepare_cancelled)
            return
        self._close_askpass()
        if isinstance(self.screen, InstallationScreen):
            self.pop_screen()
        self.exit_code = 130
        self.push_screen(
            ResultScreen(self.strings, "cancelled", exit_code=130,
                         log_path=self.prepare_log_path),
            callback=self._result_dismissed)

    def _install_finished(self, session, code: int) -> None:
        if isinstance(self.screen, ConfirmDialog):
            # A run can end while its abort question is open. dismiss() pops the
            # dialog right after its callback, so wait for that before stacking
            # the result, or the pop would remove the result instead.
            self.set_timer(0.1, lambda: self._install_finished(session, code))
            return
        self.exit_code = code
        if isinstance(self.screen, InstallationScreen):
            # A session that raises ends without a done/cancel event of its own.
            self.screen.stop_activity()
        if code and any("incorrect password" in text
                        for _level, text in getattr(session, "tail", [])):
            # The password was wrong: drop it so Retry asks again, and say why.
            self.log_tail.append(self.strings("sudo_password_wrong"))
        self._close_askpass()
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
            # The result screen is already popped; the run pages sit on Review.
            self._back_to_review()
        elif value == "quit":
            self.exit(self.exit_code)

    # -- cancel and quit -------------------------------------------------
    def abort(self) -> None:
        """Ctrl+Z (or the mouse button): stop the running step at once."""
        if self.action_screen is not None:
            self.cancel_action()
        else:
            self.cancel_install()

    def cancel_install(self) -> None:
        self.cancel_event.set()
        if isinstance(self.screen, InstallationScreen):
            self.screen.note_cancel()

    async def action_quit(self) -> None:
        """Cancel any running worker and wait until its child is reaped."""
        self.cancel_event.set()
        self.action_event.set()
        for worker in (self.install_worker, self.prepare_worker, self.action_worker):
            if worker is not None and not worker.is_finished:
                try:
                    await asyncio.wait_for(worker.wait(), timeout=10)
                except Exception:
                    pass
        self.exit(self.exit_code)

    async def on_unmount(self) -> None:
        # Last resort: never leave an install child running behind a closed UI.
        self.cancel_event.set()
        self.action_event.set()
        self._close_askpass()
        for worker in (self.install_worker, self.prepare_worker, self.action_worker):
            if worker is not None and not worker.is_finished:
                try:
                    await asyncio.wait_for(worker.wait(), timeout=10)
                except Exception:
                    pass


def main() -> int:
    """`python3 -m installer.ui`: the same flow and flags as `python3 -m installer`."""
    from ..__main__ import main as cli

    return cli()
