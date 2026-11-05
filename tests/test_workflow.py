"""The install flow's source preparation (docs/design.md §10.5-10.7), offline.

Every repository is the temporary bare one the source tests build; nothing here
talks to GitHub, and no install step is executed.
"""

from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tests"))

from installer import workflow  # noqa: E402
from installer.detect import OsInfo, System  # noqa: E402
from installer.plan import Options, Step, build_plan  # noqa: E402
from installer.render import plain  # noqa: E402
from installer.strings import Strings  # noqa: E402
from test_source import (SourceTestCase, commit_all, git, make_repository,  # noqa: E402
                         url)


def make_checkout(work: Path) -> Path:
    """A local NextKDE checkout: the user's own directory."""
    git("init", "-q", "-b", "main", str(work))
    (work / "README.md").write_text("NextKDE\n", encoding="utf-8")
    (work / "tools").mkdir()
    (work / "tools" / "kosctl").write_text("#!/bin/sh\n", encoding="utf-8")
    commit_all(work, "first")
    return work


class PreparationTest(SourceTestCase):
    def opts(self, source: str = "main") -> Options:
        return Options(source=source)

    def test_development_fetches_the_workspace_through_one_step(self) -> None:
        bare, work = make_repository(self.base)
        commit = git("rev-parse", "HEAD", cwd=work).stdout.strip()

        preparation = workflow.begin("development", self.opts(), self.paths,
                                     repository=url(bare))
        self.assertIsNone(preparation.prepared)
        self.assertEqual(len(preparation.steps), 1)
        argv = preparation.steps[0].argv
        self.assertEqual(argv[:2], ["git", "clone"])
        self.assertEqual(argv[-2:], [url(bare), str(self.workspace(bare, commit)) + ".tmp"])
        # Nothing is fetched until the caller runs the step.
        self.assertFalse(self.workspace(bare, commit).exists())

        prepared = preparation.finish()
        self.assertEqual(prepared.commit, commit)
        self.assertEqual(prepared.mode, "development")
        self.assertEqual(prepared.ref, "main")
        self.assertEqual(prepared.path, self.workspace(bare, commit))
        self.assertTrue(prepared.managed)
        self.assertEqual(preparation.finish(), prepared)  # idempotent
        self.assertEqual(sorted(path.name for path in prepared.path.parent.iterdir()),
                         [commit])

        # A second begin() finds the workspace: nothing left to fetch.
        again = workflow.begin("development", self.opts(), self.paths,
                               repository=url(bare))
        self.assertEqual(again.prepared, prepared)
        self.assertEqual(again.steps, [])
        self.assertEqual(again.finish(), prepared)

    def test_local_uses_the_checkout_and_fetches_nothing(self) -> None:
        work = make_checkout(self.paths.source_root)
        before = git("rev-parse", "HEAD", cwd=work).stdout.strip()

        preparation = workflow.begin("local", self.opts("local"), self.paths)
        self.assertEqual(preparation.steps, [])
        prepared = preparation.finish()
        self.assertEqual(prepared.mode, "local")
        self.assertEqual(prepared.path, work.resolve())
        self.assertEqual(prepared.commit, before)
        self.assertFalse(prepared.managed)
        self.assertFalse(self.paths.sources_root.exists())

    def test_a_chosen_local_path_wins_over_the_root(self) -> None:
        chosen = make_checkout(self.base / "chosen")
        opts = Options(source="local", local_path=chosen)

        identity = workflow.identity("local", opts, self.paths)
        self.assertEqual(identity.path, chosen.resolve())
        prepared = workflow.begin("local", opts, self.paths).finish()
        self.assertEqual(prepared.path, chosen.resolve())

        steps = build_plan("arch", opts, self.paths, prepared)
        self.assertTrue(steps[0].argv[0].startswith(str(chosen.resolve())),
                        steps[0].argv)

    def test_a_local_path_is_ignored_for_other_sources(self) -> None:
        bare, _work = make_repository(self.base)
        chosen = make_checkout(self.base / "chosen")
        opts = Options(source="development", local_path=chosen)
        preparation = workflow.begin("development", opts, self.paths,
                                     repository=url(bare))
        self.assertIsNone(preparation.prepared)       # a clone, not the checkout
        self.assertEqual(preparation.stage.mode, "development")
        self.assertEqual(preparation.stage.repository, url(bare))

    def test_a_failed_fetch_leaves_no_workspace_and_raises_on_finish(self) -> None:
        bare, work = make_repository(self.base)
        commit = git("rev-parse", "HEAD", cwd=work).stdout.strip()
        preparation = workflow.begin("development", self.opts(), self.paths,
                                     repository=url(bare))
        with mock.patch("installer.source.git.clone", side_effect=RuntimeError("no network")):
            with self.assertRaises(RuntimeError):
                preparation.finish()
        self.assertIsNone(preparation.prepared)
        self.assertFalse(self.workspace(bare, commit).exists())
        self.assertFalse(self.workspace(bare, commit).parent.joinpath(
            commit + ".tmp").exists())


    def test_an_interrupted_clone_does_not_block_the_next_attempt(self) -> None:
        bare, work = make_repository(self.base)
        commit = git("rev-parse", "HEAD", cwd=work).stdout.strip()
        leftover = self.workspace(bare, commit).with_name(commit + ".tmp")
        leftover.mkdir(parents=True)
        (leftover / "junk").write_text("x\n", encoding="utf-8")

        preparation = workflow.begin("development", self.opts(), self.paths,
                                     repository=url(bare))
        self.assertFalse(leftover.exists())
        self.assertEqual(preparation.finish().commit, commit)


class PreparedPlanTest(SourceTestCase):
    def prepared(self, repository: str, source: str = "main"):
        preparation = workflow.begin("development", Options(source=source), self.paths,
                                     repository=repository)
        return preparation.finish()

    def test_the_plan_runs_inside_the_prepared_workspace(self) -> None:
        bare, _ = make_repository(self.base)
        prepared = self.prepared(url(bare))
        steps = build_plan("arch", Options(source="main", apps=True,
                                           app_set={"calendar"}, start=True),
                           self.paths, prepared)
        self.assertNotIn("source", [step.key for step in steps])
        self.assertFalse(any("update" in argument
                             for step in steps for argument in step.argv))
        self.assertEqual(steps[0].argv, [str(prepared.path / "tools" / "kosctl"),
                                         "install"])
        for step in steps:
            for argument in step.argv:
                if argument.startswith("/"):
                    self.assertTrue(argument.startswith(str(prepared.path)), argument)

    def test_debian_uses_the_workspace_as_a_local_source(self) -> None:
        bare, _ = make_repository(self.base)
        prepared = self.prepared(url(bare))
        argv = build_plan("debian", Options(source="main"), self.paths, prepared)[0].argv
        self.assertEqual(argv[1], str(prepared.path / "tools" / "install-debian13.sh"))
        self.assertEqual(argv[argv.index("--dir") + 1], str(prepared.path))
        self.assertIn("--local", argv)
        # The wrapper must not fetch or switch anything: no repo, no version.
        self.assertNotIn("--version", argv)
        self.assertNotIn("--repo", argv)

    def test_without_a_prepared_source_the_plan_is_unchanged(self) -> None:
        steps = build_plan("arch", Options(source="main"),
                           self.paths)
        self.assertEqual(steps[0].key, "source")


class PlainFlowTest(SourceTestCase):
    """The non-interactive loop fetches first, then runs the plan it enables."""

    def test_the_clone_runs_first_and_then_the_plan(self) -> None:
        bare, _ = make_repository(self.base)
        self.paths.source_root.mkdir()
        preparation = workflow.begin("development", Options(source="main"), self.paths,
                                     repository=url(bare))
        system = System(os=OsInfo(id="arch", version="", like=(), pretty="Arch Linux"),
                        family="arch", method="kosctl", arch="x86_64",
                        probes=[], blocked=False)
        plan = lambda: [  # noqa: E731 - the plan only exists after finish()
            Step("core", "echo hi", ["echo", "hi"])]

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = plain.execute(system, plan, self.paths, Strings("en"),
                                 preparation=preparation)
        self.assertEqual(code, 0)
        self.assertTrue(preparation.prepared.path.is_dir())
        printed = output.getvalue()
        self.assertLess(printed.index("=== [1/1] git clone main ==="),
                        printed.index("=== [1/1] echo hi ==="))
        self.assertTrue((self.paths.log_dir / "install.log").is_file())


class CheckIdentityTest(SourceTestCase):
    def test_resolving_the_identity_fetches_and_writes_nothing(self) -> None:
        bare, work = make_repository(self.base)
        commit = git("rev-parse", "HEAD", cwd=work).stdout.strip()

        source = workflow.identity("main", Options(source="main"), self.paths,
                                   repository=url(bare))
        self.assertEqual(source.commit, commit)
        self.assertEqual(source.path, self.workspace(bare, commit))
        self.assertFalse(self.paths.sources_root.exists())
        self.assertEqual(list(self.base.rglob("*.tmp")), [])

    def test_an_existing_workspace_reports_its_recorded_identity(self) -> None:
        bare, _ = make_repository(self.base)
        prepared = workflow.begin("development", Options(source="main"), self.paths,
                                  repository=url(bare)).finish()
        source = workflow.identity("main", Options(source="main"), self.paths,
                                   repository=url(bare))
        self.assertEqual(source, prepared)


if __name__ == "__main__":
    unittest.main()
