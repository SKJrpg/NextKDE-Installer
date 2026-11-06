"""Git Source Manager (docs/design.md §6): stable, development and local sources."""

from .manager import prepare
from .models import PreparedSource
from .resolver import CANONICAL_REPO, DEFAULT_SOURCE, DISABLED_SOURCES

__all__ = ["CANONICAL_REPO", "DEFAULT_SOURCE", "DISABLED_SOURCES",
           "PreparedSource", "prepare"]
