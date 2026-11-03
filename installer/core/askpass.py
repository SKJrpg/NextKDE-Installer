"""Sudo on demand: an askpass helper that waits for an answer, and a sudo shim.

sudo ignores ``SUDO_ASKPASS`` unless ``-A`` is given, and the install children
run without a tty, so a ``sudo`` shim earlier on PATH adds ``-A`` and a helper
hands sudo one answer.  The helper asks for that answer by creating
``pending.<token>`` and waiting for ``answer.<token>``, which the UI writes when
the user types the password: the prompt appears exactly while a sudo call is
blocked, never before.  Nothing here puts the password in the environment, in
argv, or in the helper's own text.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

# %(dir)s and %(ticks)d: each tick is one 0.1 s sleep of the wait loop.
_HELPER = '''#!/bin/sh
# sudo -A runs this: print one answer, or wait for it.
umask 077
dir="%(dir)s"
[ -f "$dir/denied" ] && exit 1
[ -f "$dir/password" ] && exec cat "$dir/password"
token=$$
: > "$dir/pending.$token"
tick=0
while [ "$tick" -lt %(ticks)d ]; do
    # The run may end (and remove the tree) while sudo is still waiting.
    [ -d "$dir" ] || exit 1
    if [ -f "$dir/answer.$token" ]; then
        code=1
        [ -s "$dir/answer.$token" ] && cat "$dir/answer.$token" && code=0
        rm -f "$dir/answer.$token" "$dir/pending.$token"
        exit "$code"
    fi
    sleep 0.1
    tick=$((tick + 1))
done
rm -f "$dir/pending.$token"
exit 1
'''
_SHIM = '#!/bin/sh\nexec "%s" -A "$@"\n'

# How long a blocked sudo call waits for an answer before giving up.
TIMEOUT = 180


def sudo_ready() -> bool:
    """True when sudo already works without a password."""
    try:
        return subprocess.run(["sudo", "-n", "true"], capture_output=True,
                              timeout=5, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class Askpass:
    def __init__(self, runtime_dir: Path | None = None,
                 timeout: float = TIMEOUT) -> None:
        base = Path(runtime_dir) if runtime_dir is not None else Path(
            os.environ.get("XDG_RUNTIME_DIR") or "/tmp")
        try:
            self.dir = Path(tempfile.mkdtemp(prefix="kos-askpass-", dir=base))
        except OSError:
            # XDG_RUNTIME_DIR can name a directory we cannot write to.
            self.dir = Path(tempfile.mkdtemp(prefix="kos-askpass-", dir="/tmp"))
        self.helper_path = self.dir / "askpass.sh"
        self.shim_path = self.dir / "sudo"
        # Resolved before the shim exists, so the shim cannot find itself.
        sudo = shutil.which("sudo") or "/usr/bin/sudo"
        self._write(self.helper_path,
                    _HELPER % {"dir": self.dir, "ticks": max(1, int(timeout * 10))},
                    0o700)
        self._write(self.shim_path, _SHIM % sudo, 0o700)

    @staticmethod
    def _write(path: Path, text: str, mode: int) -> None:
        path.write_text(text, encoding="utf-8")
        path.chmod(mode)

    def _secret(self, path: Path, text: str) -> None:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        path.chmod(0o600)

    def _tokens(self) -> list[str]:
        try:
            names = sorted(path.name for path in self.dir.glob("pending.*"))
        except OSError:
            return []
        return [name[len("pending."):] for name in names]

    def pending(self) -> str | None:
        """The token of a sudo call waiting for an answer, or None."""
        tokens = self._tokens()
        return tokens[0] if tokens else None

    def answer(self, token: str, password: str) -> None:
        """Hand the waiting helper its password; an empty one means denied."""
        self._secret(self.dir / f"answer.{token}", password)

    def cancel(self) -> None:
        """Deny: this request fails now, and every later one fails at once.

        The ``denied`` marker is what keeps sudo from asking three times (or
        asking again for the next step) once the user has said no.
        """
        self._secret(self.dir / "denied", "")
        for token in self._tokens():
            self._secret(self.dir / f"answer.{token}", "")

    def set_password(self, password: str) -> None:
        """Plain mode only: no event loop there to answer a request mid-run."""
        self._secret(self.dir / "password", password)

    @property
    def env(self) -> dict[str, str]:
        """The two variables a child needs to find the shim and the helper."""
        path = os.environ.get("PATH", "")
        return {"PATH": str(self.dir) + (os.pathsep + path if path else ""),
                "SUDO_ASKPASS": str(self.helper_path)}

    def close(self) -> None:
        """Idempotent: the tree is gone even when the run crashed."""
        shutil.rmtree(self.dir, ignore_errors=True)

    def __enter__(self) -> "Askpass":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
