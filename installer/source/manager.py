"""Prepare a product source: one commit, one workspace (design §6).

Managed workspaces are independent clones under ``<data_home>/nextkde/sources/
<repository-id>/<commit>/``, so a prepared commit is never rewritten in place.
Local sources are used where they are and never written to.

The work is split into the stages a caller needs separately: resolving the ref
is fast and read-only, the clone can be streamed through a runner, and only
finalizing verifies and moves the workspace into place.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..paths import Paths
from . import git, manifest
from .models import PreparedSource
from .resolver import CANONICAL_REPO, repository_id, resolve


@dataclass(frozen=True)
class Stage:
    """A resolved source, before anything is fetched."""

    mode: str
    repository: str
    ref: str
    commit: str
    repository_id: str


def resolve_commit(mode: str, repository: str = CANONICAL_REPO,
                   tag: str | None = None) -> tuple[str, str, str, str]:
    """The (repository, ref, commit, repository id) of a mode; no clone."""
    repository, ref = resolve(mode, repository, None, tag)
    return repository, ref, git.ls_remote(repository, ref), repository_id(repository)


def stage_for(mode: str, repository: str = CANONICAL_REPO,
              tag: str | None = None) -> Stage:
    """The resolved source a mode names, as one value."""
    return Stage(mode, *resolve_commit(mode, repository, tag))


def workspace_path(stage: Stage, paths: Paths) -> Path:
    """Where a commit's workspace lives: <sources_root>/<repo-id>/<commit>."""
    return Path(paths.sources_root) / stage.repository_id / stage.commit


def temporary_path(stage: Stage, paths: Paths) -> Path:
    """The clone target beside the workspace; the ``.tmp`` name is ours alone."""
    workspace = workspace_path(stage, paths)
    return workspace.with_name(workspace.name + ".tmp")


def clone_argv(repository: str, ref: str, temporary: Path) -> list[str]:
    """The exact ``git clone`` argv ``prepare()`` runs, streamable by a caller."""
    return git.clone_argv(repository, ref, Path(temporary))


def existing(stage: Stage, paths: Paths) -> PreparedSource | None:
    """The workspace for this commit when it is already prepared and verified."""
    workspace = workspace_path(stage, paths)
    if not workspace.is_dir():
        return None
    recorded = _recorded(workspace)
    if git.head(workspace) == stage.commit \
            and recorded.get("repository", stage.repository) == stage.repository:
        return _prepared(stage, workspace)  # reused, no fetch
    raise ValueError(f"Managed workspace {workspace} does not hold {stage.commit} of "
                     f"{stage.repository}; remove it and prepare again")


def fetch(stage: Stage, temporary: Path) -> Path:
    """Clone the stage into its temporary directory, in this process."""
    temporary = Path(temporary)
    discard(temporary)
    git.clone(stage.repository, stage.ref, temporary)
    return temporary


def discard(temporary: Path) -> None:
    """Remove our own interrupted clone target: the ``.tmp`` name is ours."""
    shutil.rmtree(temporary, ignore_errors=True)


def finalize(stage: Stage, temporary: Path, paths: Paths) -> PreparedSource:
    """Verify the clone, record its identity and move it into place."""
    workspace = workspace_path(stage, paths)
    temporary = Path(temporary)
    try:
        already = existing(stage, paths)  # another installer may have won the race
        if already is not None:
            discard(temporary)
            return already
        if git.head(temporary) != stage.commit:
            git.checkout_detach(temporary, stage.commit)  # the ref moved after ls-remote
        if git.head(temporary) != stage.commit:
            raise ValueError(f"Cloned {stage.repository} at {git.head(temporary) or 'no commit'}, "
                             f"expected {stage.commit}")
        manifest.write(temporary, _prepared(stage, temporary))
        os.replace(temporary, workspace)
    except BaseException:
        discard(temporary)
        raise
    return _prepared(stage, workspace)


def prepare(mode: str, repository: str = CANONICAL_REPO, checkout=None,
            tag: str | None = None, paths: Paths | None = None,
            env: dict[str, str] | None = None) -> PreparedSource:
    """Resolve, fetch and verify the source for ``mode``; return its identity."""
    env = os.environ if env is None else env
    paths = paths or Paths.resolve(env=env)
    if mode == "local":
        return _local(Path(resolve("local", repository, checkout, tag)[0]))
    stage = stage_for(mode, repository, tag)
    prepared = existing(stage, paths)
    if prepared is not None:
        return prepared
    temporary = temporary_path(stage, paths)
    fetch(stage, temporary)
    return finalize(stage, temporary, paths)


def _prepared(stage: Stage, workspace: Path) -> PreparedSource:
    return PreparedSource(mode=stage.mode, repository=stage.repository, ref=stage.ref,
                          commit=stage.commit, path=workspace,
                          dirty=git.is_dirty(workspace, manifest.NAME),
                          managed=True, manifest_path=workspace / manifest.NAME)


def _recorded(workspace: Path) -> dict:
    try:
        return manifest.read(workspace)
    except (OSError, ValueError):
        return {}


def _local(root: Path) -> PreparedSource:
    """The user's own checkout: read its identity, change nothing."""
    try:
        result = git.run(root, "rev-parse", "--show-toplevel")
    except OSError as error:
        raise ValueError(f"Local source needs a git work tree: {error}") from error
    top = result.stdout.strip()
    if result.returncode != 0 or not top or Path(top).resolve() != root.resolve():
        raise ValueError(f"Local source {root} is not the top of a Git work tree")
    if not (root / "tools" / "kosctl").is_file():
        raise ValueError(f"Local source {root} has no tools/kosctl; "
                         "is it a NextKDE checkout?")
    commit = git.head(root)
    if not commit:
        raise ValueError(f"Local source {root} has no commit yet")
    return PreparedSource(
        mode="local",
        repository=git.origin(root) or str(root),
        ref=git.branch(root) or commit,
        commit=commit,
        path=root,
        dirty=git.is_dirty(root),
        managed=False,
        manifest_path=None,
    )
