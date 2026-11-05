"""Resolved directories: the installer, the product checkout, build and state.

One root used to stand in for all of them; they are separate (docs/design.md
§4) and XDG-based. The product checkout is an input, never inferred from
``__file__``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# This checkout: installer/paths.py -> installer/ -> repository root.
INSTALLER_ROOT = Path(__file__).resolve().parents[1]


def _xdg(env: dict[str, str], key: str, default: str) -> Path:
    value = (env.get(key) or "").strip()
    return Path(value).expanduser() if value else Path.home() / default


@dataclass(frozen=True)
class Paths:
    installer_root: Path   # this checkout
    source_root: Path      # the NextKDE checkout to install
    build_root: Path       # ~/.cache/nextkde/build; not passed to the backend yet
    state_root: Path       # ~/.local/state/nextkde-installer
    data_home: Path | None = None   # kept so installer_runtime matches resolve(env)
    # --root or $KOS_ROOT named the checkout: it is the first detection candidate.
    source_root_explicit: bool = False

    @property
    def log_dir(self) -> Path:
        return self.state_root / "logs"

    @property
    def installer_runtime(self) -> Path:
        return self._data_home / "nextkde-installer"

    @property
    def sources_root(self) -> Path:
        """Managed product workspaces, one directory per repository and commit."""
        return self._data_home / "nextkde" / "sources"

    @property
    def _data_home(self) -> Path:
        return self.data_home or _xdg(os.environ, "XDG_DATA_HOME", ".local/share")

    @classmethod
    def resolve(cls, source_root=None, env=None, installer_root=None) -> "Paths":
        env = os.environ if env is None else env
        given = source_root or env.get("KOS_ROOT")
        source = given or Path.home() / "NextKde"
        return cls(
            installer_root=Path(installer_root or INSTALLER_ROOT).resolve(),
            source_root=Path(source).expanduser().resolve(),
            source_root_explicit=bool(given),
            build_root=_xdg(env, "XDG_CACHE_HOME", ".cache") / "nextkde" / "build",
            state_root=_xdg(env, "XDG_STATE_HOME", ".local/state") / "nextkde-installer",
            data_home=_xdg(env, "XDG_DATA_HOME", ".local/share"),
        )
