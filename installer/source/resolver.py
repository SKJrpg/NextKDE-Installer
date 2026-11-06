"""Turn a source channel into the repository and ref to fetch (design §6.2)."""

from __future__ import annotations

import re
from pathlib import Path

from . import git

CANONICAL_REPO = "https://github.com/NextKde/NextKde.git"

_RELEASE_BRANCH = re.compile(r"release/([0-9]+)\.([0-9]+)")
_GITHUB_REMOTE = re.compile(
    r"(?:https?://|ssh://git@|git@)(?:www\.)?github\.com[/:]([\w.-]+)/([\w.-]+?)(?:\.git)?/?",
    re.IGNORECASE,
)


def repository_id(remote: str) -> str:
    """A stable, path-safe ``owner.repo`` for a remote (design §4.3).

    GitHub remotes give ``owner.repo``; a local or self-hosted remote keeps its
    path components, so two different repositories never share a workspace.
    """
    text = (remote or "").strip()
    match = _GITHUB_REMOTE.fullmatch(text)
    if match:
        parts = list(match.groups())
    else:
        path = re.sub(r"^[a-z][\w+.-]*://", "", text, flags=re.IGNORECASE)
        path = re.sub(r"^[^/]*@[^/:]+:", "", path)  # scp-like user@host:path
        path = path.rstrip("/")
        path = path[:-4] if path.endswith(".git") else path
        parts = [part for part in re.split(r"[/\\]", path) if part not in ("", ".", "..")]
    safe = [re.sub(r"[^\w.-]", "_", part) for part in parts]
    if not safe or not all(safe):
        raise ValueError(f"Cannot derive a repository id from {remote!r}")
    return ".".join(safe)


def latest_release_branch(repository: str) -> str:
    """The newest ``release/X.Y`` branch, e.g. ``release/0.1``.

    Only the latest release series is maintained, so the highest X.Y wins.
    Read with ``git ls-remote``: no GitHub API and no clone.
    """
    result = git.run(None, "ls-remote", "--heads", repository,
                     "refs/heads/release/*", timeout=60)
    if result.returncode != 0:
        lines = (result.stderr or result.stdout).strip().splitlines()
        raise ValueError(f"Cannot list release branches of {repository}: "
                         f"{lines[-1] if lines else result.returncode}")
    found = {}
    for line in result.stdout.splitlines():
        _, _, name = line.partition("\t")
        branch = name.strip().removeprefix("refs/heads/")
        match = _RELEASE_BRANCH.fullmatch(branch)
        if match:
            found[branch] = (int(match.group(1)), int(match.group(2)))
    if not found:
        raise ValueError(f"{repository} has no release/X.Y branch")
    return max(found, key=found.get)


def resolve(mode: str, repository: str = CANONICAL_REPO, checkout=None,
            tag: str | None = None) -> tuple[str, str]:
    """The (repository, ref) a mode works from; nothing is fetched here."""
    if mode == "stable":
        return repository, tag or latest_release_branch(repository)
    if mode == "development":
        # A custom branch or commit is a later extension of this channel.
        return repository, tag or "main"
    if mode == "local":
        if not checkout:
            raise ValueError("Local source mode requires a checkout directory")
        return str(Path(checkout).expanduser().resolve()), tag or ""
    raise ValueError(f"Unknown source mode: {mode!r}")
