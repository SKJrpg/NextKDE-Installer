"""Detection and plan construction for the installer UI shell.

Pure functions only: no package manager is executed, no machine is modified.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from installer.detect import (family_of, latest_workspace, parse_missing_packages,  # noqa: E402
                              parse_os_release)
from installer.paths import Paths  # noqa: E402
from installer import plan  # noqa: E402
from installer.__main__ import _load_config as load_config  # noqa: E402
from installer.__main__ import _options as options  # noqa: E402
from installer.plan import (ALL_APPS, Options, build_plan, parse_app_deps, proxy_url,  # noqa: E402
                            session_env, unsupported)
from installer.strings import choose_language, cjk_fonts_available, resolve_lang  # noqa: E402

ROOT = Path("/repo")


def paths_for(root: Path) -> Paths:
    return Paths(installer_root=HERE, source_root=Path(root),
                 build_root=Path("/cache/build"), state_root=Path("/state"))


DEBIAN = 'ID=debian\nVERSION_ID="13"\nPRETTY_NAME="Debian GNU/Linux 13 (trixie)"\n'
UBUNTU = 'ID=ubuntu\nVERSION_ID="26.04"\nID_LIKE=debian\nPRETTY_NAME="Ubuntu 26.04"\n'
ARCH = 'ID=arch\nPRETTY_NAME="Arch Linux"\n'
FEDORA = 'ID=fedora\nVERSION_ID=44\n'
OPENSUSE = 'ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n'
NIXOS = 'ID=nixos\nVERSION_ID="25.05"\n'
UNKNOWN = 'ID=void\nPRETTY_NAME="Void Linux"\n'


class OsReleaseTest(unittest.TestCase):
    def test_parse_strips_quotes(self) -> None:
        info = parse_os_release(DEBIAN)
        self.assertEqual(info.id, "debian")
        self.assertEqual(info.version, "13")
        self.assertIn("Debian", info.label)

    def test_families(self) -> None:
        cases = {
            DEBIAN: "debian",
            UBUNTU: "ubuntu",
            ARCH: "arch",
            FEDORA: "fedora",
            OPENSUSE: "opensuse",
            NIXOS: "nixos",
            UNKNOWN: None,
        }
        for text, expected in cases.items():
            with self.subTest(expected=expected):
                self.assertEqual(family_of(parse_os_release(text)), expected)

    def test_ubuntu_is_not_debian(self) -> None:
        # Ubuntu has ID_LIKE=debian but must not take the Debian wrapper path.
        self.assertEqual(family_of(parse_os_release(UBUNTU)), "ubuntu")


class PlanTest(unittest.TestCase):
    def test_debian_uses_the_wrapper(self) -> None:
        steps = build_plan("debian", Options(source="main", start=True), paths_for(ROOT))
        # The wrapper installs the core; activation is a step of its own.
        self.assertEqual([step.key for step in steps], ["debian", "start"])
        argv = steps[0].argv
        self.assertIn("install-debian13.sh", argv[1])
        self.assertIn("--dir", argv)
        self.assertEqual(argv[argv.index("--version") + 1], "main")
        self.assertNotIn("--start", argv)

    def test_debian_passes_the_checkout_origin(self) -> None:
        with mock.patch.object(plan, "origin_url",
                               return_value="https://github.com/fork/NextKde.git"):
            argv = build_plan("debian", Options(), paths_for(ROOT))[0].argv
        self.assertEqual(argv[argv.index("--repo") + 1],
                         "https://github.com/fork/NextKde.git")

    def test_debian_local_keeps_the_checkout(self) -> None:
        with mock.patch.object(plan, "origin_url", return_value=""):
            argv = build_plan("debian", Options(source="local"), paths_for(ROOT))[0].argv
        self.assertIn("--local", argv)
        self.assertNotIn("--version", argv)
        self.assertNotIn("--repo", argv)

    def test_debian_components_follow_the_core(self) -> None:
        steps = build_plan("debian",
                           Options(apps=True, app_set={"calendar"}, lockscreen=True, start=True),
                           paths_for(ROOT))
        self.assertEqual([step.key for step in steps],
                         ["debian", "apps", "lockscreen", "start"])
        self.assertEqual(steps[1].argv[steps[1].argv.index("--only") + 1], "calendar")

    def test_arch_clean_main_selects_source_first(self) -> None:
        steps = build_plan("arch", Options(), paths_for(Path("/nonexistent-checkout")))
        # A missing checkout reports dirty, so source selection must be skipped.
        self.assertEqual(steps[0].key, "source")
        self.assertEqual(steps[0].argv, [])
        # Starting the desktop is on by default, and runs last.
        self.assertEqual([step.key for step in steps], ["source", "core", "start"])
        self.assertEqual(steps[-1].key, "start")

    def test_components_add_steps(self) -> None:
        steps = build_plan("arch", Options(apps=True, app_set=set(ALL_APPS),
                                           lockscreen=True, start=True),
                           paths_for(Path("/nonexistent-checkout")))
        keys = [step.key for step in steps]
        self.assertEqual(keys, ["source", "core", "apps", "lockscreen", "start"])

    def test_nixos_uses_flake(self) -> None:
        steps = build_plan("nixos", Options(), paths_for(ROOT))
        self.assertEqual(steps[0].argv[-2:], ["nix", "install"])

    def test_report_only_families_plan_nothing(self) -> None:
        self.assertEqual(build_plan("opensuse", Options(), paths_for(ROOT)), [])
        self.assertEqual(build_plan(None, Options(), paths_for(ROOT)), [])

    def test_apps_subset_passes_only(self) -> None:
        opts = Options(apps=True, app_set={"calendar", "weather"})
        steps = build_plan("arch", opts, paths_for(Path("/nonexistent-checkout")))
        apps = next(step for step in steps if step.key == "apps")
        self.assertIn("--only", apps.argv)
        self.assertEqual(apps.argv[apps.argv.index("--only") + 1], "calendar,weather")

        full = build_plan("arch", Options(apps=True, app_set=set(ALL_APPS)),
                          paths_for(Path("/nonexistent-checkout")))
        self.assertNotIn("--only", next(step for step in full if step.key == "apps").argv)

        # An empty set means "the standard apps", not "nothing": --apps used to
        # be a no-op because of this.
        none = Options(apps=True, app_set=set())
        argv = next(step for step in build_plan("arch", none, paths_for(Path("/nonexistent-checkout")))
                    if step.key == "apps").argv
        self.assertNotIn("--only", argv)

    def test_spatial_is_off_unless_asked(self) -> None:
        steps = build_plan("arch", Options(), paths_for(Path("/nonexistent-checkout")))
        self.assertTrue(all(step.env.get("KOS_BUILD_SPATIAL") == "OFF" for step in steps))
        on = build_plan("arch", Options(spatial=True), paths_for(Path("/nonexistent-checkout")))
        self.assertTrue(all(step.env.get("KOS_BUILD_SPATIAL") == "ON" for step in on))
        debian = build_plan("debian", Options(), paths_for(ROOT))[0].argv
        self.assertEqual(debian[debian.index("--spatial") + 1], "off")

    def test_proxy_url_reports_what_would_be_forwarded(self) -> None:
        self.assertEqual(proxy_url({}), "")
        self.assertEqual(proxy_url({"http_proxy": "http://a:1"}), "http://a:1")
        self.assertEqual(proxy_url({"https_proxy": "http://b:2", "http_proxy": "http://a:1"}),
                         "http://b:2")

    def test_session_env_points_at_the_user_bus(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "bus").touch()
            self.assertEqual(session_env({"XDG_RUNTIME_DIR": tmp}),
                             {"XDG_RUNTIME_DIR": tmp,
                              "DBUS_SESSION_BUS_ADDRESS": f"unix:path={tmp}/bus"})
            self.assertEqual(session_env({"XDG_RUNTIME_DIR": tmp,
                                          "DBUS_SESSION_BUS_ADDRESS": "unix:path=/x"}),
                             {"XDG_RUNTIME_DIR": tmp, "DBUS_SESSION_BUS_ADDRESS": "unix:path=/x"})
            self.assertEqual(session_env({"XDG_RUNTIME_DIR": f"{tmp}/nope"}), {})

    def test_proxy_env_is_forwarded_only_when_enabled(self) -> None:
        import os

        os.environ["http_proxy"] = "http://127.0.0.1:7897"
        try:
            on = build_plan("arch", Options(proxy=True), paths_for(Path("/nonexistent-checkout")))
            off = build_plan("arch", Options(proxy=False), paths_for(Path("/nonexistent-checkout")))
            self.assertEqual(on[0].env.get("http_proxy"), "http://127.0.0.1:7897")
            self.assertNotIn("http_proxy", off[0].env)
        finally:
            del os.environ["http_proxy"]


class RunnerTest(unittest.TestCase):
    def _run(self, body: str) -> tuple[int, list[str], str, str]:
        import tempfile

        from installer.plan import Step
        from installer.runner import StepRunner

        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "step.sh"
            script.write_text("#!/bin/sh\n" + body, encoding="utf-8")
            log_path = Path(tmp) / "step.log"
            step = Step("fixture", "fixture", ["sh", str(script)])
            with log_path.open("w", encoding="utf-8") as log:
                runner = StepRunner(step, Path(tmp), log)
                runner.start()
                lines: list[str] = []
                import time

                start = time.monotonic()
                while time.monotonic() - start < 5.0:
                    line = runner.readline(0.2)
                    if line is not None:
                        lines.append(line)
                    if runner.poll() is not None:
                        break
                rc = runner.close()
            return rc, lines, log_path.read_text(encoding="utf-8"), runner.phase, runner.progress

    def test_banner_sets_phase_and_lines_reach_the_log(self) -> None:
        # The trailing sleep keeps the process alive long enough for the reader
        # loop to consume both lines; a process that exits first has its output
        # drained straight into the log by close(), which made this racy.
        rc, lines, log, phase, _progress = self._run(
            "echo '=== build ==='\necho ok\nsleep 0.3\n")
        self.assertEqual(rc, 0)
        self.assertIn("=== build ===", lines)
        self.assertEqual(phase, "build")
        self.assertIn("=== build ===", log)
        self.assertIn("ok", log)

    def test_build_counter_becomes_progress(self) -> None:
        _rc, _lines, _log, _phase, progress = self._run("echo '[3/4] Building CXX'\necho ok\n")
        self.assertAlmostEqual(progress, 0.75)

    def test_nonzero_exit_is_reported(self) -> None:
        rc, _lines, _log, _phase, _progress = self._run("echo nope\nexit 3\n")
        self.assertEqual(rc, 3)


class AppDepParseTest(unittest.TestCase):
    def test_missing_app_dependencies(self) -> None:
        output = (
            "Missing or incompatible application dependencies:\n"
            "  - KF6CalendarCore (kcalendarcore)\n"
            "  - pkgconf\n"
            "Install the missing packages:\n"
            "sudo pacman -S --needed kcalendarcore\n"
        )
        self.assertEqual(parse_app_deps(output),
                         ["KF6CalendarCore (kcalendarcore)", "pkgconf"])

    def test_ready_output(self) -> None:
        self.assertEqual(parse_app_deps("Application system dependencies are ready (arch, Qt 6.12.0).\n"), [])


class DoctorParseTest(unittest.TestCase):
    def test_missing_packages_are_collected(self) -> None:
        output = (
            "ok   cmake        /usr/bin/cmake\n"
            "miss pkg:pkgconf    required to build the default configuration\n"
            "miss pkg:kf6-kio-devel   required to build the default configuration\n"
            "warn quickshell   2.0.0 (expected Quickshell 0.3.x)\n"
        )
        self.assertEqual(parse_missing_packages(output), ["pkgconf", "kf6-kio-devel"])

    def test_clean_doctor_output(self) -> None:
        self.assertEqual(parse_missing_packages("ok   cmake\nok   ninja\n"), [])

    def test_latest_workspace_is_the_newest_kosctl(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            older = base / "repo" / "aaa" / "tools" / "kosctl"
            newer = base / "repo" / "bbb" / "tools" / "kosctl"
            for path in (older, newer):
                path.parent.mkdir(parents=True)
                path.write_text("#!/bin/sh\n", encoding="utf-8")
            os.utime(older, (1000, 1000))
            os.utime(newer, (2000, 2000))
            self.assertEqual(latest_workspace(base), newer.parents[1])


class LanguageTest(unittest.TestCase):
    def test_explicit_flag_wins(self) -> None:
        self.assertEqual(resolve_lang("en", {"LANG": "zh_CN.UTF-8"}), "en")
        self.assertEqual(resolve_lang("zh", {"LANG": "en_US.UTF-8"}), "zh")

    def test_named_locales(self) -> None:
        self.assertEqual(resolve_lang(None, {"LANG": "zh_CN.UTF-8"}), "zh")
        self.assertEqual(resolve_lang(None, {"LANG": "zh-Hans.UTF-8"}), "zh")
        self.assertEqual(resolve_lang(None, {"LANG": "en_US.UTF-8"}), "en")
        self.assertEqual(resolve_lang(None, {"LANG": "de_DE.UTF-8"}), "en")

    def test_c_locale_means_no_preference(self) -> None:
        # The VM ships LANG=C.UTF-8; that is "no language", not "English".
        self.assertEqual(resolve_lang(None, {"LANG": "C.UTF-8"}), "zh")
        self.assertEqual(resolve_lang(None, {"LANG": "C"}), "en")
        self.assertEqual(resolve_lang(None, {"LANG": "POSIX"}), "en")

    def test_utf8_through_lc_ctype(self) -> None:
        self.assertEqual(resolve_lang(None, {"LANG": "C", "LC_CTYPE": "C.UTF-8"}), "zh")

    def test_precedence(self) -> None:
        self.assertEqual(resolve_lang(None, {"LC_ALL": "en_US.UTF-8", "LANG": "zh_CN.UTF-8"}), "en")
        self.assertEqual(resolve_lang(None, {"LC_MESSAGES": "zh_CN.UTF-8", "LANG": "en_US.UTF-8"}), "zh")
        self.assertEqual(resolve_lang(None, {"LANGUAGE": "zh_CN:en_US"}), "zh")

    def test_nothing_set_stays_ascii(self) -> None:
        self.assertEqual(resolve_lang(None, {}), "en")

    def test_missing_cjk_fonts_fall_back_to_english(self) -> None:
        # A UTF-8 locale is not proof that Chinese can be drawn.
        self.assertEqual(resolve_lang(None, {"LANG": "zh_CN.UTF-8"}, cjk_ok=False), "en")
        self.assertEqual(resolve_lang(None, {"LANG": "C.UTF-8"}, cjk_ok=False), "en")
        self.assertEqual(resolve_lang(None, {"LANG": "zh_CN.UTF-8"}, cjk_ok=True), "zh")
        # An explicit flag still wins over a missing font.
        self.assertEqual(resolve_lang("zh", {"LANG": "en_US.UTF-8"}, cjk_ok=False), "zh")

    def test_linux_console_never_claims_cjk(self) -> None:
        self.assertFalse(cjk_fonts_available({"TERM": "linux"}))

    def test_font_probe_only_runs_for_chinese(self) -> None:
        calls = []

        def probe() -> bool:
            calls.append(1)
            return True

        self.assertEqual(choose_language(None, {"LANG": "en_US.UTF-8"}, probe), ("en", False))
        self.assertEqual(choose_language(None, {"LANG": "de_DE.UTF-8"}, probe), ("en", False))
        self.assertEqual(calls, [])

        self.assertEqual(choose_language(None, {"LANG": "zh_CN.UTF-8"}, probe), ("zh", False))
        self.assertEqual(len(calls), 1)

        # An explicit flag never probes either.
        self.assertEqual(choose_language("zh", {"LANG": "en_US.UTF-8"}, probe), ("zh", False))
        self.assertEqual(len(calls), 1)

    def test_font_probe_failure_reports_the_fallback(self) -> None:
        self.assertEqual(choose_language(None, {"LANG": "zh_CN.UTF-8"}, lambda: False), ("en", True))
        self.assertEqual(choose_language(None, {"LANG": "C.UTF-8"}, lambda: False), ("en", True))


    def test_local_source_never_updates(self) -> None:
        steps = build_plan("arch", Options(source="local"), paths_for(Path("/nonexistent-checkout")))
        self.assertEqual(steps[0].key, "source")
        self.assertEqual(steps[0].argv, [])
        self.assertEqual(steps[0].note, "skipped_local")

    def test_nixos_reports_unsupported_selections(self) -> None:
        self.assertEqual(unsupported("nixos", Options()), [])
        self.assertEqual(unsupported("nixos", Options(apps=True, spatial=True)),
                         ["apps", "spatial"])
        # Every other family supports these through kosctl.
        self.assertEqual(unsupported("arch", Options(apps=True, lockscreen=True, spatial=True)), [])


class OptionsTest(unittest.TestCase):
    """CLI and config values must reach Options without inventing defaults."""

    @staticmethod
    def args(**overrides):
        base = dict(source=None, apps=None, lockscreen=False, start=False,
                    no_start=False, all=False, no_proxy=False)
        base.update(overrides)
        return argparse.Namespace(**base)

    def test_starting_the_desktop_is_on_by_default(self) -> None:
        self.assertTrue(options(self.args(), {}).start)
        self.assertTrue(options(self.args(), {"start": True}).start)

    def test_no_start_turns_it_off(self) -> None:
        self.assertFalse(options(self.args(no_start=True), {}).start)
        self.assertFalse(options(self.args(no_start=True), {"start": True}).start)
        self.assertFalse(options(self.args(), {"start": False}).start)

    def test_apps_flag_without_value_means_every_app(self) -> None:
        opts = options(self.args(apps="all"), {})
        self.assertTrue(opts.apps)
        self.assertEqual(opts.app_set, set())

    def test_apps_flag_with_a_list_selects_a_subset(self) -> None:
        opts = options(self.args(apps="calendar, todo"), {})
        self.assertTrue(opts.apps)
        self.assertEqual(opts.app_set, {"calendar", "todo"})

    def test_all_expands_to_apps_and_lockscreen(self) -> None:
        opts = options(self.args(all=True), {})
        self.assertTrue(opts.apps)
        self.assertTrue(opts.lockscreen)

    def test_config_accepts_spatial_and_an_app_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"source": "local", "apps": ["todo"], "spatial": true}',
                            encoding="utf-8")
            config = load_config(str(path))
        opts = options(self.args(), config)
        self.assertEqual(opts.source, "local")
        self.assertEqual(opts.app_set, {"todo"})
        self.assertTrue(opts.spatial)

    def test_config_rejects_unknown_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"nope": 1}', encoding="utf-8")
            with self.assertRaises(SystemExit):
                load_config(str(path))

    def test_legacy_components_still_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"components": ["apps", "lockscreen"]}', encoding="utf-8")
            config = load_config(str(path))
        opts = options(self.args(), config)
        self.assertTrue(opts.apps)
        self.assertTrue(opts.lockscreen)



class CancelTest(unittest.TestCase):
    def _runner(self):
        from installer.plan import Step
        from installer.runner import StepRunner

        runner = StepRunner(Step("x", "x", ["sleep", "30"]), Path("."), open(os.devnull, "w"))
        runner.proc = mock.Mock()
        runner.proc.pid = 4321
        runner.proc.poll.return_value = None
        return runner

    def test_cancel_terminates_the_group_then_kills(self) -> None:
        import signal
        import time

        runner = self._runner()
        with mock.patch("installer.runner.os.getpgid", return_value=99), \
                mock.patch("installer.runner.os.killpg") as killpg:
            runner.cancel()
            self.assertTrue(runner.cancelled)
            killpg.assert_called_once_with(99, signal.SIGTERM)
            # Nothing died within the grace period: escalate to SIGKILL once.
            runner._kill_deadline = time.monotonic() - 1
            runner.poll()
            killpg.assert_called_with(99, signal.SIGKILL)
            self.assertEqual(runner._kill_deadline, 0.0)



    def test_deps_step_appears_only_when_packages_are_missing(self) -> None:
        from installer.backend.models import (INSTALL_CORE, SOURCE_UPDATE, SYSTEM_DEPS,
                                              BackendInfo)

        info = BackendInfo(product="nextkde", version="1.0.0", installer_api=1,
                           capabilities=frozenset({INSTALL_CORE, SYSTEM_DEPS, SOURCE_UPDATE}),
                           components=(), source="probe")
        with_missing = build_plan("arch", Options(), paths_for(Path("/nonexistent-checkout")),
                                  deps_missing=True, backend=info)
        keys = [step.key for step in with_missing]
        # Right after the source decision, before anything builds.
        self.assertEqual(keys[:2], ["source", "deps"])
        self.assertEqual(with_missing[1].argv[-2:], ["deps", "--install"])
        self.assertEqual(with_missing[1].input, "y\n")

        complete = build_plan("arch", Options(), paths_for(Path("/nonexistent-checkout")),
                              deps_missing=False, backend=info)
        self.assertNotIn("deps", [step.key for step in complete])

    def test_deps_step_needs_the_backend_capability(self) -> None:
        from installer.backend.models import INSTALL_CORE, BackendInfo

        info = BackendInfo(product="nextkde", version="1.0.0", installer_api=1,
                           capabilities=frozenset({INSTALL_CORE}), components=(),
                           source="probe")
        steps = build_plan("arch", Options(), paths_for(Path("/nonexistent-checkout")),
                           deps_missing=True, backend=info)
        self.assertNotIn("deps", [step.key for step in steps])

    def test_arch_installs_packages_when_the_backend_has_no_deps_command(self) -> None:
        from installer.backend.models import INSTALL_CORE, BackendInfo

        info = BackendInfo(product="nextkde", version="1.0.0", installer_api=1,
                           capabilities=frozenset({INSTALL_CORE}), components=(),
                           source="probe")
        steps = build_plan("arch", Options(), paths_for(Path("/nonexistent-checkout")),
                           deps_missing=True, missing_packages=["gcc", "go"],
                           backend=info)
        package = next(step for step in steps if step.key == "packages")
        self.assertEqual(package.argv, ["sudo", "pacman", "-S", "--needed", "gcc", "go"])
        self.assertEqual(package.input, "y\n")
        self.assertNotIn("deps", [step.key for step in steps])

    def test_debian_keeps_its_wrapper_without_a_deps_step(self) -> None:
        steps = build_plan("debian", Options(), paths_for(ROOT), deps_missing=True)
        self.assertNotIn("deps", [step.key for step in steps])


if __name__ == "__main__":
    unittest.main()