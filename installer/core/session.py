"""Run a plan of steps in order and report what happens, UI-agnostically.

The session owns the process lifecycle: every runner is closed (reaped) even
when the caller raises, and a cancel request reaches the running child group
before the next step starts.
"""

from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path
from typing import Callable

from ..plan import Step
from ..runner import StepRunner, classify
from .events import Event

# How long one read waits; short enough that a cancel lands promptly.
_POLL = 0.1
_TAIL = 8


class InstallSession:
    def __init__(self, paths, steps, log_path, root=None, extra_env=None) -> None:
        self.paths = paths
        self.steps = list(steps)
        self.log_path = Path(log_path)
        self.root = Path(root) if root is not None else Path(paths.source_root)
        # Merged into every step (the askpass PATH and SUDO_ASKPASS): a copy per
        # step, so the caller's list is never mutated.
        self.extra_env = dict(extra_env or {})
        self.result = ""            # ok | failed | cancelled, once run() returns
        self.exit_code = 0
        self.failed_index: int | None = None
        self.tail: list[tuple[str, str]] = []   # last classified lines

    def run(self, emit: Callable[[Event], None],
            cancel: threading.Event) -> int:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        total = len(self.steps)
        work = [index for index, step in enumerate(self.steps, 1) if step.argv]
        with self.log_path.open("w", encoding="utf-8") as log:
            for index, step in enumerate(self.steps, 1):
                if cancel.is_set():
                    return self._finish(emit, "cancelled", 130, index, step)
                emit(Event("stage", text=step.title, key=step.key,
                           index=index, total=total))
                if not step.argv:
                    continue
                if self.extra_env:
                    step = replace(step, env={**step.env, **self.extra_env})
                runner = StepRunner(step, self.root, log)
                try:
                    runner.start()
                except OSError as error:
                    self.tail = (self.tail + [("ERROR", str(error))])[-_TAIL:]
                    emit(Event("log", text=str(error), level="ERROR", key=step.key,
                               index=index, total=total))
                    return self._finish(emit, "failed", 1, index, step, str(error))
                done = sum(1 for other in work if other < index)
                last: float | None = None
                try:
                    while True:
                        line = runner.readline(_POLL)
                        while line is not None:
                            self._log(emit, step, index, total, line)
                            line = runner.readline(0)
                        if cancel.is_set() and not runner.cancelled:
                            runner.cancel()
                        if runner.progress is not None and runner.progress != last:
                            last = runner.progress
                            emit(Event("stage", text=step.title, key=step.key,
                                       index=index, total=total,
                                       fraction=(done + last) / len(work)))
                        if runner.poll() is not None:
                            # Gone, but its last lines may still be in the pipe:
                            # the fatal one is what the user must see.
                            line = runner.readline(0)
                            while line is not None:
                                self._log(emit, step, index, total, line)
                                line = runner.readline(0)
                            break
                finally:
                    code = runner.close()
                if runner.cancelled or cancel.is_set():
                    return self._finish(emit, "cancelled", 130, index, step)
                if code != 0:
                    error = next((text for level, text in reversed(self.tail)
                                  if level == "ERROR"), "")
                    return self._finish(emit, "failed", code if code > 0 else 1,
                                        index, step, error)
        return self._finish(emit, "ok", 0, total, self.steps[-1] if self.steps else None)

    def _log(self, emit, step: Step, index: int, total: int, text: str) -> None:
        """One streamed line, classified and added to the tail."""
        level = classify(text)
        self.tail = (self.tail + [(level, text)])[-_TAIL:]
        emit(Event("log", text=text, level=level, key=step.key,
                   index=index, total=total))

    def _finish(self, emit, result: str, code: int, index: int,
                step: Step | None, error: str = "") -> int:
        self.result = result
        self.exit_code = code
        if result == "failed":
            self.failed_index = index
        emit(Event("done" if result == "ok" else result,
                   text=error if result == "failed" else "",
                   key=step.key if step is not None else "", index=index,
                   total=len(self.steps),
                   level="ERROR" if result == "failed" else ""))
        return code
