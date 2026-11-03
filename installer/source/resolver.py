"""Turn a source channel into the repository and ref to fetch (design §6.2)."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

CANONICAL_REPO = "https://github.com/NextKde/NextKde.git"

_STABLE_TAG = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+")
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


def latest_tag(repository: str) -> str:
    """The latest GitHub release tag, if it is a plain ``vX.Y.Z`` stable tag."""
    match = _GITHUB_REMOTE.fullmatch((repository or "").strip())
    if not match:
        raise ValueError("Automatic stable selection needs a github.com repository; "
                         "pass an explicit vX.Y.Z tag")
    owner_repo = "/".join(match.groups())
    request = urllib.request.Request(
        f"https://api.github.com/repos/{owner_repo}/releases/latest",
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": "NextKDE-installer"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            release = json.load(response)
    except urllib.error.HTTPError as error:
        raise ValueError(f"No stable release is available for {owner_repo} "
                         f"(HTTP {error.code}); pass an explicit vX.Y.Z tag") from error
    except (OSError, ValueError) as error:  # URLError, timeouts, broken JSON
        raise ValueError(f"Cannot read the latest release of {owner_repo}: {error}") from error
    tag = str(release.get("tag_name", ""))
    if release.get("draft") or release.get("prerelease") or not _STABLE_TAG.fullmatch(tag):
        raise ValueError(f"The latest release of {owner_repo} is not a stable vX.Y.Z tag; "
                         "pass an explicit tag")
    return tag


def resolve(mode: str, repository: str = CANONICAL_REPO, checkout=None,
            tag: str | None = None) -> tuple[str, str]:
    """The (repository, ref) a mode works from; nothing is fetched here."""
    if mode == "stable":
        return repository, tag or latest_tag(repository)
    if mode == "development":
        # A custom branch or commit is a later extension of this channel.
        return repository, tag or "main"
    if mode == "local":
        if not checkout:
            raise ValueError("Local source mode requires a checkout directory")
        return str(Path(checkout).expanduser().resolve()), tag or ""
    raise ValueError(f"Unknown source mode: {mode!r}")
