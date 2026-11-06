"""The source identity every later installer step works from (design §6.3)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PreparedSource:
    mode: str          # stable / development / local
    repository: str    # the remote the source came from
    ref: str           # tag, branch or local ref
    commit: str        # full commit SHA
    path: Path         # the work tree to build
    dirty: bool        # uncommitted or untracked changes
    managed: bool      # the installer owns this directory
    manifest_path: Path | None = None
    tag: str = ""      # release tag at the commit, when the ref has one
