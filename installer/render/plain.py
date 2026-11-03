"""Plain-text renderer: the same plan, no terminal drawing.

Used for --check, for --yes/--config, and whenever stdout is not a TTY.  It
keeps the wizard's information hierarchy (checks, then plan, then warnings) with
plain headings, indented bodies and explicit PASS/WARN/FAIL labels; colour is
only a bonus on a TTY, and NO_COLOR or a pipe turns it off.
"""

from __future__ import annotations

import os
import sys
import time
from collections import deque
from pathlib import Path

from ..detect import System, method_label
from ..plan import Step
from ..runner import StepRunner, classify

_LEVEL_CODE = {"ERROR": "\033[31m", "WARN": "\033[33m", "OK": "\033[32m"}
_STATUS_CODE = {"PASS": "\033[32m", "WARN": "\033[33m", "FAIL": "\033[31m"}


def _colour(stream=None) -> bool:
    stream = sys.stdout if stream is None else stream
    return bool(getattr(stream, "isatty", lambda: False)()) and not os.environ.get("NO_COLOR")


def _paint(text: str, code: str, enabled: bool) -> str:
    return f"{code}{text}\033[0m" if enabled and code else text


def print_report(system: System, steps: list[Step], strings) -> None:
    colour = _colour()
    bold = "\033[1m" if colour else ""
    reset = "\033[0m" if colour else ""
    header = f"{strings('title')} — {system.label} ({system.arch})"
    print(f"{bold}{header}{reset}")
    print(f"  {strings('method')}: {system.family or 'unknown'} → "
          f"{method_label(strings, system.method)}")
    print(f"  {strings('label_path')}: {strings('review_target')}")
    print()

    print(f"{bold}{strings('system_head')}{reset}")
    for probe in system.probes:
        status = _paint(f"{probe.status:<4}", _STATUS_CODE.get(probe.status, ""), colour)
        print(f"  {status} {strings(probe.key)}: {probe.detail}")
        if probe.remedy and probe.status != "PASS":
            print(f"       {strings('check_remedy')}: {probe.remedy}")
    passed = sum(1 for probe in system.probes if probe.status == "PASS")
    warned = sum(1 for probe in system.probes if probe.status == "WARN")
    failed = sum(1 for probe in system.probes if probe.status == "FAIL")
    print(f"  {strings('system_counts') % (passed, warned, failed)}")
    print()

    if not steps:
        print(f"  {strings('review_none')}")
        return

    print(f"{bold}{strings('review_steps')}{reset}  ({strings('step_count') % len(steps)})")
    for index, step in enumerate(steps, 1):
        print(f"  {index}. {step.title}")
        if step.argv:
            print(f"     $ {' '.join(step.argv)}")
        elif step.note:
            print(f"     {strings(step.note)}")
    print()

    print(f"{bold}{strings('review_side')}{reset}")
    for text in (strings("review_side_takeover"), strings("review_side_userpath")):
        print(f"  - {text}")
    if system.blocked:
        print(f"  - {_paint(strings('review_blocked'), '\033[31m', colour)}")


def execute(system: System, steps: list[Step], root: Path, log_path: Path, strings) -> int:
    colour = _colour()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"# {system.label} {system.arch}\n")
        for index, step in enumerate(steps, 1):
            print(f"\n=== [{index}/{len(steps)}] {step.title} ===")
            if not step.argv:
                print(f"  {strings(step.note) if step.note else 'skipped'}")
                continue
            print(f"  $ {' '.join(step.argv)}")
            runner = StepRunner(step, root, log)
            runner.start()
            tail: deque[tuple[str, str]] = deque(maxlen=8)
            try:
                while True:
                    line = runner.readline(0.2)
                    if line is not None:
                        level = classify(line)
                        tail.append((level, line))
                        if colour:
                            print(_paint(f"  {line}", _LEVEL_CODE.get(level, ""), colour))
                        else:
                            print(f"  {line}")
                    if runner.poll() is not None:
                        break
                    time.sleep(0.02)
            except KeyboardInterrupt:
                # The child runs in its own session, so Ctrl-C never reaches it.
                print(f"\n  {strings('cancel_confirm')}", file=sys.stderr)
                runner.cancel()
                while runner.poll() is None:
                    time.sleep(0.05)
            rc = runner.close()
            if runner.cancelled:
                print(f"  {strings('cancelled')}")
                return 130
            if rc != 0:
                print(f"\n{strings('failure_title')}: {step.title} "
                      f"({strings('result_exit_code')}: {rc})")
                errors = [text for level, text in tail if level == "ERROR"]
                summary = errors[-1] if errors else strings("result_none_logged")
                print(f"  {strings('result_error')}: {summary}")
                if tail:
                    print(f"  {strings('result_tail')}:")
                    for _level, text in list(tail)[-4:]:
                        print(f"    {text}")
                print(f"  {strings('log_path')}{log_path}")
                return 1
    print(f"\n{strings('success_title')}")
    print(f"{strings('next_steps')}")
    print(f"{strings('log_path')}{log_path}")
    return 0
