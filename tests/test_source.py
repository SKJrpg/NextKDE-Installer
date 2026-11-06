"""Git Source Manager: stable, development and local sources, offline.

Every repository here is a temporary bare repository reached over ``file://``;
nothing in this module talks to GitHub.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from installer.paths import Paths  # noqa: E402
from installer.source import manifest  # noqa: E402
from installer.source.manager import (detect_local, inspect_local,  # noqa: E402
                                      local_candidates, prepare)
from installer.source.resolver import (CANONICAL_REPO, latest_release_branch,  # noqa: E402
                                       repository_id, resolve)

IDENTITY = ("-c", "user.name=test", "-c", "user.email=test@example.com")


def git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], cwd=None if cwd is None else str(cwd),
                            capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result


def commit_all(work: Path, message: str = "change") -> str:
    git("add", "-A", cwd=work)
    git(*IDENTITY, "commit", "-q", "-m", message, cwd=work)
    return git("rev-parse", "HEAD", cwd=work).stdout.strip()


def make_repository(base: Path, name: str = "repo", tag: str | None = None):
    """A bare origin plus a work tree that pushed to it; returns (bare, work)."""
    bare = base / f"{name}.git"
    work = base / f"{name}-work"
    git("init", "-q", "--bare", "-b", "main", str(bare))
    git("init", "-q", "-b", "main", str(work))
    (work / "tools").mkdir()
    (work / "tools" / "kosctl").write_text("#!/bin/sh\n", encoding="utf-8")
    (work / "README.md").write_text("NextKDE\n", encoding="utf-8")
    commit_all(work, "first")
    if tag:
        git("tag", tag, cwd=work)
    git("remote", "add", "origin", str(bare), cwd=work)
    git("push", "-q", "--tags", "origin", "main", cwd=work)
    return bare, work


def url(bare: Path) -> str:
    return f"file://{bare}"


class SourceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.base = Path(self._directory.name)
        self.paths = Paths.resolve(env={"XDG_DATA_HOME": str(self.base / "data"),
                                        "XDG_CACHE_HOME": str(self.base / "cache"),
                                        "XDG_STATE_HOME": str(self.base / "state")},
                                   source_root=self.base / "source")

    def tearDown(self) -> None:
        self._directory.cleanup()

    def workspace(self, bare: Path, commit: str) -> Path:
        return self.paths.sources_root / repository_id(url(bare)) / commit


class RepositoryIdTest(unittest.TestCase):
    def test_github_remotes_give_owner_repo(self) -> None:
        for remote in ("https://github.com/NextKde/NextKde.git",
                       "git@github.com:NextKde/NextKde.git",
                       "ssh://git@github.com/NextKde/NextKde"):
            self.assertEqual(repository_id(remote), "NextKde.NextKde")

    def test_result_is_a_single_directory_name(self) -> None:
        name = repository_id("file:///tmp/a b/repo.git")
        self.assertNotIn("/", name)
        self.assertEqual(name, "tmp.a_b.repo")

    def test_non_remote_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            repository_id("   ")


class ResolveTest(unittest.TestCase):
    def test_stable_prefers_an_explicit_tag(self) -> None:
        self.assertEqual(resolve("stable", "https://github.com/A/B.git", tag="v1.2.3"),
                         ("https://github.com/A/B.git", "v1.2.3"))

    def test_development_uses_main(self) -> None:
        self.assertEqual(resolve("development", "https://github.com/A/B.git")[1], "main")

    def test_stable_uses_the_newest_release_branch(self) -> None:
        with mock.patch("installer.source.resolver.latest_release_branch",
                        return_value="release/0.2"):
            self.assertEqual(resolve("stable", "https://github.com/A/B.git"),
                             ("https://github.com/A/B.git", "release/0.2"))

    def test_unknown_mode_and_missing_checkout(self) -> None:
        with self.assertRaises(ValueError):
            resolve("nightly")
        with self.assertRaises(ValueError):
            resolve("local")


class DevelopmentTest(SourceTestCase):
    def test_clones_main_and_reuses_the_workspace(self) -> None:
        bare, work = make_repository(self.base)
        commit = git("rev-parse", "HEAD", cwd=work).stdout.strip()

        first = prepare("development", url(bare), paths=self.paths)
        self.assertEqual(first.mode, "development")
        self.assertEqual(first.ref, "main")
        self.assertEqual(first.commit, commit)
        self.assertEqual(first.path, self.workspace(bare, commit))
        self.assertTrue(first.path.is_dir())
        self.assertTrue(first.managed)
        self.assertFalse(first.dirty)
        self.assertEqual(git("rev-parse", "HEAD", cwd=first.path).stdout.strip(), commit)
        self.assertEqual(manifest.read(first.path)["commit"], commit)
        self.assertEqual(manifest.read(first.path)["mode"], "development")
        self.assertEqual(first.manifest_path, first.path / "source.json")
        # The workspace is immutable and keyed by commit: history is not kept.
        self.assertEqual(git("rev-parse", "--is-shallow-repository",
                             cwd=first.path).stdout.strip(), "true")

        second = prepare("development", url(bare), paths=self.paths)
        self.assertEqual(second.path, first.path)
        self.assertEqual(second.commit, commit)
        self.assertEqual(sorted(p.name for p in first.path.parent.iterdir()), [commit])

    def test_another_repository_is_not_reused(self) -> None:
        bare_a, work_a = make_repository(self.base, "alpha")
        bare_b, work_b = make_repository(self.base, "beta")
        first = prepare("development", url(bare_a), paths=self.paths)
        second = prepare("development", url(bare_b), paths=self.paths)
        self.assertNotEqual(first.path, second.path)
        self.assertEqual(manifest.read(second.path)["repository"], url(bare_b))
        self.assertEqual(prepare("development", url(bare_a), paths=self.paths).path,
                         first.path)

    def test_missing_remote_raises_and_writes_nothing(self) -> None:
        with self.assertRaises(ValueError):
            prepare("development", f"file://{self.base}/missing.git", paths=self.paths)
        self.assertFalse(self.paths.sources_root.exists()
                         and any(self.paths.sources_root.iterdir()))


class StableTest(SourceTestCase):
    def test_explicit_tag_lands_on_its_commit(self) -> None:
        bare, work = make_repository(self.base, tag="v0.1.0")
        tagged = git("rev-parse", "v0.1.0^{commit}", cwd=work).stdout.strip()
        (work / "README.md").write_text("NextKDE\nmore\n", encoding="utf-8")
        head = commit_all(work, "after the tag")
        git("push", "-q", "origin", "main", cwd=work)
        self.assertNotEqual(tagged, head)

        source = prepare("stable", url(bare), tag="v0.1.0", paths=self.paths)
        self.assertEqual(source.ref, "v0.1.0")
        self.assertEqual(source.commit, tagged)
        self.assertEqual(source.path.name, tagged)
        self.assertEqual(git("rev-parse", "HEAD", cwd=source.path).stdout.strip(), tagged)
        self.assertEqual(manifest.read(source.path)["ref"], "v0.1.0")

    def test_missing_tag_raises(self) -> None:
        bare, _ = make_repository(self.base, tag="v0.1.0")
        with self.assertRaises(ValueError):
            prepare("stable", url(bare), tag="v9.9.9", paths=self.paths)
        self.assertFalse(self.workspace(bare, "v9.9.9").exists())


class StableBranchTest(SourceTestCase):
    def test_newest_release_branch_is_chosen_and_cloned(self) -> None:
        bare, work = make_repository(self.base)
        for name in ("release/0.9", "release/0.10", "release/next"):
            git("branch", name, cwd=work)
            git("push", "-q", "origin", name, cwd=work)
        commit = git("rev-parse", "release/0.10", cwd=work).stdout.strip()

        source = prepare("stable", url(bare), paths=self.paths)

        self.assertEqual(source.mode, "stable")
        self.assertEqual(source.ref, "release/0.10")
        self.assertEqual(source.commit, commit)
        self.assertEqual(source.path, self.workspace(bare, commit))
        self.assertEqual(git("rev-parse", "HEAD", cwd=source.path).stdout.strip(), commit)
        self.assertEqual(manifest.read(source.path)["ref"], "release/0.10")

    def test_no_release_branch_raises_and_writes_nothing(self) -> None:
        bare, _ = make_repository(self.base)
        with self.assertRaises(ValueError):
            prepare("stable", url(bare), paths=self.paths)
        self.assertFalse(self.paths.sources_root.exists()
                         and any(self.paths.sources_root.iterdir()))

    def test_highest_series_wins_numerically(self) -> None:
        bare, work = make_repository(self.base)
        for name in ("release/0.9", "release/0.10"):
            git("branch", name, cwd=work)
            git("push", "-q", "origin", name, cwd=work)
        self.assertEqual(latest_release_branch(url(bare)), "release/0.10")


class LocalTest(SourceTestCase):
    def checkout(self, *, kosctl: bool = True) -> Path:
        work = self.base / "local"
        git("init", "-q", "-b", "main", str(work))
        (work / "README.md").write_text("NextKDE\n", encoding="utf-8")
        if kosctl:
            (work / "tools").mkdir()
            (work / "tools" / "kosctl").write_text("#!/bin/sh\n", encoding="utf-8")
        commit_all(work, "first")
        return work

    def snapshot(self, root: Path) -> tuple[str, str, str]:
        return (git("rev-parse", "HEAD", cwd=root).stdout.strip(),
                git("status", "--porcelain", cwd=root).stdout,
                git("remote", "-v", cwd=root).stdout)

    def test_reports_identity_without_touching_the_checkout(self) -> None:
        work = self.checkout()
        git("remote", "add", "origin", "file:///nonexistent/NextKde.git", cwd=work)
        before = self.snapshot(work)

        source = prepare("local", checkout=str(work), paths=self.paths)
        self.assertEqual(source.mode, "local")
        self.assertEqual(source.ref, "main")
        self.assertEqual(source.commit, before[0])
        self.assertEqual(source.path, work.resolve())
        self.assertEqual(source.repository, "file:///nonexistent/NextKde.git")
        self.assertFalse(source.dirty)
        self.assertFalse(source.managed)
        self.assertIsNone(source.manifest_path)
        self.assertEqual(self.snapshot(work), before)
        self.assertFalse(self.paths.sources_root.exists())

    def test_modified_file_is_dirty(self) -> None:
        work = self.checkout()
        (work / "README.md").write_text("changed\n", encoding="utf-8")
        self.assertTrue(prepare("local", checkout=str(work), paths=self.paths).dirty)

    def test_untracked_file_is_dirty(self) -> None:
        work = self.checkout()
        (work / "new.txt").write_text("x\n", encoding="utf-8")
        self.assertTrue(prepare("local", checkout=str(work), paths=self.paths).dirty)

    def test_non_git_directory_is_rejected(self) -> None:
        plain = self.base / "plain"
        (plain / "tools").mkdir(parents=True)
        (plain / "tools" / "kosctl").write_text("", encoding="utf-8")
        with self.assertRaises(ValueError):
            prepare("local", checkout=str(plain), paths=self.paths)

    def test_checkout_without_kosctl_is_rejected(self) -> None:
        work = self.checkout(kosctl=False)
        with self.assertRaises(ValueError):
            prepare("local", checkout=str(work), paths=self.paths)


class FailureTest(SourceTestCase):
    def test_failed_clone_leaves_no_workspace_and_no_tmp(self) -> None:
        bare, work = make_repository(self.base)
        commit = git("rev-parse", "HEAD", cwd=work).stdout.strip()
        with mock.patch("installer.source.git.clone", side_effect=RuntimeError("no network")):
            with self.assertRaises(RuntimeError):
                prepare("development", url(bare), paths=self.paths)
        parent = self.workspace(bare, commit).parent
        self.assertFalse((parent / commit).exists())
        self.assertFalse((parent / (commit + ".tmp")).exists())


class CanonicalTest(unittest.TestCase):
    def test_the_one_canonical_repository(self) -> None:
        from installer import plan
        self.assertEqual(plan.CANONICAL_REPO, CANONICAL_REPO)
        self.assertEqual(CANONICAL_REPO, "https://github.com/NextKde/NextKde.git")


class TimeoutTest(unittest.TestCase):
    """A hung network must not freeze the UI behind an unbounded subprocess."""

    @staticmethod
    def completed(stdout: str = "") -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess([], 0, stdout, "")

    def test_run_passes_the_timeout_through(self) -> None:
        from installer.source import git as git_module
        with mock.patch("installer.source.git.subprocess.run",
                        return_value=self.completed()) as run:
            git_module.run(None, "status")
            self.assertEqual(run.call_args.kwargs["timeout"], git_module.TIMEOUT)
            git_module.run(None, "status", timeout=3)
            self.assertEqual(run.call_args.kwargs["timeout"], 3)

    def test_ls_remote_uses_a_short_timeout(self) -> None:
        from installer.source import git as git_module
        with mock.patch("installer.source.git.subprocess.run",
                        return_value=self.completed("a\trefs/heads/main\n")) as run:
            self.assertEqual(git_module.ls_remote("r", "main"), "a")
            self.assertEqual(run.call_args.kwargs["timeout"], 60)


class AnnotatedTagTest(unittest.TestCase):
    def test_ls_remote_returns_the_peeled_commit(self) -> None:
        from installer.source import git as sgit

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "work"
            work.mkdir()
            git(*IDENTITY, "init", "-q", "-b", "main", cwd=work)
            (work / "file").write_text("x", encoding="utf-8")
            git(*IDENTITY, "add", "file", cwd=work)
            git(*IDENTITY, "commit", "-q", "-m", "one", cwd=work)
            # An annotated tag names a tag object, not the commit.
            git(*IDENTITY, "tag", "-a", "v9.9.9", "-m", "release", cwd=work)
            commit = git("rev-parse", "HEAD", cwd=work).stdout.strip()
            tag_object = git("rev-parse", "v9.9.9", cwd=work).stdout.strip()
            self.assertNotEqual(commit, tag_object)
            self.assertEqual(sgit.ls_remote(f"file://{work}", "v9.9.9"), commit)
            self.assertEqual(sgit.ls_remote(f"file://{work}", "main"), commit)



if __name__ == "__main__":
    unittest.main()


class LocalDetectionTest(SourceTestCase):
    """Where the installer looks for a checkout, and what it accepts."""

    def checkout(self, root: Path, *, kosctl: bool = True) -> Path:
        git("init", "-q", "-b", "main", str(root))
        (root / "README.md").write_text("NextKDE\n", encoding="utf-8")
        if kosctl:
            (root / "tools").mkdir()
            (root / "tools" / "kosctl").write_text("#!/bin/sh\n", encoding="utf-8")
        commit_all(root, "first")
        return root

    def paths_for(self, root: Path, *, explicit: bool = True) -> Paths:
        return Paths(installer_root=HERE, source_root=root,
                     build_root=self.base / "build", state_root=self.base / "state",
                     data_home=self.base / "data", source_root_explicit=explicit)

    def test_the_explicit_root_is_the_first_candidate(self) -> None:
        explicit = self.checkout(self.base / "explicit")
        cwd = self.checkout(self.base / "cwd")
        home = self.base / "home"          # nothing there
        paths = self.paths_for(explicit)
        self.assertEqual(local_candidates(paths, cwd=cwd, home=home)[0],
                         explicit.resolve())
        source, _tried = detect_local(paths, cwd=cwd, home=home)
        self.assertEqual(source.path, explicit.resolve())

    def test_without_an_explicit_root_cwd_then_projects_then_home(self) -> None:
        cwd = self.checkout(self.base / "cwd")
        projects = self.checkout(self.base / "home" / "Projects" / "NextKde")
        home_checkout = self.checkout(self.base / "home" / "NextKde")
        home = self.base / "home"
        paths = self.paths_for(self.base / "ignored", explicit=False)
        tried = local_candidates(paths, cwd=cwd, home=home)
        self.assertEqual(tried, [cwd.resolve(), projects.resolve(),
                                 home_checkout.resolve()])
        self.assertEqual(detect_local(paths, cwd=cwd, home=home)[0].path,
                         cwd.resolve())

    def test_an_invalid_candidate_is_skipped(self) -> None:
        explicit = self.checkout(self.base / "explicit", kosctl=False)
        cwd = self.checkout(self.base / "cwd")
        paths = self.paths_for(explicit)
        source, tried = detect_local(paths, cwd=cwd, home=self.base / "home")
        self.assertEqual(source.path, cwd.resolve())
        self.assertEqual(tried[:2], [explicit.resolve(), cwd.resolve()])

    def test_nothing_valid_leaves_no_source(self) -> None:
        plain = self.base / "plain"
        (plain / "tools").mkdir(parents=True)
        (plain / "tools" / "kosctl").write_text("", encoding="utf-8")
        paths = self.paths_for(plain)
        source, tried = detect_local(paths, cwd=plain, home=self.base / "home")
        self.assertIsNone(source)
        # The explicit root and the cwd are the same directory: looked at once.
        self.assertEqual(len(tried), 3)

    def test_inspect_local_is_the_one_validation(self) -> None:
        work = self.checkout(self.base / "work")
        source = inspect_local(work)
        self.assertEqual(source.mode, "local")
        self.assertEqual(source.path, work.resolve())
        self.assertEqual(source.commit,
                         git("rev-parse", "HEAD", cwd=work).stdout.strip())
        self.assertFalse(source.dirty)

        (work / "README.md").write_text("changed\n", encoding="utf-8")
        self.assertTrue(inspect_local(work).dirty)
        with self.assertRaises(ValueError):
            inspect_local(self.checkout(self.base / "no-kosctl", kosctl=False))
        with self.assertRaises(ValueError):
            inspect_local(self.base / "missing")
