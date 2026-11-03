"""Capabilities evidenced by the prepared checkout itself.

The product has no contract file today, so this is the compatibility bridge
(design §7.5): every capability is read from a file the checkout really has, and
nothing is assumed from a version number. The price of that honesty is a probe
that is narrower than the product; the contract path replaces it once the
product ships one.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from ..plan import ALL_APPS
from .models import (ACTIVATION_START, INSTALL_APPS, INSTALL_CORE, INSTALL_DEBIAN,
                     INSTALL_DEBIAN_LOCAL, INSTALL_LOCKSCREEN, INSTALLER_API,
                     MANAGEMENT_SNAPSHOTS, MANAGEMENT_UNINSTALL, PLATFORM_NIX,
                     SOURCE_UPDATE, SYSTEM_DOCTOR, BackendInfo, product_version)


def root_of(prepared) -> Path:
    """A PreparedSource, or a plain path, without caring which was passed."""
    return Path(getattr(prepared, "path", prepared))


def runnable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def usage_text(script: Path, back: int = 4) -> str:
    """Every usage block the script prints, or "" when it prints none.

    All blocks, not just the first: ``kosctl`` prints a short per-verb usage
    before its main one, and truncating at the first would drop most verbs.
    Reading the file is deliberate: executing ``kosctl`` creates its build
    directory first, and a probe must not write into the product checkout.
    """
    try:
        lines = script.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if "Usage:" not in line:
            continue
        # A heredoc usage continues to EOF; a one-line echo usage does not.
        if any("<<" in before for before in lines[max(0, index - back - 1):index]):
            block = [line]
            while index < len(lines) and lines[index].strip() != "EOF":
                block.append(lines[index])
                index += 1
            blocks.append("\n".join(block))
        else:
            blocks.append(line)
    return "\n".join(blocks)


def detect(prepared) -> BackendInfo:
    """Read the checkout only: no network, no execution, no guesses."""
    root = root_of(prepared)
    found: set[str] = set()

    kosctl = root / "tools" / "kosctl"
    if runnable(kosctl):
        usage = usage_text(kosctl)
        if re.search(r"\bdoctor\b", usage):
            found.add(SYSTEM_DOCTOR)
        if re.search(r"(?<!un)\binstall\b", usage):
            found.add(INSTALL_CORE)
            if re.search(r"(?<!un)\binstall\b[^\n]*\bapps\b", usage):
                found.add(INSTALL_APPS)
            if re.search(r"(?<!un)\binstall\b[^\n]*\blockscreen\b", usage):
                found.add(INSTALL_LOCKSCREEN)
        if re.search(r"\buninstall\b", usage):
            found.add(MANAGEMENT_UNINSTALL)
        if re.search(r"\bstart\b", usage):
            found.add(ACTIVATION_START)
        if re.search(r"\bupdate\b", usage):
            found.add(SOURCE_UPDATE)
        if re.search(r"\bnix\b", usage):
            found.add(PLATFORM_NIX)

    if (root / "tools" / "kos-state.py").is_file():
        found.add(MANAGEMENT_SNAPSHOTS)

    wrapper = root / "tools" / "install-debian13.sh"
    if wrapper.is_file():
        found.add(INSTALL_DEBIAN)
        if "--local" in usage_text(wrapper):
            found.add(INSTALL_DEBIAN_LOCAL)

    components = tuple(name for name in ALL_APPS if (root / "apps" / name).is_dir())
    return BackendInfo(product="nextkde", version=product_version(root),
                       installer_api=INSTALLER_API, capabilities=frozenset(found),
                       components=components, source="probe")
