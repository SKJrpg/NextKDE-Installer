"""Read the ledger, snapshots, logs and doctor output for the manage screen.

Everything here shells out to the tools that own the data; the UI never
reimplements what kosctl or kos-state already know.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .plan import Step, session_env

STATE_SCRIPT = "tools/kos-state.py"


def state_command(root: Path, *args: str) -> list[str]:
    return ["python3", str(Path(root) / STATE_SCRIPT), *args]


def _run(argv: list[str], root: Path, timeout: float = 30) -> tuple[int, str]:
    try:
        result = subprocess.run(argv, cwd=str(root), capture_output=True, text=True,
                                timeout=timeout, check=False, env={**os.environ,
                                                                  **session_env()})
    except (OSError, subprocess.SubprocessError) as error:
        return 127, str(error)
    return result.returncode, result.stdout + result.stderr


KNOWN_UNITS = ("core", "apps", "lockscreen", "shortcuts")


@dataclass
class Unit:
    name: str
    version: str
    mode: str
    paths: int
    installed_at: str

    @property
    def installed(self) -> bool:
        return bool(self.installed_at)


def units(root: Path) -> list[Unit]:
    rc, output = _run(state_command(root, "list", "--json"), root)
    if rc != 0:
        return []
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return []
    entries = data.get("units", {})
    found = []
    for name in KNOWN_UNITS:
        entry = entries.get(name, {})
        found.append(Unit(name=name, version=entry.get("version", "-"),
                          mode=entry.get("mode", "-"),
                          paths=len(entry.get("paths", [])),
                          installed_at=entry.get("installedAt", "")))
    for name, entry in sorted(entries.items()):
        if name not in KNOWN_UNITS:
            found.append(Unit(name=name, version=entry.get("version", "?"),
                              mode=entry.get("mode", "files"),
                              paths=len(entry.get("paths", [])),
                              installed_at=entry.get("installedAt", "")))
    return found


@dataclass
class Deps:
    family: str
    packages: list[tuple[str, bool]]


def deps(root: Path) -> Deps:
    """Every build package for this family, with its installed state."""
    rc, output = _run(["bash", str(Path(root) / "tools" / "kosctl"), "deps"], root, timeout=60)
    family, packages = "", []
    for line in output.splitlines():
        if line.startswith("family="):
            family = line.split("=", 1)[1].strip()
        elif "=" in line:
            name, state = line.rsplit("=", 1)
            packages.append((name.strip(), state.strip() == "ok"))
    return Deps(family=family, packages=packages)


@dataclass
class Snapshot:
    id: str
    created_at: str
    note: str
    trees: str


def snapshots(root: Path) -> list[Snapshot]:
    rc, output = _run(state_command(root, "snapshots", "--json"), root)
    if rc != 0:
        return []
    try:
        rows = json.loads(output)
    except json.JSONDecodeError:
        return []
    return [Snapshot(id=row.get("id", ""), created_at=row.get("createdAt", ""),
                     note=row.get("note", ""), trees=",".join(row.get("trees", [])))
            for row in rows]


def logs(log_dir: Path) -> list[Path]:
    if not log_dir.is_dir():
        return []
    return sorted(log_dir.glob("*.log"), reverse=True)


def doctor(root: Path) -> tuple[int, str]:
    return _run(["bash", str(Path(root) / "tools" / "kosctl"), "doctor"], root, timeout=60)


def action_step(root: Path, title: str, *argv: str) -> Step:
    return Step(key="manage", title=title, argv=list(argv))


def kosctl(root: Path, *args: str) -> Step:
    return action_step(root, " ".join(("kosctl",) + args), str(Path(root) / "tools" / "kosctl"),
                       *args)
