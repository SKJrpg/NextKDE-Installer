"""Small git helpers: argv only, never a shell (design §6.4)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

TIMEOUT = 600  # a clone of the product tree on a slow link


def run(root: Path | str | None, *args: str,
        timeout: float = TIMEOUT) -> subprocess.CompletedProcess:
    """Run one git command; ``root`` becomes ``-C`` (None runs it anywhere)."""
    command = ["git"] if root is None else ["git", "-C", str(root)]
    return subprocess.run(
        [*command, *args],
        capture_output=True, text=True, timeout=timeout, check=False,
        # A missing credential or host key must fail, not wait on a prompt.
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )


def _check(result: subprocess.CompletedProcess, action: str) -> subprocess.CompletedProcess:
    if result.returncode != 0:
        lines = (result.stderr or result.stdout).strip().splitlines()
        raise ValueError(f"git {action} failed: {lines[-1] if lines else result.returncode}")
    return result


def origin(root) -> str:
    """The origin URL, or "" when there is none."""
    result = run(root, "remote", "get-url", "origin")
    return result.stdout.strip() if result.returncode == 0 else ""


def head(root) -> str:
    """The full HEAD commit, or "" outside a repository."""
    result = run(root, "rev-parse", "--verify", "HEAD^{commit}")
    return result.stdout.strip() if result.returncode == 0 else ""


def branch(root) -> str:
    """The current branch, or "" on a detached HEAD."""
    result = run(root, "rev-parse", "--abbrev-ref", "HEAD")
    name = result.stdout.strip() if result.returncode == 0 else ""
    return "" if name == "HEAD" else name


def is_dirty(root, *exclude: str) -> bool:
    """Any modified, staged or untracked file, ignoring the named root files.

    ``exclude`` keeps the installer's own ``source.json`` from making a managed
    workspace look locally modified. Read-only: the index is not refreshed.
    """
    args = ["--no-optional-locks", "status", "--porcelain", "--untracked-files=normal"]
    if exclude:
        args += ["--", ".", *(f":(exclude){name}" for name in exclude)]
    return bool(run(root, *args).stdout.strip())


def rev_parse(root, ref: str) -> str:
    result = _check(run(root, "rev-parse", "--verify", f"{ref}^{{commit}}"), f"rev-parse {ref}")
    return result.stdout.strip()


def ls_remote(repository: str, ref: str) -> str:
    """The commit ``ref`` names in ``repository``, without fetching anything.

    An annotated tag lists both the tag object and its peeled commit; the
    commit is the one that ends up in a workspace.
    """
    wanted = [ref] if ref.startswith("refs/") else [f"refs/heads/{ref}", f"refs/tags/{ref}"]
    result = _check(run(None, "ls-remote", repository, *wanted, timeout=60),
                    f"ls-remote {repository}")
    found = {}
    for line in result.stdout.splitlines():
        sha, _, name = line.partition("\t")
        found[name.strip()] = sha.strip()
    for name in wanted:
        for key in (f"{name}^{{}}", name):
            if found.get(key):
                return found[key]
    raise ValueError(f"{repository} has no ref {ref}")


def clone_argv(repository: str, ref: str, dest: Path, depth: int | None = 1) -> list[str]:
    """The complete clone command; ``dest``'s parent must already exist.

    Managed workspaces are immutable and keyed by commit, so history is dead
    weight: ``depth=1`` turns a 240 MB product clone into the tree that is
    actually built. Pass ``depth=None`` for a full clone.
    """
    args = ["clone", "--quiet", "--branch", ref, "--single-branch"]
    if depth:
        args += ["--depth", str(depth)]
    return ["git", *args, repository, str(Path(dest))]


def clone(repository: str, ref: str, dest: Path, depth: int | None = 1) -> Path:
    """Clone ``repository`` at ``ref`` into ``dest`` (which must not exist)."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    argv = clone_argv(repository, ref, dest, depth)
    _check(run(None, *argv[1:]), f"clone {repository}")
    return dest


def checkout_detach(root, commit: str) -> None:
    _check(run(root, "checkout", "--detach", "--quiet", commit), f"checkout {commit}")
