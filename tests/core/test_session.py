"""Stage T2: the session runs real steps, reports them, and always reaps."""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from installer.core.events import Event
from installer.core.session import InstallSession
from installer.paths import Paths
from installer.plan import Step
from installer.runner import StepRunner


def sh(title: str, script: str) -> Step:
    return Step(title, title, ["sh", "-c", script])


class SessionTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, tmp)
        self.paths = Paths.resolve(source_root=tmp)
        self.log = tmp / "logs" / "install.log"
        self.closed: list[str] = []

    def run_session(self, steps, cancel=None, emit=None) -> tuple[int, list[Event], InstallSession]:
        session = InstallSession(self.paths, steps, self.log)
        events: list[Event] = []

        def sink(event: Event) -> None:
            events.append(event)
            if emit is not None:
                emit(event)

        original = StepRunner.close

        def spy(runner):
            self.closed.append(runner.step.key)
            return original(runner)

        with mock.patch.object(StepRunner, "close", spy):
            code = session.run(sink, cancel or threading.Event())
        return code, events, session

    def test_events_follow_the_plan(self) -> None:
        code, events, session = self.run_session([
            sh("one", "echo one"), sh("two", "echo two")])

        self.assertEqual(code, 0)
        self.assertEqual(session.result, "ok")
        stages = [event for event in events if event.kind == "stage"]
        self.assertEqual([stage.index for stage in stages], [1, 2])
        self.assertEqual({stage.total for stage in stages}, {2})
        logs = [event for event in events if event.kind == "log"]
        self.assertEqual([log.text for log in logs], ["one", "two"])
        self.assertEqual(logs[0].level, "INFO")
        self.assertEqual(events[0].kind, "stage")
        self.assertEqual(events[-1].kind, "done")
        self.assertLess([e.kind for e in events].index("stage"),
                        [e.kind for e in events].index("log"))
        self.assertEqual(self.closed, ["one", "two"])
        self.assertEqual(self.log.read_text(encoding="utf-8").splitlines(),
                         ["one", "two"])

    def test_failed_step_stops_the_plan(self) -> None:
        code, events, session = self.run_session([
            sh("bad", 'echo "err boom" >&2; exit 3'),
            sh("never", "echo never")])

        self.assertEqual(code, 3)
        self.assertEqual(session.result, "failed")
        self.assertEqual(session.failed_index, 1)
        self.assertEqual(events[-1].kind, "failed")
        self.assertEqual(events[-1].index, 1)
        self.assertEqual(events[-1].level, "ERROR")
        self.assertIn("err boom", events[-1].text)
        self.assertNotIn("never", [event.text for event in events])
        self.assertEqual(self.closed, ["bad"])

    def test_cancel_mid_step_reaps_the_child(self) -> None:
        cancel = threading.Event()

        def press(event: Event) -> None:
            if event.kind == "log" and "alive" in event.text:
                cancel.set()

        started = time.monotonic()
        code, events, session = self.run_session(
            [sh("slow", "echo alive; sleep 30"), sh("never", "echo never")],
            cancel=cancel, emit=press)
        elapsed = time.monotonic() - started

        self.assertEqual(code, 130)
        self.assertEqual(session.result, "cancelled")
        self.assertEqual(events[-1].kind, "cancelled")
        # close() is the reap: it ran for the killed step and no other.
        self.assertEqual(self.closed, ["slow"])
        self.assertLess(elapsed, 10)
