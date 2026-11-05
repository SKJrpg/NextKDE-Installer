"""Options must not offer a capability the backend did not declare.

Pilot test with a fake backend: the row is disabled and says why, in text.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_VENDOR = ROOT / "vendor"
if _VENDOR.is_dir():
    sys.path.insert(0, str(_VENDOR))
HAS_TEXTUAL = importlib.util.find_spec("textual") is not None

if HAS_TEXTUAL:
    from textual.widgets import Checkbox

    from installer.backend.models import (ACTIVATION_START, INSTALL_CORE,
                                          INSTALL_LOCKSCREEN, BackendInfo)
    from installer.detect import OsInfo, Probe, System
    from installer.paths import Paths
    from installer.ui.app import KosApp
    from installer.ui.screens.options import OptionsScreen
    from installer.ui.screens.review import ReviewScreen


def fake_system() -> "System":
    return System(
        os=OsInfo(id="arch", version="", like=(), pretty="Arch Linux"),
        family="arch", method="kosctl", arch="x86_64",
        probes=[Probe("probe_os", "PASS", "Arch Linux")],
    )


def backend(*capabilities: str) -> "BackendInfo":
    return BackendInfo(product="nextkde", version="1.0.0", installer_api=1,
                       capabilities=frozenset(capabilities),
                       components=(), source="probe")


@unittest.skipUnless(HAS_TEXTUAL, "textual is not vendored (run tools/vendor.py)")
class OptionsCapabilityTest(unittest.IsolatedAsyncioTestCase):
    async def to_options(self, pilot) -> None:
        await pilot.press("tab")
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()

    def make_app(self, info: "BackendInfo") -> "KosApp":
        return KosApp(lang="en", system=fake_system(),
                      paths=Paths.resolve(source_root=ROOT), backend=info)

    async def test_missing_capabilities_disable_the_rows_with_a_reason(self) -> None:
        app = self.make_app(backend(INSTALL_CORE, ACTIVATION_START))
        async with app.run_test(size=(66, 20)) as pilot:
            await self.to_options(pilot)
            self.assertIsInstance(app.screen, OptionsScreen)
            app_row = app.screen.query_one("#app_todo", Checkbox)
            lock_row = app.screen.query_one("#lockscreen", Checkbox)
            start_row = app.screen.query_one("#start", Checkbox)
            self.assertTrue(app_row.disabled)
            self.assertTrue(lock_row.disabled)
            self.assertFalse(start_row.disabled)
            self.assertIn("install.apps", app_row.label.plain)
            self.assertIn("install.lockscreen", lock_row.label.plain)
            self.assertIn("unavailable", app_row.label.plain)

    async def test_declared_capabilities_leave_the_rows_usable(self) -> None:
        app = self.make_app(backend(INSTALL_CORE, "install.apps",
                                    INSTALL_LOCKSCREEN, ACTIVATION_START))
        async with app.run_test(size=(66, 20)) as pilot:
            await self.to_options(pilot)
            for ident in ("app_todo", "lockscreen", "start"):
                self.assertFalse(app.screen.query_one("#" + ident, Checkbox).disabled)

    async def test_incompatible_backend_never_reaches_review(self) -> None:
        app = self.make_app(backend(INSTALL_CORE))
        app.backend_error = "nextkde 1.0.0 requires installer API 2-3"
        async with app.run_test(size=(66, 20)) as pilot:
            await self.to_options(pilot)
            await pilot.press("tab")
            await pilot.pause()
            self.assertIsInstance(app.screen, OptionsScreen)
            self.assertNotIsInstance(app.screen, ReviewScreen)


if __name__ == "__main__":
    unittest.main()
