"""Plain-text renderer: the same plan, no terminal drawing.

Used for --check, for --yes/--config, and whenever stdout is not a TTY.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from ..detect import System, method_label
from ..plan import Step
from ..runner import StepRunner, classify


def _status_color(status: str) -> str:
    return {"PASS": "\033[32m", "WARN": "\033[33m", "FAIL": "\033[31m"}.get(status, "")


def print_report(system: System, steps: list[Step], strings) -> None:
    reset = "\033[0m" if sys.stdout.isatty() else ""
    bold = "\033[1m" if sys.stdout.isatty() else ""
    print(f"{bold}{strings('title')}{reset} — {system.label} ({system.arch})")
    print(f"{strings('method')}: {system.family or 'unknown'} → {method_label(strings, system.method)}")
    print()
    for probe in system.probes:
        color = _status_color(probe.status) if sys.stdout.isatty() else ""
        print(f"  {color}{probe.status:<4}{reset} {strings(probe.key)}: {probe.detail}")
        if probe.remedy and probe.status != "PASS":
            print(f"       {probe.remedy}")
    print()
    if not steps:
        print(f"  {strings('review_none')}")
        return
    print(f"{bold}{strings('review_warn')}{reset}")
    for index, step in enumerate(steps, 1):
        if not step.argv:
            print(f"  {index}. {step.title}  ({strings(step.note) if step.note else '-'})")
            continue
        print(f"  {index}. {step.title}")
        print(f"     $ {' '.join(step.argv)}")


def execute(system: System, steps: list[Step], root: Path, log_path: Path, strings) -> int:
    plain = not sys.stdout.isatty()
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
            while True:
                line = runner.readline(0.2)
                if line is not None:
                    if plain:
                        print(line)
                    else:
                        level = classify(line)
                        color = {"ERROR": "\033[31m", "WARN": "\033[33m", "OK": "\033[32m"}.get(level, "")
                        print(f"  {color}{line}\033[0m" if color else f"  {line}")
                if runner.poll() is not None:
                    break
                time.sleep(0.02)
            rc = runner.close()
            if runner.cancelled:
                print(f"  {strings('cancelled')}")
                return 130
            if rc != 0:
                print(f"\n{strings('failure_title')}: {step.title} (exit {rc})")
                print(f"{strings('log_hint')}{log_path}")
                return 1
    print(f"\n{strings('success_title')}")
    print(f"{strings('log_hint')}{log_path}")
    return 0
