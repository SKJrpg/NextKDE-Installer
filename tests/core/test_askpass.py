"""The one-password sudo channel: file modes, the shim's argv, and reuse."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
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

    def test_tree_and_files_are_private(self) -> None:
        self.assertEqual(self.ask.dir.parent, self.base)
        self.assertTrue(self.ask.dir.name.startswith("kos-askpass-"))
        self.assertEqual(self.mode(self.ask.dir), 0o700)
        self.assertEqual(self.mode(self.ask.helper_path), 0o700)
        self.assertEqual(self.mode(self.ask.shim_path), 0o700)

    def test_password_file_is_0600_and_env_is_empty_until_set(self) -> None:
        self.assertEqual(self.ask.env, {})
        self.ask.set_password(PASSWORD)
        self.assertEqual(self.mode(self.ask.password_path), 0o600)
        # The secret lives in one file, never in env, argv or helper text.
        self.assertNotIn(PASSWORD, str(self.ask.env))
        for path in (self.ask.helper_path, self.ask.shim_path):
            self.assertNotIn(PASSWORD, path.read_text(encoding="utf-8"))

    def test_helper_prints_exactly_the_password(self) -> None:
        self.ask.set_password(PASSWORD)
        result = subprocess.run([str(self.ask.helper_path)],
                                capture_output=True, check=True)
        self.assertEqual(result.stdout.decode(), PASSWORD)
        self.assertEqual(result.stderr, b"")

    def test_env_puts_the_shim_first_on_path(self) -> None:
        self.ask.set_password(PASSWORD)
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
        self.ask.set_password(PASSWORD)
        self.ask.close()
        self.assertFalse(self.ask.dir.exists())
        self.assertEqual(self.ask.env, {})
        self.ask.close()

    def test_unwritable_runtime_dir_falls_back_to_tmp(self) -> None:
        ask = Askpass(Path("/nonexistent-kos-askpass/base"))
        self.addCleanup(ask.close)
        self.assertEqual(ask.dir.parent, Path("/tmp"))


class ShimTraceTest(unittest.TestCase):
    """One password, two sudo calls: the trace the design promises."""

    def test_two_sudo_calls_reuse_one_password(self) -> None:
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
        ask.set_password(PASSWORD)
        env = {**os.environ, **ask.env}

        outputs = [subprocess.run(["sudo", "-n", "true"], env=env,
                                  capture_output=True, text=True, check=True)
                   for _ in range(2)]

        self.assertEqual([out.stdout for out in outputs], [PASSWORD, PASSWORD])
        self.assertEqual(calls.read_text(encoding="utf-8").splitlines(),
                         ["-A -n true", "-A -n true"])


if __name__ == "__main__":
    unittest.main()
