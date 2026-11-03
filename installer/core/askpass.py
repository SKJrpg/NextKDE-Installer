"""One sudo password for a whole run: an askpass helper and a sudo shim.

sudo ignores ``SUDO_ASKPASS`` unless ``-A`` is given, and the install children
run without a tty, so a ``sudo`` shim earlier on PATH adds ``-A`` and a helper
prints the password from a file only this user can read.  Nothing here puts the
password in the environment, in argv, or in the helper's own text.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

_HELPER = '#!/bin/sh\nexec cat "%s"\n'
_SHIM = '#!/bin/sh\nexec "%s" -A "$@"\n'


def sudo_ready() -> bool:
    """True when sudo already works without a password."""
    try:
        return subprocess.run(["sudo", "-n", "true"], capture_output=True,
                              timeout=5, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class Askpass:
    def __init__(self, runtime_dir: Path | None = None) -> None:
        base = Path(runtime_dir) if runtime_dir is not None else Path(
            os.environ.get("XDG_RUNTIME_DIR") or "/tmp")
        try:
            self.dir = Path(tempfile.mkdtemp(prefix="kos-askpass-", dir=base))
        except OSError:
            # XDG_RUNTIME_DIR can name a directory we cannot write to.
            self.dir = Path(tempfile.mkdtemp(prefix="kos-askpass-", dir="/tmp"))
        self.password_path = self.dir / "password"
        self.helper_path = self.dir / "askpass.sh"
        self.shim_path = self.dir / "sudo"
        # Resolved before the shim exists, so the shim cannot find itself.
        sudo = shutil.which("sudo") or "/usr/bin/sudo"
        self._write(self.helper_path, _HELPER % self.password_path, 0o700)
        self._write(self.shim_path, _SHIM % sudo, 0o700)
        self._set = False

    @staticmethod
    def _write(path: Path, text: str, mode: int) -> None:
        path.write_text(text, encoding="utf-8")
        path.chmod(mode)

    def set_password(self, password: str) -> None:
        fd = os.open(self.password_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                     0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(password)
        self.password_path.chmod(0o600)
        self._set = True

    @property
    def env(self) -> dict[str, str]:
        """The two variables a child needs; empty until a password is set."""
        if not self._set:
            return {}
        path = os.environ.get("PATH", "")
        return {"PATH": str(self.dir) + (os.pathsep + path if path else ""),
                "SUDO_ASKPASS": str(self.helper_path)}

    def close(self) -> None:
        """Idempotent: the tree is gone even when the run crashed."""
        self._set = False
        shutil.rmtree(self.dir, ignore_errors=True)

    def __enter__(self) -> "Askpass":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
