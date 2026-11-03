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

    @property
    def log_dir(self) -> Path:
        return self.state_root / "logs"

    @property
    def installer_runtime(self) -> Path:
        data = self.data_home or _xdg(os.environ, "XDG_DATA_HOME", ".local/share")
        return data / "nextkde-installer"

    @classmethod
    def resolve(cls, source_root=None, env=None, installer_root=None) -> "Paths":
        env = os.environ if env is None else env
        source = source_root or env.get("KOS_ROOT") or Path.home() / "NextKde"
        return cls(
            installer_root=Path(installer_root or INSTALLER_ROOT).resolve(),
            source_root=Path(source).expanduser().resolve(),
            build_root=_xdg(env, "XDG_CACHE_HOME", ".cache") / "nextkde" / "build",
            state_root=_xdg(env, "XDG_STATE_HOME", ".local/state") / "nextkde-installer",
            data_home=_xdg(env, "XDG_DATA_HOME", ".local/share"),
        )
