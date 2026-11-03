"""Turn a detected system plus the user's options into the command plan.

The shell never invents an install: every step is a command that already exists
in this repository. Anything the shell cannot express is left out.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .paths import Paths


ALL_APPS = ("calendar", "todo", "weather", "calculator")


@dataclass
class Options:
    source: str = "stable"
    apps: bool = False
    lockscreen: bool = False
    start: bool = False
    proxy: bool = True
    spatial: bool = False  # ONNX + OpenCV depth engine, a wallpaper feature
    app_set: set[str] = field(default_factory=set)


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


CANONICAL_REPO = "https://github.com/NextKde/NextKde.git"


def latest_release(root: Path, max_age: float = 6 * 3600) -> str:
    """Latest stable tag, cached: the version screen must not block on GitHub."""
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "kos" /         "installer" / "latest-release.json"
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        if time.time() - float(data.get("at", 0)) < max_age:
            return str(data.get("tag", ""))
    except (OSError, ValueError):
        pass
    script = str(Path(root) / "tools" / "source-release.py")
    tag = ""
    # A fork's origin usually has no releases; ask the upstream repository then.
    for extra in ([], ["--repository", CANONICAL_REPO]):
        try:
            result = subprocess.run(["python3", script, "latest", *extra], cwd=str(root),
                                    capture_output=True, text=True, timeout=15, check=False)
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0 and result.stdout.strip():
            tag = result.stdout.strip().splitlines()[-1]
            break
    if tag:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"tag": tag, "at": time.time()}), encoding="utf-8")
        except OSError:
            pass
    return tag


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


def parse_app_deps(text: str) -> list[str]:
    """The packages tools/check-apps-dependencies.py lists as missing."""
    found = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            found.append(stripped[2:].strip())
    return found


def apps_missing(root: Path) -> list[str]:
    """Run the apps dependency check; empty when everything is present."""
    script = Path(root) / "tools" / "check-apps-dependencies.py"
    if not script.is_file():
        return []
    try:
        result = subprocess.run(["python3", str(script)], capture_output=True,
                                text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_app_deps(result.stdout + result.stderr)


def origin_url(root: Path) -> str:
    """The checkout's origin, or "" when this is not a Git repository."""
    try:
        result = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"],
                                capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def selected_apps(opts: Options) -> list[str]:
    """The apps to install, in canonical order; empty when none is wanted."""
    chosen = opts.app_set or set(ALL_APPS)
    return [name for name in ALL_APPS if name in chosen] if opts.apps else []


def unsupported(family: str | None, opts: Options) -> list[str]:
    """Selections the detected backend cannot honour, by option name."""
    if family == "nixos":
        # `kosctl nix install` builds the flake and nothing else: there is no
        # app, lockscreen or spatial switch in that path.
        return [name for name in ("apps", "lockscreen", "spatial")
                if getattr(opts, name)]
    return []


def _component_steps(opts: Options, root: Path, env: dict[str, str]) -> list[Step]:
    """App and lockscreen steps shared by every backend that runs kosctl."""
    kosctl = str(root / "tools" / "kosctl")
    steps: list[Step] = []
    chosen = selected_apps(opts)
    if chosen:
        argv = [kosctl, "install", "apps"]
        if len(chosen) != len(ALL_APPS):
            argv += ["--only", ",".join(chosen)]
        steps.append(Step("apps", "kosctl install apps", argv, env))
    if opts.lockscreen:
        steps.append(Step("lockscreen", "kosctl install lockscreen",
                          [kosctl, "install", "lockscreen"], env))
    return steps


def build_plan(family: str | None, opts: Options, paths: Paths) -> list[Step]:
    root = Path(paths.source_root)
    env = {**session_env(), **_proxy_env(opts.proxy),
           "KOS_BUILD_SPATIAL": "ON" if opts.spatial else "OFF"}
    # paths.build_root is not passed as KOS_BUILD_DIR/KOS_APPS_BUILD_DIR: the
    # product backend's path behaviour must be verified first (design §4.5).
    kosctl = str(root / "tools" / "kosctl")

    if family == "debian":
        # The wrapper owns the Debian preflight and the core install; apps,
        # lockscreen and start stay separate steps so activation runs last.
        argv = ["bash", str(root / "tools" / "install-debian13.sh"), "--dir", str(root),
                "--spatial", "on" if opts.spatial else "off"]
        repo = origin_url(root)
        if repo:
            # The same repository on both sides: the wrapper's selector must not
            # meet an origin mismatch, and a fork must stay a fork.
            argv += ["--repo", repo]
        if opts.source == "local":
            argv += ["--local"]
        elif opts.source != "stable":
            argv += ["--version", opts.source]
        if not opts.proxy:
            argv += ["--no-proxy"]
        steps = [Step("debian", "tools/install-debian13.sh", argv, env)]
        steps += _component_steps(opts, root, env)
        if opts.start:
            steps.append(Step("start", "kosctl start", [kosctl, "start"], env))
        return steps

    if family == "nixos":
        steps = [Step("nix", "kosctl nix install", [kosctl, "nix", "install"], env)]
        if opts.start:
            steps.append(Step("start", "kosctl start", [kosctl, "start"], env))
        return steps

    if family in ("ubuntu", "arch", "fedora"):
        steps: list[Step] = []
        branch, dirty = git_state(root)
        if opts.source == "local":
            steps.append(Step("source", "kosctl update (skipped)", [],
                              env, note="skipped_local"))
        elif branch == "main" and not dirty:
            steps.append(Step("source", f"kosctl update {opts.source}",
                              [kosctl, "update", opts.source], env))
        else:
            steps.append(Step("source", "kosctl update (skipped)", [],
                              env, note="skipped_source"))
        steps.append(Step("core", "kosctl install", [kosctl, "install"], env))
        steps += _component_steps(opts, root, env)
        if opts.start:
            steps.append(Step("start", "kosctl start", [kosctl, "start"], env))
        return steps

    # opensuse, unknown: nothing is executed.
    return []
