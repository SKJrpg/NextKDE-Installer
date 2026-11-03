"""The backend contract's vocabulary: capability names, the info record, and
the one compatibility rule.

Nothing here reads the filesystem or runs a command; ``contract`` and ``probe``
produce :class:`BackendInfo`, this module only describes what it may mean.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# The interface version this installer speaks (design §7.2-7.3).
INSTALLER_API = 1

SYSTEM_DOCTOR = "system.doctor"
SYSTEM_DEPS = "system.deps"
INSTALL_CORE = "install.core"
INSTALL_APPS = "install.apps"
INSTALL_LOCKSCREEN = "install.lockscreen"
INSTALL_DEBIAN = "install.debian"
INSTALL_DEBIAN_LOCAL = "install.debian.local"
ACTIVATION_START = "activation.start"
MANAGEMENT_UNINSTALL = "management.uninstall"
MANAGEMENT_SNAPSHOTS = "management.snapshots"
SOURCE_UPDATE = "source.update"
PLATFORM_NIX = "platform.nix"

# Every name this installer understands. A contract may carry more; those are
# kept in BackendInfo.capabilities but never acted on (design §7.4).
CAPABILITIES = frozenset({
    SYSTEM_DOCTOR, SYSTEM_DEPS, INSTALL_CORE, INSTALL_APPS, INSTALL_LOCKSCREEN,
    INSTALL_DEBIAN, INSTALL_DEBIAN_LOCAL, ACTIVATION_START,
    MANAGEMENT_UNINSTALL, MANAGEMENT_SNAPSHOTS, SOURCE_UPDATE, PLATFORM_NIX,
})


class BackendIncompatible(ValueError):
    """The product and this installer do not speak the same interface version."""


@dataclass(frozen=True)
class BackendInfo:
    product: str
    version: str
    installer_api: int
    capabilities: frozenset[str]
    components: tuple[str, ...]
    source: str  # "contract" (declared) or "probe" (read off the checkout)

    @property
    def usable(self) -> frozenset[str]:
        """The declared capabilities this installer can act on."""
        return self.capabilities & CAPABILITIES

    def has(self, capability: str) -> bool:
        """True only for a known capability the backend declared."""
        return capability in CAPABILITIES and capability in self.capabilities


def product_version(root: Path) -> str:
    try:
        return (Path(root) / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def require(info: BackendInfo, capability: str) -> None:
    """Refuse to continue when the backend cannot do ``capability``."""
    if not info.has(capability):
        raise BackendIncompatible(
            f"{info.product} {info.version or 'unknown'} does not provide {capability}")
