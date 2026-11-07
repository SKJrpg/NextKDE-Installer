"""Distribution and environment detection.

Pure parsing lives in :func:`parse_os_release` and :func:`family_of` so tests can
feed fixtures; the probing functions are thin wrappers around the machine and are
only used by the UI.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

OS_RELEASE = Path("/etc/os-release")

# Exact ID wins; ID_LIKE is consulted second. The order matters: Ubuntu has
# ID_LIKE=debian but must be handled by the apt/kosctl path, not the Debian
# wrapper, which is written and tested for Debian 13 only.
FAMILY_IDS: dict[str, str] = {
    "nixos": "nixos",
    "ubuntu": "ubuntu",
    "linuxmint": "ubuntu",
    "pop": "ubuntu",
    "debian": "debian",
    "arch": "arch",
    "archarm": "arch",
    "manjaro": "arch",
    "endeavouros": "arch",
    "fedora": "fedora",
    "rhel": "fedora",
    "centos": "fedora",
    "nobara": "fedora",
    "opensuse-tumbleweed": "opensuse",
    "opensuse-leap": "opensuse",
    "opensuse": "opensuse",
    "suse": "opensuse",
    "sled": "opensuse",
    "sles": "opensuse",
}

METHODS: dict[str, str] = {
    "debian": "wrapper",
    "ubuntu": "kosctl",
    "arch": "kosctl",
    "fedora": "kosctl",
    "opensuse": "report",
    "nixos": "nixos",
}


@dataclass(frozen=True)
class OsInfo:
    id: str
    version: str
    like: tuple[str, ...]
    pretty: str

    @property
    def label(self) -> str:
        return self.pretty or f"{self.id} {self.version}".strip()


@dataclass
class Probe:
    key: str
    status: str  # PASS | WARN | FAIL
    detail: str
    remedy: str = ""


@dataclass
class System:
    os: OsInfo
    family: str | None
    method: str
    arch: str
    probes: list[Probe] = field(default_factory=list)
    missing_packages: list[str] = field(default_factory=list)
    blocked: bool = False

    @property
    def label(self) -> str:
        return self.os.label


def parse_os_release(text: str) -> OsInfo:
    data: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return OsInfo(
        id=data.get("ID", "").lower(),
        version=data.get("VERSION_ID", ""),
        like=tuple(v.lower() for v in data.get("ID_LIKE", "").split()),
        pretty=data.get("PRETTY_NAME", ""),
    )


def family_of(info: OsInfo, nixos_marker: bool = False) -> str | None:
    if nixos_marker or info.id == "nixos":
        return "nixos"
    if info.id in FAMILY_IDS:
        return FAMILY_IDS[info.id]
    for like in info.like:
        if like in FAMILY_IDS:
            return FAMILY_IDS[like]
    return None


def _run(argv: list[str], timeout: float = 5.0) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return 127, ""
    return proc.returncode, (proc.stdout or proc.stderr).strip()


_VERSION = re.compile(r"\d+(?:\.\d+)+")


def _version(text: str) -> str:
    """Just the first dotted number in a tool's banner, or ""."""
    match = _VERSION.search(text or "")
    return match.group(0) if match else ""


def _major_minor(text: str) -> tuple[int, int] | None:
    for chunk in text.split():
        stripped = chunk.strip("v")
        if not stripped or not stripped[0].isdigit():
            continue
        nums = stripped.split(".")
        try:
            major = int(nums[0])
        except ValueError:
            continue
        minor = 0
        if len(nums) > 1 and nums[1].isdigit():
            minor = int(nums[1])
        return major, minor
    return None


def parse_missing_packages(text: str) -> list[str]:
    """Pull the build packages kosctl doctor reports as missing."""
    found = []
    for line in text.splitlines():
        match = re.match(r"\s*miss\s+pkg:(\S+)", line)
        if match:
            found.append(match.group(1))
    return found


def latest_workspace(sources_root: Path | None) -> Path | None:
    """The most recently prepared product workspace, or None.

    Managed sources are keyed by commit, so the newest ``tools/kosctl`` is the
    source the installer prepared last. Used only to report package state
    before a new clone; the install itself always re-checks its own workspace.
    """
    if sources_root is None:
        return None
    try:
        found = [path for path in Path(sources_root).glob("*/*/tools/kosctl")
                 if path.is_file()]
        newest = max(found, key=lambda path: path.stat().st_mtime)
    except (OSError, ValueError):
        return None
    return newest.parents[1]


def deps_report(root: Path | None) -> tuple[bool, list[str]]:
    """(doctor ran, missing build packages) for a product checkout."""
    if root is None or not (Path(root) / "tools" / "kosctl").is_file():
        return False, []
    rc, output = _run(["bash", str(Path(root) / "tools" / "kosctl"), "doctor"], timeout=30)
    if not output and rc != 0:
        return False, []
    return True, parse_missing_packages(output)


def product_checkout(root: Path | None, fallback_root: Path | None) -> Path | None:
    """The checkout whose build packages matter: --root, else the newest workspace."""
    product = Path(root) if root is not None else None
    if product is None or not (product / "tools" / "kosctl").is_file():
        product = latest_workspace(fallback_root)
    if product is None or not (product / "tools" / "kosctl").is_file():
        return None
    return product


def missing_packages(root: Path | None) -> list[str]:
    """The build packages ``kosctl doctor`` reports missing, or []."""
    return deps_report(root)[1]


def _probe(key: str, ok: bool, detail: str, remedy: str = "", warn: bool = False) -> Probe:
    status = "PASS" if ok else ("WARN" if warn else "FAIL")
    return Probe(key=key, status=status, detail=detail, remedy="" if ok else remedy)


def detect(fixed_os_release: str | None = None, root: Path | None = None,
           fallback_root: Path | None = None,
           check_packages: bool = True) -> System:
    text = fixed_os_release
    if text is None:
        try:
            text = OS_RELEASE.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
    info = parse_os_release(text)
    family = family_of(info, nixos_marker=Path("/etc/NIXOS").exists())
    method = METHODS.get(family or "", "unknown")
    system = System(os=info, family=family, method=method, arch=platform.machine())

    system.probes.append(_probe("probe_os", bool(info.id), info.label or "unknown",
                                "Read /etc/os-release; this system is not identifiable."))
    system.probes.append(_probe("probe_arch", system.arch in ("x86_64", "aarch64"),
                                system.arch, "Only x86_64 and aarch64 are tested.", warn=True))

    manager = next((m for m in ("apt-get", "pacman", "dnf", "zypper") if shutil.which(m)), "")
    system.probes.append(_probe("probe_manager", bool(manager), manager or "not found",
                                "No supported package manager found."))

    # The stack checks first: Plasma on Wayland, KWin, Quickshell, Qt.
    session = os.environ.get("XDG_SESSION_TYPE", "")
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
    wayland = session == "wayland" or "wayland" in os.environ.get("WAYLAND_DISPLAY", "")
    if session:
        session_detail = f"{session} ({desktop})" if desktop else session
    elif wayland:
        session_detail = "wayland (WAYLAND_DISPLAY)"
    else:
        session_detail = desktop or "unknown"
    plasma_bin = shutil.which("plasmashell")
    rc, plasma_out = _run([plasma_bin, "--version"]) if plasma_bin else (127, "")
    plasma_ver = _major_minor(plasma_out) if rc == 0 else None
    plasma_ok = plasma_ver is not None and plasma_ver >= (6, 0)
    system.probes.append(_probe("probe_plasma", plasma_ok,
                                _version(plasma_out) or "not found",
                                "KDE Plasma 6 is required."))
    system.probes.append(_probe("probe_graphics", wayland,
                                "Wayland" if wayland else session_detail,
                                "KOS runs only in a Plasma 6 Wayland session."))

    rc, kwin_out = _run(["kwin_wayland", "--version"])
    ver = _major_minor(kwin_out) if rc == 0 else None
    kwin_ok = ver is not None and ver >= (6, 6)
    system.probes.append(_probe("probe_kwin", kwin_ok,
                                _version(kwin_out) or kwin_out or "kwin_wayland not found",
                                "KWin 6.6+ is required for the native plugins."))

    rc, qs_out = _run(["qs", "--version"]) if shutil.which("qs") else (127, "")
    if rc != 0:
        rc, qs_out = _run(["quickshell", "--version"]) if shutil.which("quickshell") else (127, "")
    qs_ok = rc == 0 and "0.3" in qs_out
    system.probes.append(_probe("probe_quickshell", qs_ok,
                                _version(qs_out) or qs_out or "not found",
                                "Quickshell 0.3.x is required; the install step can provide it.",
                                warn=True))

    qt_out, rc = "", 127
    for argv in (["qmake6", "-query", "QT_VERSION"],
                 ["qtpaths6", "--qt-version"],
                 ["pkg-config", "--modversion", "Qt6Core"]):
        if not shutil.which(argv[0]):
            continue
        rc, qt_out = _run(argv, timeout=3.0)
        if rc == 0:
            break
    qt_ver = _major_minor(qt_out) if rc == 0 else None
    qt_ok = qt_ver is not None and qt_ver >= (6, 6)
    system.probes.append(_probe("probe_qt", qt_ok,
                                _version(qt_out) or qt_out or "not found",
                                "Qt 6.6+ is required; install qt6-base.", warn=True))


    free_gb = 0.0
    try:
        free_gb = shutil.disk_usage(str(Path.home())).free / (1024 ** 3)
    except OSError:
        pass
    system.probes.append(_probe("probe_disk", free_gb >= 6.0, f"{free_gb:.1f} GiB free",
                                "At least 6 GiB is needed for the build tree."))

    product = product_checkout(root, fallback_root) if check_packages else None
    if product is not None:
        ran, missing = deps_report(product)
        system.missing_packages = missing
        if missing:
            system.probes.append(Probe(
                key="probe_packages", status="WARN",
                detail=", ".join(missing),
                remedy="The installer adds these before the build, after you confirm."))
        elif ran:
            system.probes.append(Probe(key="probe_packages", status="PASS",
                                       detail="build dependencies present"))

    system.blocked = any(p.status == "FAIL" for p in system.probes)
    return system


def method_label(strings, method: str) -> str:
    return strings(f"method_{method}")
