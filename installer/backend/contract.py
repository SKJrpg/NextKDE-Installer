"""Read the backend contract the product declares.

Two sources, in order (design §7.2-7.3): the static
``packaging/installer-contract.json`` a release can be inspected for, then
``kosctl installer-info --json`` for a checkout that can answer for itself.
Neither is present in today's product, so ``None`` means "probe it".
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .models import (INSTALLER_API, BackendIncompatible, BackendInfo,
                     product_version)
from .probe import root_of, runnable, usage_text

CONTRACT_PATH = Path("packaging") / "installer-contract.json"


def _range(api) -> tuple[int, int] | None:
    if isinstance(api, int):
        return api, api
    if (isinstance(api, dict) and isinstance(api.get("minimum"), int)
            and isinstance(api.get("maximum"), int)):
        return api["minimum"], api["maximum"]
    return None


def _info(data: dict, root: Path, source: str) -> BackendInfo | None:
    """One record from either shape; None when a required field is malformed."""
    product = data.get("product")
    if isinstance(product, dict):
        product = product.get("id") or product.get("name")
    product = str(product or "nextkde")
    version = str(data.get("product_version") or product_version(root))

    schema = data.get("schema_version", 1 if "installer_api" in data else None)
    if schema is not None and schema != 1:
        raise BackendIncompatible(
            f"{product} {version or 'unknown'} uses contract schema {schema}; "
            f"this installer reads schema 1")

    api = _range(data.get("installer_api"))
    if api is None:
        return None
    minimum, maximum = api
    if not minimum <= INSTALLER_API <= maximum:
        raise BackendIncompatible(
            f"{product} {version or 'unknown'} requires installer API "
            f"{minimum}-{maximum}; this installer speaks {INSTALLER_API}")

    capabilities = data.get("capabilities")
    components = data.get("components") or []
    if not isinstance(capabilities, list) or not isinstance(components, list):
        return None
    return BackendInfo(
        product=product, version=version, installer_api=INSTALLER_API,
        capabilities=frozenset(str(name) for name in capabilities),
        components=tuple(str(name) for name in components), source=source)


def _runtime(root: Path) -> BackendInfo | None:
    """Ask the checkout, but only when its usage advertises the subcommand."""
    kosctl = root / "tools" / "kosctl"
    if not kosctl.is_file() or "installer-info" not in usage_text(kosctl):
        return None
    argv = ([str(kosctl)] if runnable(kosctl) else ["bash", str(kosctl)])
    argv += ["installer-info", "--json"]
    try:
        result = subprocess.run(argv, capture_output=True, text=True,
                                timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except ValueError:
        return None
    return _info(data, root, "contract") if isinstance(data, dict) else None


def read(prepared) -> BackendInfo | None:
    """The declared contract, or None when the checkout declares none.

    A malformed contract file is not a crash and not an incompatibility: the
    probe still describes what the checkout really contains.
    """
    root = root_of(prepared)
    path = root / CONTRACT_PATH
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict):
            info = _info(data, root, "contract")
            if info is not None:
                return info
    return _runtime(root)
