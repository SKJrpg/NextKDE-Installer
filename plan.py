"""Turn a detected system plus the user's options into the command plan.

The shell never invents an install: every step is a command that already exists
in this repository. Anything the shell cannot express is left out.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Options:
    source: str = "stable"
    apps: bool = False
    lockscreen: bool = False
    start: bool = False
    install_all: bool = False
    proxy: bool = True


@dataclass
class Step:
    key: str
    title: str
    argv: list[str]
    env: dict[str, str] = field(default_factory=dict)
    note: str = ""


def git_state(root: Path) -> tuple[str, bool]:
    """Return (branch, dirty). Missing git or repo yields ('', True)."""
    try:
        branch = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "", True
    return branch.stdout.strip(), bool(dirty.stdout.strip())


def proxy_url(env: dict[str, str] | None = None) -> str:
    """The proxy the installer would forward, or "" when none is configured."""
    env = os.environ if env is None else env
    for key in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY",
                "all_proxy", "ALL_PROXY"):
        value = (env.get(key) or "").strip()
        if value:
            return value
    return ""


def session_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """The user session bus, when the caller has none (SSH, --yes, a service).

    kbuildsycoca6 and `systemctl --user` need it; without it a non-interactive
    install fails halfway through deployment even though the desktop is running.
    """
    env = os.environ if env is None else env
    runtime = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    if Path(runtime, "bus").exists():
        return {
            "XDG_RUNTIME_DIR": runtime,
            "DBUS_SESSION_BUS_ADDRESS": env.get("DBUS_SESSION_BUS_ADDRESS")
            or f"unix:path={runtime}/bus",
        }
    return {}


def _proxy_env(enabled: bool) -> dict[str, str]:
    if not enabled:
        return {}
    env = {}
    for key in ("http_proxy", "https_proxy", "all_proxy", "no_proxy",
                "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        value = os.environ.get(key)
        if value:
            env[key] = value
    return env


def build_plan(family: str | None, opts: Options, root: Path) -> list[Step]:
    root = Path(root)
    env = {**session_env(), **_proxy_env(opts.proxy)}

    if family == "debian":
        argv = ["bash", str(root / "tools/install-debian13.sh"), "--dir", str(root)]
        if opts.source != "stable":
            argv += ["--version", opts.source]
        if opts.install_all:
            argv += ["--all"]
        if opts.start:
            argv += ["--start"]
        if not opts.proxy:
            argv += ["--no-proxy"]
        return [Step("debian", "tools/install-debian13.sh", argv, env)]

    if family == "nixos":
        steps = [Step("nix", "kosctl nix install", [str(root / "tools/kosctl"), "nix", "install"], env)]
        if opts.start:
            steps.append(Step("start", "kosctl start", [str(root / "tools/kosctl"), "start"], env))
        return steps

    if family in ("ubuntu", "arch", "fedora"):
        kosctl = str(root / "tools/kosctl")
        branch, dirty = git_state(root)
        steps: list[Step] = []
        if branch == "main" and not dirty:
            steps.append(Step("source", f"kosctl update {opts.source}",
                              [kosctl, "update", opts.source], env))
        else:
            steps.append(Step("source", "kosctl update (skipped)", [],
                              env, note="skipped_source"))
        steps.append(Step("core", "kosctl install", [kosctl, "install"], env))
        if opts.apps:
            steps.append(Step("apps", "kosctl install apps", [kosctl, "install", "apps"], env))
        if opts.lockscreen:
            steps.append(Step("lockscreen", "kosctl install lockscreen",
                              [kosctl, "install", "lockscreen"], env))
        if opts.start:
            steps.append(Step("start", "kosctl start", [kosctl, "start"], env))
        return steps

    # opensuse, unknown: nothing is executed.
    return []
