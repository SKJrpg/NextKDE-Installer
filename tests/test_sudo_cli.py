"""Plain / --yes: one password on a tty, a clear exit 2 without one."""

from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from unittest import mock

from installer.__main__ import main
from installer.detect import OsInfo, Probe, System
from installer.plan import Step


class Tty(io.StringIO):
    def isatty(self) -> bool:
        return True

    def reconfigure(self, **kwargs) -> None:
        pass


def fake_system() -> "System":
    return System(os=OsInfo(id="cachyos", version="", like=("arch",), pretty="CachyOS"),
                  family="arch", method="kosctl", arch="x86_64",
                  probes=[Probe("probe_sudo", "WARN", "password required")])


def fake_plan():
    return [Step("core", "kosctl install", ["true"])]


class PlainSudoTest(unittest.TestCase):
    def make_patches(self, stdin, stderr=None, sudo_ready=False):
        return [
            mock.patch.object(sys, "stdout", Tty()),
            mock.patch.object(sys, "stdin", stdin),
            mock.patch.object(sys, "stderr", stderr or io.StringIO()),
            mock.patch("installer.__main__.detect", return_value=fake_system()),
            mock.patch("installer.__main__.build_plan", return_value=fake_plan()),
            mock.patch("installer.__main__.sudo_ready", return_value=sudo_ready),
        ]

    def test_no_tty_and_no_sudo_exits_2_before_any_step(self) -> None:
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            patches = self.make_patches(io.StringIO(), stderr)
            with patches[0], patches[1], patches[2], patches[3], patches[4], \
                    patches[5], \
                    mock.patch("installer.__main__.workflow.begin") as begin, \
                    mock.patch("installer.__main__.plain.execute") as execute:
                code = main(["--root", directory, "--plain"])

        self.assertEqual(code, 2)
        self.assertIn("sudo -v", stderr.getvalue())
        begin.assert_not_called()
        execute.assert_not_called()

    def test_tty_asks_once_and_the_run_gets_the_askpass_env(self) -> None:
        seen: dict[str, str] = {}

        def fake_execute(system, steps, paths, strings, preparation=None) -> int:
            seen["askpass"] = os.environ.get("SUDO_ASKPASS", "")
            seen["first"] = os.environ["PATH"].split(os.pathsep)[0]
            seen["files"] = ",".join(sorted(os.listdir(seen["first"])))
            seen["mode"] = oct(os.stat(seen["first"]).st_mode & 0o777)
            return 0

        before = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(before)))
        preparation = mock.MagicMock(steps=[], prepared=None)
        with tempfile.TemporaryDirectory() as directory:
            patches = self.make_patches(Tty())
            with patches[0], patches[1], patches[2], patches[3], patches[4], \
                    patches[5], \
                    mock.patch("installer.__main__.workflow.begin",
                               return_value=preparation), \
                    mock.patch("installer.__main__.getpass.getpass",
                               return_value="pw") as getpass_mock, \
                    mock.patch("installer.__main__.plain.execute",
                               side_effect=fake_execute):
                code = main(["--root", directory, "--yes"])

        self.assertEqual(code, 0)
        getpass_mock.assert_called_once()
        self.assertTrue(seen["askpass"].endswith("/askpass.sh"))
        self.assertEqual(seen["first"], os.path.dirname(seen["askpass"]))
        self.assertEqual(seen["files"], "askpass.sh,password,sudo")
        self.assertEqual(seen["mode"], "0o700")
        # Everything is gone once the run ends.
        self.assertFalse(os.path.exists(seen["first"]))


if __name__ == "__main__":
    unittest.main()
