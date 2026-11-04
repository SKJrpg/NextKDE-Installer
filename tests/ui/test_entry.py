"""Stage T4: the CLI is the entry point.

The flags still become the same Options, and those Options are what the Textual
app opens with; without the vendored Textual an interactive run degrades to the
plain path instead of crashing.
"""

from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
_VENDOR = ROOT / "vendor"
if _VENDOR.is_dir():
    sys.path.insert(0, str(_VENDOR))
HAS_TEXTUAL = importlib.util.find_spec("textual") is not None

from installer.__main__ import main  # noqa: E402
from installer.detect import OsInfo, Probe, System  # noqa: E402
from installer.plan import Step  # noqa: E402
from installer.source.models import PreparedSource  # noqa: E402


class Tty(io.StringIO):
    def isatty(self) -> bool:
        return True

    def reconfigure(self, **kwargs) -> None:
        pass


def fake_system() -> "System":
    return System(
        os=OsInfo(id="cachyos", version="", like=("arch",), pretty="CachyOS"),
        family="arch",
        method="kosctl",
        arch="x86_64",
        probes=[Probe("probe_os", "PASS", "CachyOS")],
    )


def fake_plan():
    return [Step("core", "kosctl install", ["true"])]


class EntryTest(unittest.TestCase):
    @unittest.skipUnless(HAS_TEXTUAL, "textual is not vendored (run tools/vendor.py)")
    def test_flags_reach_the_app_options(self) -> None:
        captured = {}

        class FakeApp:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def run(self) -> int:
                return 0

        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(sys, "stdout", Tty()), \
                mock.patch.object(sys, "stdin", Tty()), \
                mock.patch("installer.__main__.detect", return_value=fake_system()), \
                mock.patch("installer.__main__.build_plan", return_value=fake_plan()), \
                mock.patch("installer.ui.app.KosApp", FakeApp):
            code = main(["--root", directory, "--source", "local", "--apps", "todo"])

        self.assertEqual(code, 0)
        opts = captured["opts"]
        self.assertEqual(opts.source, "local")
        self.assertEqual(opts.app_set, {"todo"})
        self.assertTrue(opts.apps)
        self.assertEqual(captured["system"].family, "arch")
        self.assertEqual(captured["paths"].source_root,
                         Path(directory).resolve())
        self.assertIn(captured["lang"], ("en", "zh"))

    @unittest.skipUnless(HAS_TEXTUAL, "textual is not vendored (run tools/vendor.py)")
    def test_config_keys_are_applied_before_the_app_starts(self) -> None:
        seen = {}

        class FakeApp:
            def __init__(self, **kwargs):
                pass

            def run(self) -> int:
                return 0

        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            config.write_text('{"keys": {"wizard.back": "b"}}', encoding="utf-8")
            with mock.patch.object(sys, "stdout", Tty()), \
                    mock.patch.object(sys, "stdin", Tty()), \
                    mock.patch("installer.__main__.detect", return_value=fake_system()), \
                    mock.patch("installer.__main__.build_plan", return_value=fake_plan()), \
                    mock.patch("installer.ui.keymap.apply_overrides",
                               side_effect=lambda mapping: seen.update(mapping)), \
                    mock.patch("installer.ui.app.KosApp", FakeApp):
                code = main(["--root", directory, "--config", str(config)])
        self.assertEqual(code, 0)
        self.assertEqual(seen, {"wizard.back": "b"})

    @unittest.skipUnless(HAS_TEXTUAL, "textual is not vendored (run tools/vendor.py)")
    def test_an_unknown_key_action_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            config.write_text('{"keys": {"wizard.nope": "x"}}', encoding="utf-8")
            with mock.patch.object(sys, "stdout", Tty()), \
                    mock.patch.object(sys, "stdin", Tty()), \
                    mock.patch("installer.__main__.detect", return_value=fake_system()), \
                    mock.patch("installer.__main__.build_plan", return_value=fake_plan()), \
                    self.assertRaises(SystemExit):
                main(["--root", directory, "--config", str(config)])

    def test_interactive_without_textual_falls_back_to_plain(self) -> None:
        stderr = io.StringIO()
        preparation = mock.MagicMock(steps=[], prepared=None)
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(sys, "stdout", Tty()), \
                mock.patch.object(sys, "stdin", Tty()), \
                mock.patch.object(sys, "stderr", stderr), \
                mock.patch("installer.__main__.detect", return_value=fake_system()), \
                mock.patch("installer.__main__.build_plan", return_value=fake_plan()), \
                mock.patch("installer.__main__.workflow.begin",
                           return_value=preparation), \
                mock.patch("installer.__main__.sudo_ready", return_value=True), \
                mock.patch("installer.__main__.plain.execute", return_value=0) as execute, \
                mock.patch("importlib.util.find_spec", return_value=None):
            code = main(["--root", directory])

        self.assertEqual(code, 0)
        execute.assert_called_once()
        self.assertIn("Textual not found", stderr.getvalue())

    def test_check_prints_the_detected_backend(self) -> None:
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tools").mkdir()
            script = root / "tools" / "kosctl"
            script.write_text("#!/usr/bin/env bash\ncat <<'EOF'\n"
                              "Usage: ./tools/kosctl <install|doctor>\nEOF\n",
                              encoding="utf-8")
            script.chmod(0o755)
            source = PreparedSource(mode="local", repository="https://example.invalid",
                                    ref="main", commit="b" * 40, path=root,
                                    dirty=False, managed=False)
            with mock.patch.object(sys, "stdout", stdout), \
                    mock.patch("installer.__main__.detect", return_value=fake_system()), \
                    mock.patch("installer.__main__.workflow.identity",
                               return_value=source):
                code = main(["--root", directory, "--check"])
        self.assertEqual(code, 0)
        self.assertIn("Backend: probe ·", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
