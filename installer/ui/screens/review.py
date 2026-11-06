"""Review: what will run, from the real plan, before anything changes."""

from __future__ import annotations

import subprocess

from rich.cells import cell_len
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from ... import workflow
from ...detect import method_label
from ...plan import build_plan, selected_apps, unsupported
from ..widgets.commands import Command
from . import WizardScreen

# A cause the user can act on, most specific first: a host that does not resolve
# is never a permissions problem.
_CAUSES = (
    (("could not resolve host", "timed out", "timeout", "network is unreachable",
      "connection refused", "connection reset", "failed to connect"),
     "advice_network"),
    (("permission denied (publickey", "authentication failed",
      "could not read username", "could not read password"), "advice_credentials"),
    # A local EACCES is not a git credential problem.
    (("permission denied", "errno 13", "read-only file system"), "advice_permissions"),
    (("no ref", "couldn't find remote ref", "unknown revision", "not our ref"),
     "advice_tag"),
)


def advice_for(error: str) -> str:
    """The string key of one line of advice for a preparation failure, or ""."""
    lowered = (error or "").lower()
    for needles, key in _CAUSES:
        if any(needle in lowered for needle in needles):
            return key
    return ""


class ReviewScreen(WizardScreen):
    STEP = 3
    CONTEXT = "wizard.review"

    def __init__(self, strings, **kwargs) -> None:
        super().__init__(strings, **kwargs)
        self.details = False
        self._source = None       # identity resolved for an unprepared source
        self._resolved = False
        self._error_shown: str | None = None   # the failure the footer was built for

    def body(self) -> ComposeResult:
        with VerticalScroll(id="review", can_focus=False):
            yield Static(id="status")
            yield Static(id="summary")
            yield Static(id="steps")
            yield Static(id="side")

    def on_mount(self) -> None:
        self.reload()
        if self.app.prepared is None and not self._resolved:
            self.resolve_source()

    @work(thread=True, exit_on_error=False)
    def resolve_source(self) -> None:
        """Resolve the workspace off the event loop: ls-remote is network I/O."""
        source = None
        try:
            source = workflow.identity(self.app.opts.source, self.app.opts,
                                       self.app.paths)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        try:
            self.app.call_from_thread(self._source_resolved, source)
        except RuntimeError:
            pass

    def _source_resolved(self, source) -> None:
        self._source = source
        self._resolved = True
        if self.is_mounted:
            self.query_one("#steps", Static).update(self._steps())

    def reload(self) -> None:
        """Rebuild every pane from the app's current options and source."""
        error = self.app.prepare_error
        # The retry/log hints come and go with the failure, so only then does
        # the footer have to re-read the bindings.
        if self._error_shown is not None and self._error_shown != error:
            self.refresh_bindings()
        self._error_shown = error
        self.query_one("#status", Static).update(self._status())
        self.query_one("#summary", Static).update(self._summary())
        self.query_one("#steps", Static).update(self._steps())
        self.query_one("#side", Static).update(self._side())

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        failed = bool(self.app.prepare_error)
        # A failed page swaps "continue/commands" for "retry/log": the plan is
        # not what the user can act on any more.
        if action in ("review_retry", "log_open"):
            return failed
        if action in ("review_continue", "review_details", "wizard_next"):
            return not failed   # a failed page has nothing to confirm
        return True

    def set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(Text(text, style="bold"))

    def _pairs(self, pairs) -> Text:
        width = max(cell_len(str(label)) for label, _ in pairs) + 2
        quiet = self.app.secondary_style
        text = Text()
        for index, (label, value) in enumerate(pairs):
            text.append(str(label) + " " * (width - cell_len(str(label))),
                        style=quiet)
            text.append(str(value))
            if index < len(pairs) - 1:
                text.append("\n")
        return text

    def _status(self) -> Text:
        if not self.app.prepare_error:
            return Text()
        # What failed, then what to do, then the raw reason: the git text
        # explains the cause, but it is not what the user should read first.
        s = self.strings
        text = Text(s("review_prepare_failed"), style="bold red")
        text.append("\n" + s("review_error_keys"), style="bold")
        advice = advice_for(self.app.prepare_error)
        if advice:
            text.append("\n" + s(advice), style="yellow")
        text.append("\n")
        text.append(self.app.prepare_error, style=self.app.secondary_style)
        return text

    def _summary(self) -> Text:
        s, opts = self.strings, self.app.opts
        apps = [s("app_" + name) for name in selected_apps(opts)]
        pairs = [(s("label_source"), s("source_" + opts.source))]
        prepared = self.app.prepared
        if prepared is not None:
            pairs += [
                (s("label_repo"), prepared.repository),
                (s("label_ref"), prepared.ref),
                (s("label_commit"), prepared.commit[:8]),
                (s("label_workspace"), str(prepared.path)),
                (s("label_dirty"), s("review_dirty") if prepared.dirty
                 else s("review_clean")),
            ]
        pairs += [
            (s("label_core"), f"{s('core_shell')} · {s('label_required')}"),
            (s("method"), method_label(s, self.app.system.method)),
            (s("label_apps"), ", ".join(apps) if apps else s("review_apps_none")),
            (s("opt_lockscreen"), s("on") if opts.lockscreen else s("off")),
            (s("opt_spatial"), s("on") if opts.spatial else s("off")),
            (s("opt_start"), s("on") if opts.start else s("off")),
        ]
        text = Text(s("review_summary"), style="bold")
        text.append("\n\n")
        text.append_text(self._pairs(pairs))
        return text

    def _plan_steps(self):
        """The plan that preparation will produce, not the legacy-update one.

        Before the source exists, resolve its identity so the argv already
        points inside the workspace that ``preparation.finish()`` creates.
        """
        prepared = self.app.prepared or self._source
        return build_plan(self.app.system.family, self.app.opts, self.app.paths,
                          prepared, backend=self.app.backend,
                          deps_missing=bool(self.app.system.missing_packages))

    def _steps(self) -> Text:
        s = self.strings
        quiet = self.app.secondary_style
        text = Text(s("review_steps"), style="bold")
        if self.app.prepared is None and not self._resolved:
            text.append("\n" + s("review_resolving"), style=quiet)
            return text
        steps = self._plan_steps()
        if not steps:
            text.append("\n")
            text.append(s("review_no_steps"), style="yellow")
            return text
        text.append(f"  ({s('step_count') % len(steps)})\n", style=quiet)
        for index, step in enumerate(steps, 1):
            text.append(f"{index}. {step.title}\n", style="bold")
            if step.argv and self.details:
                text.append(f"    $ {' '.join(step.argv)}\n", style=quiet)
            elif step.argv:
                rest = max(0, len(step.argv) - 1)
                text.append(f"    {s('review_cmd')}: {step.argv[0]} +{rest}\n",
                            style=quiet)
            elif step.note:
                text.append(f"    {s(step.note)}\n", style="yellow")
        text.append(s("review_details_on" if self.details else "review_details"),
                    style=quiet)
        return text

    def _side(self) -> Text:
        s = self.strings
        text = Text(s("review_side"), style="bold")
        warnings = []
        blocked = unsupported(self.app.system.family, self.app.opts,
                              self.app.backend)
        if blocked:
            warnings.append((s("review_unsupported") % ", ".join(blocked), "red"))
        if self.app.system.blocked:
            warnings.append((s("review_blocked"), "red"))
        warnings.append((s("review_side_takeover"), "yellow"))
        if self.app.opts.start:
            warnings.append((s("review_side_session"), "yellow"))
        quiet = self.app.secondary_style
        warnings.append((s("review_side_userpath"), quiet))
        warnings.append((s("review_side_log"), quiet))
        text.append("\n\n")
        for line, style in warnings:
            text.append("! " if style != quiet else "· ", style=style)
            text.append(line + "\n", style=style)
        return text

    def context_commands(self) -> list[Command]:
        s, failed = self.strings, bool(self.app.prepare_error)
        return [
            Command("log", s("cmd_log"), self.action_log_open, shortcut="ctrl+l",
                    enabled=failed, reason="" if failed else s("cmd_no_log")),
            Command("details", s("cmd_details"), self.action_review_details,
                    shortcut="ctrl+e", enabled=not failed,
                    reason="" if not failed else s("cmd_plan_unavailable")),
        ]

    def action_review_scroll(self, step: int) -> None:
        self.query_one("#review", VerticalScroll).scroll_relative(y=step, animate=False)

    def action_review_top(self) -> None:
        self.query_one("#review", VerticalScroll).scroll_home(animate=False)

    def action_review_bottom(self) -> None:
        self.query_one("#review", VerticalScroll).scroll_end(animate=False)

    def action_review_details(self) -> None:
        self.details = not self.details
        self.query_one("#steps", Static).update(self._steps())

    def action_review_continue(self) -> None:
        """Enter never installs: the plan page only opens the confirmation page."""
        from .confirm import ConfirmScreen

        self.app.push_screen(ConfirmScreen(self.strings, len(self._plan_steps())))

    def action_wizard_next(self) -> None:
        """Tab pages forward, exactly like Enter on this page."""
        self.action_review_continue()

    def action_review_retry(self) -> None:
        """Same as Enter on a failed page: preparation is what failed."""
        self.app.start_install()

    def action_log_open(self) -> None:
        """The log of the attempt that failed, in the existing viewer."""
        from .logs import LogViewerScreen

        self.app.push_screen(LogViewerScreen(self.strings,
                                             self.app.prepare_log_path))

    def action_wizard_back(self) -> None:
        self.app.pop_screen()
