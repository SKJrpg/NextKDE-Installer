"""Prepare the product source before any install step runs (design §10.5-10.7).

The installer owns the source: it resolves the chosen channel to one commit,
fetches that commit into its own workspace and only then builds the plan. Each
front end gets the same thing: a :class:`Preparation` that is either already
done (local checkout, or a reused workspace) or carries the one clone step to
stream, and that ends with ``finish()``.

Nothing here draws anything, so the Textual and plain front ends share it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .paths import Paths
from .plan import Step
from .source import manager
from .source.models import PreparedSource
from .source.resolver import CANONICAL_REPO

# What the CLI and the UI call a source channel versus what the manager calls it.
MODES = {"main": "development", "development": "development",
         "stable": "stable", "local": "local"}


@dataclass
class Preparation:
    """What a caller must do to obtain the source, and how it ends."""

    paths: Paths
    prepared: PreparedSource | None = None
    steps: list[Step] = field(default_factory=list)
    stage: manager.Stage | None = None
    temporary: Path | None = None

    def finish(self) -> PreparedSource:
        """Verify the fetched workspace and record it; idempotent, raises on failure.

        A caller that streamed ``steps`` has nothing left to do here; one that
        did not gets the clone run in this process.
        """
        if self.prepared is None:
            if self.stage is None or self.temporary is None:
                raise ValueError("No source was resolved to prepare")
            if not self.temporary.is_dir():
                manager.fetch(self.stage, self.temporary)
            self.prepared = manager.finalize(self.stage, self.temporary, self.paths)
        return self.prepared


def _checkout(opts, paths: Paths) -> Path:
    """The checkout a local install uses: the chosen one, else --root."""
    return Path(getattr(opts, "local_path", None) or paths.source_root)


def _mode(mode: str, opts) -> str:
    mode = mode or getattr(opts, "source", "")
    if mode not in MODES:
        raise ValueError(f"Unknown source mode: {mode!r}")
    return MODES[mode]


def begin(mode: str, opts, paths: Paths,
          repository: str = CANONICAL_REPO) -> Preparation:
    """Resolve the source and work out what the caller still has to do."""
    mode = _mode(mode, opts)
    if mode == "local":
        # The user's checkout is the source: no clone, no writes.
        return Preparation(paths, prepared=manager.prepare(
            "local", checkout=_checkout(opts, paths), paths=paths))
    stage = manager.stage_for(mode, repository)
    prepared = manager.existing(stage, paths)
    if prepared is not None:
        return Preparation(paths, prepared=prepared)
    temporary = manager.temporary_path(stage, paths)
    # git clone creates the leaf directory; the workspace's parent must exist,
    # and an interrupted clone of this commit must not block the next one.
    temporary.parent.mkdir(parents=True, exist_ok=True)
    manager.discard(temporary)
    steps = [Step("source", f"git clone {stage.ref}",
                  manager.clone_argv(stage.repository, stage.ref, temporary))]
    return Preparation(paths, steps=steps, stage=stage, temporary=temporary)


def identity(mode: str, opts, paths: Paths,
             repository: str = CANONICAL_REPO) -> PreparedSource:
    """The source an install would use, resolved without fetching it."""
    mode = _mode(mode, opts)
    if mode == "local":
        return manager.prepare("local", checkout=_checkout(opts, paths), paths=paths)
    stage = manager.stage_for(mode, repository)
    return manager.existing(stage, paths) or PreparedSource(
        mode=mode, repository=stage.repository, ref=stage.ref, commit=stage.commit,
        path=manager.workspace_path(stage, paths), dirty=False, managed=True)
