"""The plain renderer: the non-TTY path and the fallback when Textual is absent.

Ported from the curses suite; only the renderer-specific blocks were dropped.
"""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from installer.detect import OsInfo, Probe, System  # noqa: E402
from installer.paths import Paths  # noqa: E402
from installer.plan import Step  # noqa: E402
from installer.render import plain  # noqa: E402
from installer.strings import Strings  # noqa: E402

PROBES = [Probe("probe_os", "PASS", "Arch Linux"),
          Probe("probe_disk", "WARN", "4.2 GiB free")]


def make_system() -> System:
    return System(os=OsInfo(id="arch", version="", like=(), pretty="Arch Linux"),
                  family="arch", method="kosctl", arch="x86_64",
                  probes=list(PROBES))


def make_paths(directory: Path) -> Paths:
    return Paths(installer_root=HERE, source_root=directory,
                 build_root=directory / "build", state_root=directory / "state")


class PlainTest(unittest.TestCase):
    def _report(self, stream) -> str:
        steps = [Step("core", "kosctl install", ["/repo/tools/kosctl", "install"])]
        with mock.patch.object(plain.sys, "stdout", stream):
            plain.print_report(make_system(), steps, Strings("en"))
        return stream.getvalue()

    def test_no_ansi_when_stdout_is_not_a_tty(self) -> None:
        output = self._report(io.StringIO())
        self.assertNotIn("\033", output)
        self.assertIn("System compatibility", output)
        self.assertIn("PASS", output)
        self.assertIn("kosctl install", output)

    def test_no_color_disables_ansi_on_a_tty(self) -> None:
        class Tty(io.StringIO):
            def isatty(self):
                return True

        with mock.patch.dict("os.environ", {"NO_COLOR": "1"}):
            output = self._report(Tty())
        self.assertNotIn("\033", output)

    def test_color_returns_on_a_tty_without_no_color(self) -> None:
        class Tty(io.StringIO):
            def isatty(self):
                return True

        with mock.patch.dict("os.environ", {}, clear=True):
            output = self._report(Tty())
        self.assertIn("\033[32m", output)

    def test_failure_names_the_log_path(self) -> None:
        stream = io.StringIO()
        step = Step("core", "kosctl install",
                    [sys.executable, "-c", "raise SystemExit(3)"])
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(plain.sys, "stdout", stream):
            code = plain.execute(make_system(), [step],
                                 make_paths(Path(directory)), Strings("en"))
        self.assertEqual(code, 1)
        output = stream.getvalue()
        self.assertIn(Strings("en")("log_path"), output)
        self.assertIn("3", output)
        self.assertNotIn("\033", output)


if __name__ == "__main__":
    unittest.main()
