"""Execute one step, stream its output, and keep a log.

The wrapped commands are ordinary child processes; this module owns the parts
the UI needs: line-by-line reading, banner detection, cancellation, and a log
file that survives a crash.
"""

from __future__ import annotations

import codecs
import os
import re
import selectors
import signal
import subprocess
import time
from pathlib import Path

from .plan import Step

BANNER = re.compile(r"^===+\s*(.*?)\s*===+$")
_LEVELS = (
    ("err", "ERROR"),
    ("✘", "ERROR"),
    ("warn", "WARN"),
    ("⚠", "WARN"),
)


def classify(line: str) -> str:
    lowered = line.lower()
    for needle, level in _LEVELS:
        if needle in lowered:
            return level
    if "ok" in lowered:
        return "OK"
    return "INFO"


class StepRunner:
    def __init__(self, step: Step, root: Path, log_file) -> None:
        self.step = step
        self.root = Path(root)
        self.log = log_file
        self.phase = ""
        self.progress: float | None = None
        self.proc: subprocess.Popen[bytes] | None = None
        self._sel = selectors.DefaultSelector()
        self._buffer = ""
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._fd = -1
        self.started = time.monotonic()
        self.finished = False
        self.cancelled = False
        self._kill_deadline = 0.0

    # -- lifecycle -----------------------------------------------------
    def start(self) -> None:
        if not self.step.argv:
            self.finished = True
            return
        env = dict(os.environ)
        env.update(self.step.env)
        env.setdefault("PYTHONUNBUFFERED", "1")
        self.proc = subprocess.Popen(
            self.step.argv,
            cwd=str(self.root),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            start_new_session=True,
        )
        assert self.proc.stdout is not None
        self._fd = self.proc.stdout.fileno()
        self._sel.register(self._fd, selectors.EVENT_READ)

    def cancel(self) -> None:
        """Ask the whole child group to stop; SIGKILL follows if it ignores us."""
        if self.proc is None or self.proc.poll() is not None:
            return
        self.cancelled = True
        self._kill_deadline = time.monotonic() + 5.0
        self._signal(signal.SIGTERM)

    def _signal(self, sig: int) -> None:
        assert self.proc is not None
        try:
            os.killpg(os.getpgid(self.proc.pid), sig)
        except (ProcessLookupError, PermissionError):
            try:
                self.proc.send_signal(sig)
            except ProcessLookupError:
                pass

    def readline(self, timeout: float = 0.1) -> str | None:
        """Return one complete line, or None when nothing is ready."""
        if self.proc is None or self.finished:
            return None
        events = self._sel.select(timeout)
        for _key, _ in events:
            # os.read returns what is available; TextIOWrapper.read(n) would
            # block until n characters arrive and freeze the UI.
            chunk = os.read(self._fd, 4096)
            if not chunk:
                self._sel.unregister(self._fd)
                self._drain()
                return None
            self._buffer += self._decoder.decode(chunk)
        if "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            return self._record(line)
        return None

    def poll(self) -> int | None:
        if self.proc is None:
            return 0
        rc = self.proc.poll()
        if rc is None and self.cancelled and self._kill_deadline \
                and time.monotonic() > self._kill_deadline:
            self._kill_deadline = 0.0
            self._signal(signal.SIGKILL)
        return rc

    def close(self) -> int:
        if self.proc is None:
            self.finished = True
            return 0
        rc = self.proc.wait()
        self._drain()
        try:
            self._sel.unregister(self._fd)
        except (KeyError, ValueError):
            pass
        self._sel.close()
        if self.proc.stdout is not None:
            self.proc.stdout.close()
        self.finished = True
        return rc

    # -- internals -----------------------------------------------------
    def _drain(self) -> None:
        rest, self._buffer = self._buffer, ""
        if rest.strip():
            self._record(rest)

    def _record(self, line: str) -> str:
        text = line.rstrip("\r")
        self.log.write(text + "\n")
        self.log.flush()
        match = BANNER.match(text.strip())
        if match:
            self.phase = match.group(1)
        # ninja and make print "[64/206]" while they work: real progress, not a guess.
        counter = re.search(r"\[\s*(\d+)\s*/\s*(\d+)\s*\]", text)
        if counter and int(counter.group(2)) > 0:
            self.progress = min(1.0, int(counter.group(1)) / int(counter.group(2)))
        return text
