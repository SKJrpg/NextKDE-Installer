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


DOC_SECTIONS = {
    "arch": "Arch Linux",
    "debian": "Debian 13",
    "ubuntu": "Ubuntu 26.04",
    "fedora": "Fedora 44",
    "opensuse": "openSUSE Tumbleweed",
}

_COMMANDS = {"sudo", "pacman", "apt", "apt-get", "dnf", "zypper", "install", "-S", "-y",
             "--needed", "addrepo", "refresh"}


def doc_packages(root: Path, family: str) -> list[str]:
    """The package list from docs/GettingStarted.md for this family.

    The guide is the user-facing contract; the list is read from it so the
    wizard cannot disagree with what the docs tell people to install.
    """
    markers = [DOC_SECTIONS[family]] if family in DOC_SECTIONS else []
    if family == "ubuntu":
        markers.append("Debian 13")
    if not markers:
        return []
    try:
        text = (Path(root) / "docs" / "GettingStarted.md").read_text(encoding="utf-8")
    except OSError:
        return []
    lines = text.splitlines()
    start = next((index for index, line in enumerate(lines)
                  if line.startswith("### ") and any(m in line for m in markers)), None)
    if start is None:
        return []
    end = next((index for index in range(start + 1, len(lines))
                if lines[index].startswith("### ")), len(lines))
    blocks, current, inside = [], [], False
    for line in lines[start:end]:
        if line.startswith("```"):
            if inside:
                blocks.append(current)
                current, inside = [], False
            else:
                inside = True
            continue
        if inside:
            current.append(line)
    for block in blocks:
        joined = " ".join(part.rstrip("\\").strip() for part in block)
        if not any(cmd in joined for cmd in
                   ("pacman -S", "apt install", "dnf install", "zypper install")):
            continue
        tokens = joined.split()
        for index, token in enumerate(tokens):
            if token in ("install", "-S"):
                tokens = tokens[index + 1:]
                break
        names, seen = [], set()
        for token in tokens:
            if token in _COMMANDS or token.startswith("-") or "/" in token:
                continue
            if token not in seen:
                seen.add(token)
                names.append(token)
        return names
    return []


def installed_packages(root: Path, family: str) -> set[str]:
    if family in ("arch",):
        _rc, output = _run(["pacman", "-Qq"], root, timeout=30)
    elif family in ("debian", "ubuntu"):
        _rc, output = _run(["dpkg-query", "-W", "-f=${Package}\n"], root, timeout=30)
    elif family == "fedora":
        _rc, output = _run(["rpm", "-qa", "--qf", "%{NAME}\n"], root, timeout=30)
    else:
        return set()
    return {line.strip() for line in output.splitlines() if line.strip()}


def deps_from_docs(root: Path, family: str) -> "Deps":
    names = doc_packages(root, family)
    if not names:
        return Deps(family="", packages=[])
    have = installed_packages(root, family)
    return Deps(family=family, packages=[(name, name in have) for name in names])


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
