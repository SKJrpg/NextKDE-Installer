"""Directory separation: XDG roots, the product checkout and the log dir."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from installer.paths import Paths  # noqa: E402

HOME = Path.home()


class DefaultsTest(unittest.TestCase):
    def test_xdg_defaults(self) -> None:
        paths = Paths.resolve(env={})
        self.assertEqual(paths.installer_root, HERE)
        self.assertEqual(paths.source_root, (HOME / "NextKde").resolve())
        self.assertEqual(paths.build_root, HOME / ".cache" / "nextkde" / "build")
        self.assertEqual(paths.state_root, HOME / ".local" / "state" / "nextkde-installer")
        self.assertEqual(paths.log_dir, paths.state_root / "logs")
        self.assertEqual(paths.installer_runtime,
                         HOME / ".local" / "share" / "nextkde-installer")

    def test_state_is_not_the_product_tree(self) -> None:
        paths = Paths.resolve(env={})
        self.assertNotEqual(paths.state_root, paths.source_root)
        self.assertNotIn(paths.source_root, paths.log_dir.parents)


class XdgOverrideTest(unittest.TestCase):
    def test_env_homes_are_used(self) -> None:
        env = {"XDG_DATA_HOME": "/d", "XDG_CACHE_HOME": "/c", "XDG_STATE_HOME": "/s"}
        paths = Paths.resolve(env=env)
        self.assertEqual(paths.build_root, Path("/c/nextkde/build"))
        self.assertEqual(paths.state_root, Path("/s/nextkde-installer"))
        self.assertEqual(paths.installer_runtime, Path("/d/nextkde-installer"))


class SourceRootTest(unittest.TestCase):
    def test_kos_root_is_used(self) -> None:
        paths = Paths.resolve(env={"KOS_ROOT": "/product"})
        self.assertEqual(paths.source_root, Path("/product"))

    def test_explicit_argument_beats_kos_root(self) -> None:
        paths = Paths.resolve("/explicit", env={"KOS_ROOT": "/product"})
        self.assertEqual(paths.source_root, Path("/explicit"))

    def test_relative_source_is_absolute(self) -> None:
        paths = Paths.resolve("relative/checkout", env={})
        self.assertTrue(paths.source_root.is_absolute())
        self.assertEqual(paths.source_root, (Path.cwd() / "relative/checkout").resolve())

    def test_installer_root_can_be_overridden(self) -> None:
        paths = Paths.resolve(env={}, installer_root="/elsewhere")
        self.assertEqual(paths.installer_root, Path("/elsewhere"))


if __name__ == "__main__":
    unittest.main()
