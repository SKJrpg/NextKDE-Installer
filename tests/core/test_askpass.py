"""The on-demand sudo channel: requests, answers, denial, and the shim."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from installer.core.askpass import Askpass

PASSWORD = "s3cret passwörd"


class AskpassTest(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.ask = Askpass(self.base)
        self.addCleanup(self.ask.close)

    def mode(self, path: Path) -> int:
        return path.stat().st_mode & 0o777

    def wait_request(self) -> str:
        """The token of the request the helper just left behind."""
        for _ in range(500):
            token = self.ask.pending()
            if token is not None:
                return token
            time.sleep(0.01)
        self.fail("the helper never asked for an answer")

    def run_helper(self) -> subprocess.CompletedProcess:
        return subprocess.run([str(self.ask.helper_path)], capture_output=True,
                              timeout=30, check=False)

    def test_tree_and_files_are_private(self) -> None:
        self.assertEqual(self.ask.dir.parent, self.base)
        self.assertTrue(self.ask.dir.name.startswith("kos-askpass-"))
        self.assertEqual(self.mode(self.ask.dir), 0o700)
        self.assertEqual(self.mode(self.ask.helper_path), 0o700)
        self.assertEqual(self.mode(self.ask.shim_path), 0o700)

    def test_nothing_is_asked_or_stored_before_sudo_runs(self) -> None:
        self.assertIsNone(self.ask.pending())
        self.assertEqual(sorted(os.listdir(self.ask.dir)), ["askpass.sh", "sudo"])
        # The secret lives in one file once written, never in env or argv.
        self.ask.answer("token", PASSWORD)
        answer = self.ask.dir / "answer.token"
        self.assertEqual(self.mode(answer), 0o600)
        self.assertNotIn(PASSWORD, str(self.ask.env))
        for path in (self.ask.helper_path, self.ask.shim_path):
            self.assertNotIn(PASSWORD, path.read_text(encoding="utf-8"))

    def test_helper_waits_for_the_answer_then_prints_it_once(self) -> None:
        helper = subprocess.Popen([str(self.ask.helper_path)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(helper.kill)
        token = self.wait_request()
        self.assertIsNone(helper.poll())        # still blocked on sudo's behalf

        self.ask.answer(token, PASSWORD)
        out, err = helper.communicate(timeout=30)
        self.assertEqual(out.decode(), PASSWORD)
        self.assertEqual(err, b"")
        self.assertEqual(helper.returncode, 0)
        # Both markers are gone: the answer is not left on disk.
        self.assertIsNone(self.ask.pending())
        self.assertFalse((self.ask.dir / f"answer.{token}").exists())

    def test_no_answer_times_out_non_zero(self) -> None:
        ask = Askpass(self.base, timeout=0.3)
        self.addCleanup(ask.close)
        result = subprocess.run([str(ask.helper_path)], capture_output=True,
                                timeout=30, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertIsNone(ask.pending())

    def test_cancel_denies_an_open_request_and_later_ones(self) -> None:
        helper = subprocess.Popen([str(self.ask.helper_path)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(helper.kill)
        self.wait_request()
        self.ask.cancel()
        out, _err = helper.communicate(timeout=30)
        self.assertEqual(out, b"")              # denied: nothing printed
        self.assertEqual(helper.returncode, 1)
        # A later sudo call fails at once instead of prompting three times.
        later = self.run_helper()
        self.assertEqual(later.returncode, 1)
        self.assertEqual(later.stdout, b"")
        self.assertIsNone(self.ask.pending())

    def test_env_puts_the_shim_first_on_path(self) -> None:
        entries = self.ask.env["PATH"].split(os.pathsep)
        self.assertEqual(entries[0], str(self.ask.dir))
        self.assertEqual(entries[1:], os.environ["PATH"].split(os.pathsep))
        self.assertEqual(self.ask.env["SUDO_ASKPASS"], str(self.ask.helper_path))

    def test_shim_execs_the_real_sudo_with_dash_a(self) -> None:
        text = self.ask.shim_path.read_text(encoding="utf-8")
        sudo = shutil.which("sudo") or "/usr/bin/sudo"
        self.assertIn(f'exec "{sudo}" -A "$@"', text)
        # Resolved before the shim existed, so it can never exec itself.
        self.assertNotEqual(sudo, str(self.ask.shim_path))

    def test_close_removes_the_tree_and_is_idempotent(self) -> None:
        self.ask.answer("token", PASSWORD)
        self.ask.close()
        self.assertFalse(self.ask.dir.exists())
        self.assertIsNone(self.ask.pending())
        self.ask.close()

    def test_close_releases_a_waiting_helper(self) -> None:
        helper = subprocess.Popen([str(self.ask.helper_path)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(helper.kill)
        self.wait_request()
        self.ask.close()                        # the run ended while sudo waited
        out, _err = helper.communicate(timeout=30)
        self.assertEqual(out, b"")
        self.assertEqual(helper.returncode, 1)

    def test_unwritable_runtime_dir_falls_back_to_tmp(self) -> None:
        ask = Askpass(Path("/nonexistent-kos-askpass/base"))
        self.addCleanup(ask.close)
        self.assertEqual(ask.dir.parent, Path("/tmp"))


class ShimTraceTest(unittest.TestCase):
    """Two blocked sudo calls, each answered: the trace the design promises."""

    def test_two_sudo_calls_are_each_answered(self) -> None:
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        calls = base / "argv.log"
        real = base / "real-sudo"
        real.write_text(
            "#!/bin/sh\n"
            f'printf "%s\\n" "$*" >> "{calls}"\n'
            '"$SUDO_ASKPASS"\n',
            encoding="utf-8")
        real.chmod(0o755)
        with mock.patch("installer.core.askpass.shutil.which", return_value=str(real)):
            ask = Askpass(base)
        self.addCleanup(ask.close)
        env = {**os.environ, **ask.env}

        stop = threading.Event()

        def answer_loop() -> None:
            while not stop.is_set():
                token = ask.pending()
                if token is not None:
                    ask.answer(token, PASSWORD)
                time.sleep(0.02)

        self.addCleanup(stop.set)
        threading.Thread(target=answer_loop, daemon=True).start()

        outputs = [subprocess.run(["sudo", "-n", "true"], env=env,
                                  capture_output=True, text=True, timeout=30,
                                  check=True)
                   for _ in range(2)]

        self.assertEqual([out.stdout for out in outputs], [PASSWORD, PASSWORD])
        self.assertEqual(calls.read_text(encoding="utf-8").splitlines(),
                         ["-A -n true", "-A -n true"])


if __name__ == "__main__":
    unittest.main()
