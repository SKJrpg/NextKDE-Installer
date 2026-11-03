"""Backend contract: declared capabilities, then what the checkout evidences.

Every fixture is a temporary checkout; no command outside it runs and the real
``kosctl`` is never called (the runtime fixture is a fake script).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from installer.backend import contract, probe  # noqa: E402
from installer.backend.models import (SYSTEM_DEPS, ACTIVATION_START, INSTALL_APPS,  # noqa: E402
                                      INSTALL_CORE, INSTALL_DEBIAN,
                                      INSTALL_DEBIAN_LOCAL, INSTALL_LOCKSCREEN,
                                      MANAGEMENT_SNAPSHOTS, MANAGEMENT_UNINSTALL,
                                      SYSTEM_DOCTOR, BackendIncompatible,
                                      BackendInfo, require)
from installer.paths import Paths  # noqa: E402
from installer.plan import Options, build_plan  # noqa: E402


def checkout(tmp: str) -> Path:
    root = Path(tmp)
    (root / "tools").mkdir(parents=True, exist_ok=True)
    return root


def kosctl(root: Path, usage: str) -> Path:
    """A bash script whose usage block is the only thing the probe reads."""
    script = root / "tools" / "kosctl"
    script.write_text("#!/usr/bin/env bash\ncat <<'EOF'\n" + usage + "\nEOF\n",
                      encoding="utf-8")
    script.chmod(0o755)
    return script


def info(capabilities=(), version="1.2.3") -> BackendInfo:
    return BackendInfo(product="nextkde", version=version, installer_api=1,
                       capabilities=frozenset(capabilities),
                       components=("calendar",), source="probe")


class ProbeTest(unittest.TestCase):
    def test_only_the_verbs_in_the_usage_are_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = checkout(tmp)
            kosctl(root, "Usage: ./tools/kosctl <doctor|install [lockscreen|apps]"
                        "|uninstall [lockscreen]|deps>")
            detected = probe.detect(root)
        self.assertEqual(detected.source, "probe")
        self.assertEqual(detected.capabilities, frozenset({
            SYSTEM_DOCTOR, SYSTEM_DEPS, INSTALL_CORE, INSTALL_APPS,
            INSTALL_LOCKSCREEN, MANAGEMENT_UNINSTALL}))
        # Nothing else is guessed: no start, update, nix or Debian wrapper.
        self.assertNotIn(ACTIVATION_START, detected.capabilities)

    def test_a_narrower_usage_yields_fewer_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = checkout(tmp)
            kosctl(root, "Usage: ./tools/kosctl <install|doctor>")
            detected = probe.detect(root)
        self.assertEqual(detected.capabilities,
                         frozenset({INSTALL_CORE, SYSTEM_DOCTOR}))

    def test_snapshots_need_kos_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = checkout(tmp)
            kosctl(root, "Usage: ./tools/kosctl <install>")
            self.assertNotIn(MANAGEMENT_SNAPSHOTS, probe.detect(root).capabilities)
            (root / "tools" / "kos-state.py").write_text("", encoding="utf-8")
            self.assertIn(MANAGEMENT_SNAPSHOTS, probe.detect(root).capabilities)

    def test_debian_wrapper_and_its_local_switch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = checkout(tmp)
            wrapper = root / "tools" / "install-debian13.sh"
            wrapper.write_text("#!/usr/bin/env bash\ncat <<'EOF'\n"
                               "Usage: bash install-debian13.sh [options]\n"
                               "  --dir <path>   where to clone\n"
                               "EOF\n", encoding="utf-8")
            detected = probe.detect(root)
            self.assertIn(INSTALL_DEBIAN, detected.capabilities)
            self.assertNotIn(INSTALL_DEBIAN_LOCAL, detected.capabilities)

            wrapper.write_text(wrapper.read_text(encoding="utf-8").replace(
                "  --dir <path>   where to clone",
                "  --local        keep the current checkout"), encoding="utf-8")
            self.assertIn(INSTALL_DEBIAN_LOCAL, probe.detect(root).capabilities)

    def test_version_comes_from_the_version_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = checkout(tmp)
            (root / "VERSION").write_text("4.5.6\n", encoding="utf-8")
            self.assertEqual(probe.detect(root).version, "4.5.6")

    def test_absent_kosctl_probes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            detected = probe.detect(checkout(tmp))
        self.assertEqual(detected.capabilities, frozenset())


class ContractTest(unittest.TestCase):
    def write(self, root: Path, data) -> Path:
        path = root / "packaging" / "installer-contract.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data) if not isinstance(data, str) else data,
                        encoding="utf-8")
        return path

    def test_static_file_is_preferred_over_probing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = checkout(tmp)
            kosctl(root, "Usage: ./tools/kosctl <install>")
            self.write(root, {"schema_version": 1, "product": {"id": "nextkde"},
                              "installer_api": {"minimum": 1, "maximum": 1},
                              "capabilities": ["install.apps"],
                              "components": ["todo"]})
            detected = contract.read(root)
        self.assertIsNotNone(detected)
        self.assertEqual(detected.source, "contract")
        self.assertEqual(detected.capabilities, frozenset({INSTALL_APPS}))
        self.assertEqual(detected.components, ("todo",))

    def test_unknown_capability_is_kept_but_unusable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = checkout(tmp)
            self.write(root, {"schema_version": 1,
                              "installer_api": {"minimum": 1, "maximum": 1},
                              "capabilities": ["install.core", "future.thing"],
                              "components": []})
            detected = contract.read(root)
        self.assertIn("future.thing", detected.capabilities)
        self.assertNotIn("future.thing", detected.usable)
        self.assertFalse(detected.has("future.thing"))
        self.assertTrue(detected.has(INSTALL_CORE))

    def test_wrong_api_range_is_incompatible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = checkout(tmp)
            (root / "VERSION").write_text("7.8.9", encoding="utf-8")
            self.write(root, {"schema_version": 1,
                              "installer_api": {"minimum": 2, "maximum": 3},
                              "capabilities": []})
            with self.assertRaises(BackendIncompatible) as caught:
                contract.read(root)
        self.assertIn("nextkde", str(caught.exception))
        self.assertIn("7.8.9", str(caught.exception))
        self.assertIn("installer API", str(caught.exception))

    def test_malformed_json_falls_back_to_the_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = checkout(tmp)
            kosctl(root, "Usage: ./tools/kosctl <install>")
            self.write(root, "{not json")
            self.assertIsNone(contract.read(root))
            detected = probe.detect(root)
        self.assertEqual(detected.source, "probe")
        self.assertIn(INSTALL_CORE, detected.capabilities)

    def test_runtime_command_is_a_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = checkout(tmp)
            script = root / "tools" / "kosctl"
            script.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"${1:-}\" == installer-info ]]; then\n"
                "  printf '%s' '{\"product\":\"nextkde\",\"product_version\":\"3.1.4\","
                "\"installer_api\":1,\"capabilities\":[\"install.core\"],"
                "\"components\":[\"calendar\"]}'\n"
                "  exit 0\n"
                "fi\n"
                "cat <<'EOF'\nUsage: ./tools/kosctl <installer-info|install>\nEOF\n",
                encoding="utf-8")
            script.chmod(0o755)
            detected = contract.read(root)
        self.assertIsNotNone(detected)
        self.assertEqual(detected.source, "contract")
        self.assertEqual(detected.version, "3.1.4")
        self.assertEqual(detected.capabilities, frozenset({INSTALL_CORE}))


class PlanCapabilityTest(unittest.TestCase):
    def paths_for(self, root: Path) -> Paths:
        return Paths(installer_root=HERE, source_root=root,
                     build_root=Path("/cache/build"), state_root=Path("/state"))

    def test_a_missing_capability_drops_its_step(self) -> None:
        backend = info({INSTALL_CORE, ACTIVATION_START})
        steps = build_plan("arch", Options(apps=True, lockscreen=True, start=True),
                           self.paths_for(Path("/nonexistent-checkout")),
                           backend=backend)
        keys = [step.key for step in steps]
        self.assertNotIn("apps", keys)
        self.assertNotIn("lockscreen", keys)
        self.assertIn("core", keys)
        self.assertIn("start", keys)

    def test_without_capabilities_nothing_is_emitted(self) -> None:
        steps = build_plan("arch", Options(), self.paths_for(Path("/x")),
                           backend=info())
        self.assertEqual(steps, [])

    def test_require_names_version_and_capability(self) -> None:
        with self.assertRaises(BackendIncompatible) as caught:
            require(info(version="2.0.0"), INSTALL_APPS)
        message = str(caught.exception)
        self.assertIn("2.0.0", message)
        self.assertIn(INSTALL_APPS, message)


if __name__ == "__main__":
    unittest.main()
