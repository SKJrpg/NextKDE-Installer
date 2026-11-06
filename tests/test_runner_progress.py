"""The runner turns CR-terminated progress into lines, and keeps real counters."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from installer.plan import Step
from installer.runner import StepRunner


class RunnerProgressTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)

    def run_script(self, script: str, input: str = "") -> tuple[list[str], StepRunner]:
        log = (self.root / "log").open("w", encoding="utf-8")
        self.addCleanup(log.close)
        runner = StepRunner(Step("step", "step", ["sh", "-c", script], input=input),
                            self.root, log)
        runner.start()
        lines: list[str] = []
        try:
            while True:
                line = runner.readline(0.1)
                while line is not None:
                    lines.append(line)
                    line = runner.readline(0)
                if runner.poll() is not None:
                    break
        finally:
            runner.close()
        return lines, runner

    def test_a_carriage_return_ends_a_line(self) -> None:
        # git redraws its progress line this way; waiting for "\n" loses it.
        lines, _ = self.run_script("printf 'one\\rtwo\\nthree\\n'")
        self.assertEqual(lines, ["one", "two", "three"])

    def test_crlf_is_one_break_not_two(self) -> None:
        lines, _ = self.run_script("printf 'a\\r\\nb\\r\\n'")
        self.assertEqual(lines, ["a", "b"])

    def test_git_progress_lines_reach_the_reader(self) -> None:
        lines, runner = self.run_script(
            "printf 'Receiving objects:  42%% (42/100), 4 MiB\\r"
            "Receiving objects: 100%% (100/100), 9 MiB\\r\\n'")
        self.assertIn("Receiving objects:  42% (42/100), 4 MiB", lines)
        self.assertEqual(runner.progress, 1.0)

    def test_receiving_objects_is_a_percentage(self) -> None:
        _, runner = self.run_script("printf 'Receiving objects:  37%% (37/100)\\r'")
        self.assertAlmostEqual(runner.progress, 0.37)

    def test_resolving_deltas_is_a_percentage_too(self) -> None:
        _, runner = self.run_script("printf 'Resolving deltas:   7%% (7/100)\\r'")
        self.assertAlmostEqual(runner.progress, 0.07)

    def test_step_input_answers_the_child_prompt(self) -> None:
        lines, _ = self.run_script("read answer; echo got:$answer", input="y\n")
        self.assertEqual(lines, ["got:y"])

    def test_a_step_without_a_counter_reports_no_progress(self) -> None:
        # Never invented: plain output leaves the field empty.
        _, runner = self.run_script("printf 'plain line\\n'")
        self.assertIsNone(runner.progress)


if __name__ == "__main__":
    unittest.main()
