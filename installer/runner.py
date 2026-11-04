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
# git redraws its progress line with CR instead of printing new ones.
GIT_PROGRESS = re.compile(r"(?:Receiving objects|Resolving deltas):\s+(\d+)%")
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
        for _key, _ in self._sel.select(timeout):
            # os.read returns what is available; TextIOWrapper.read(n) would
            # block until n characters arrive and freeze the UI.
            chunk = os.read(self._fd, 4096)
            if not chunk:
                # EOF: the buffered lines are still returned, one per call.
                self._sel.unregister(self._fd)
                break
            self._buffer += self._decoder.decode(chunk)
        # git ends every progress redraw with CR, so either break ends a line;
        # waiting for "\n" would swallow minutes of a clone.
        breaks = [index for index in (self._buffer.find("\n"),
                                      self._buffer.find("\r")) if index >= 0]
        if not breaks:
            return None
        index = min(breaks)
        line, rest = self._buffer[:index], self._buffer[index + 1:]
        # A CRLF is one break, not a CR line followed by an empty one.
        if self._buffer[index] == "\r" and rest.startswith("\n"):
            rest = rest[1:]
        self._buffer = rest
        return self._record(line)

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
        self._read_rest()
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
    def _read_rest(self) -> None:
        """Take what the pipe still holds: a quick exit must not hide its last line."""
        if self._fd < 0:
            return
        os.set_blocking(self._fd, False)
        try:
            while True:
                chunk = os.read(self._fd, 4096)
                if not chunk:
                    break
                self._buffer += self._decoder.decode(chunk)
        except (BlockingIOError, OSError):
            pass
        finally:
            os.set_blocking(self._fd, True)

    def _drain(self) -> None:
        """Record what is left once the child is gone, one line per real break."""
        rest, self._buffer = self._buffer, ""
        for line in re.split(r"\r\n|\r|\n", rest):
            if line.strip():
                self._record(line)

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
        # git clone --progress reports the same way, as a percentage.
        clone = GIT_PROGRESS.search(text)
        if clone:
            self.progress = min(1.0, int(clone.group(1)) / 100)
        return text
