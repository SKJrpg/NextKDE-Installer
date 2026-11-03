"""Prepare a product source: one commit, one workspace (design §6).

Managed workspaces are independent clones under ``<data_home>/nextkde/sources/
<repository-id>/<commit>/``, so a prepared commit is never rewritten in place.
Local sources are used where they are and never written to.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from ..paths import Paths
from . import git, manifest
from .models import PreparedSource
from .resolver import CANONICAL_REPO, repository_id, resolve


def prepare(mode: str, repository: str = CANONICAL_REPO, checkout=None,
            tag: str | None = None, paths: Paths | None = None,
            env: dict[str, str] | None = None) -> PreparedSource:
    """Resolve, fetch and verify the source for ``mode``; return its identity."""
    env = os.environ if env is None else env
    paths = paths or Paths.resolve(env=env)
    repository, ref = resolve(mode, repository, checkout, tag)
    if mode == "local":
        return _local(Path(repository))
    return _managed(mode, repository, ref, paths)


def _managed(mode: str, repository: str, ref: str, paths: Paths) -> PreparedSource:
    # The ref is resolved before anything is cloned: the commit is the identity,
    # not the branch that happened to point at it.
    commit = git.ls_remote(repository, ref)
    workspace = Path(paths.sources_root) / repository_id(repository) / commit
    if workspace.is_dir():
        recorded = _recorded(workspace)
        if git.head(workspace) == commit and recorded.get("repository", repository) == repository:
            return _prepared(mode, repository, ref, commit, workspace)  # reused, no fetch
        raise ValueError(f"Managed workspace {workspace} does not hold {commit} of "
                         f"{repository}; remove it and prepare again")

    temporary = workspace.with_name(workspace.name + ".tmp")
    # A leftover .tmp is this module's own interrupted clone of this commit.
    if temporary.exists():
        shutil.rmtree(temporary, ignore_errors=True)
    try:
        git.clone(repository, ref, temporary)
        if git.head(temporary) != commit:
            git.checkout_detach(temporary, commit)  # the ref moved after ls-remote
        if git.head(temporary) != commit:
            raise ValueError(f"Cloned {repository} at {git.head(temporary) or 'no commit'}, "
                             f"expected {commit}")
        prepared = _prepared(mode, repository, ref, commit, temporary)
        manifest.write(temporary, prepared)
        os.replace(temporary, workspace)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return _prepared(mode, repository, ref, commit, workspace)


def _prepared(mode: str, repository: str, ref: str, commit: str,
              workspace: Path) -> PreparedSource:
    return PreparedSource(mode=mode, repository=repository, ref=ref, commit=commit,
                          path=workspace, dirty=git.is_dirty(workspace, manifest.NAME),
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
