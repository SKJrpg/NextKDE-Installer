#!/usr/bin/env python3
"""Fetch the pinned Python wheels from PyPI and unpack them into vendor/.

Stdlib only: no pip, no venv, no shell. ``vendor/`` is a build artefact
(see ``.gitignore``); ``install.sh`` puts it on PYTHONPATH when it exists.

    python3 tools/vendor.py           # download, unpack, write SHA256SUMS
    python3 tools/vendor.py --check   # verify the unpacked tree, offline
    python3 tools/vendor.py --clean   # remove vendor/
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor"
PINS = ROOT / "vendor-requirements.txt"
JSON_URL = "https://pypi.org/pypi/{name}/{version}/json"


def pins(path: Path = PINS) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        name, _, version = line.partition("==")
        if not version:
            raise SystemExit(f"{path.name}: expected name==version, got {line!r}")
        entries.append((name.strip(), version.strip()))
    return entries


def normalized(name: str) -> str:
    """Wheel dist-info naming: PyYAML -> pyyaml, markdown-it-py -> markdown_it_py."""
    return re.sub(r"[-_.]+", "_", name).lower()


def wheel_for(name: str, version: str) -> tuple[str, str]:
    """The filename and URL of the pure-python wheel for one pin."""
    url = JSON_URL.format(name=name, version=version)
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            data = json.load(response)
    except urllib.error.HTTPError as error:
        raise SystemExit(f"{name}=={version}: PyPI replied {error.code} (version gone?)")
    except (urllib.error.URLError, OSError) as error:
        raise SystemExit(
            f"network unavailable ({error}). Nothing was changed; "
            "run this once on a connected machine."
        )
    wheels = [f for f in data.get("urls", ())
              if f.get("packagetype") == "bdist_wheel"
              and f.get("filename", "").endswith(".whl")]
    pure = [f for f in wheels if f["filename"].endswith("-none-any.whl")]
    if not (pure or wheels):
        raise SystemExit(f"{name}=={version}: PyPI lists no wheel")
    chosen = (pure or wheels)[0]
    return chosen["filename"], chosen["url"]


def download(url: str, target: Path) -> str:
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(url, timeout=60) as response, target.open("wb") as handle:
            for chunk in iter(lambda: response.read(1 << 16), b""):
                digest.update(chunk)
                handle.write(chunk)
    except (urllib.error.URLError, OSError) as error:
        raise SystemExit(f"download failed ({error}): {url}")
    return digest.hexdigest()


def unpack(wheel: Path, target: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        for member in archive.namelist():
            parts = Path(member).parts
            if member.startswith("/") or ".." in parts:
                raise SystemExit(f"{wheel.name}: unsafe path {member!r}")
        archive.extractall(target)


def install() -> int:
    entries = pins()
    staging = Path(tempfile.mkdtemp(prefix=".vendor-", dir=ROOT))
    sums: list[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix="wheels-", dir=staging) as scratch:
            for name, version in entries:
                filename, url = wheel_for(name, version)
                wheel = Path(scratch) / filename
                digest = download(url, wheel)
                unpack(wheel, staging)
                sums.append(f"{digest}  {filename}  {url}")
                print(f"  {name}=={version}  {filename}")
        (staging / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
        if VENDOR.exists():
            shutil.rmtree(VENDOR)
        staging.rename(VENDOR)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    print(f"vendor/: {len(entries)} packages unpacked")
    return 0


def check() -> int:
    entries = pins()
    problems: list[str] = []
    if not VENDOR.is_dir():
        print("vendor/ is missing; run python3 tools/vendor.py", file=sys.stderr)
        return 1
    for name, version in entries:
        metadata = VENDOR / f"{normalized(name)}-{version}.dist-info" / "METADATA"
        if not metadata.is_file():
            problems.append(f"{name}=={version}: {metadata.parent.name}/METADATA missing")
            continue
        lines = metadata.read_text(encoding="utf-8", errors="replace").splitlines()
        found = next((line.split(":", 1)[1].strip() for line in lines
                      if line.startswith("Version:")), "")
        if found != version:
            problems.append(f"{name}=={version}: unpacked tree says {found or 'nothing'}")
    sums = VENDOR / "SHA256SUMS"
    if not sums.is_file():
        problems.append("SHA256SUMS missing")
    else:
        for line in sums.read_text(encoding="utf-8").splitlines():
            if line and len(line.split()) != 3:
                problems.append(f"SHA256SUMS: malformed line {line!r}")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print(f"vendor/: {len(entries)} packages verified")
    return 0


def clean() -> int:
    if not VENDOR.exists():
        print("vendor/ is already absent")
        return 0
    shutil.rmtree(VENDOR)
    print("vendor/ removed")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true",
                       help="verify the unpacked packages offline")
    group.add_argument("--clean", action="store_true", help="remove vendor/")
    args = parser.parse_args(argv)
    if args.check:
        return check()
    if args.clean:
        return clean()
    return install()


if __name__ == "__main__":
    sys.exit(main())
