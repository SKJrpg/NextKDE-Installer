"""The two choices the installer remembers between runs.

Language and source channel are user preferences, not installation state: they
are small, safe to reapply, and live under the installer's XDG state root so a
throwaway ``XDG_STATE_HOME`` (tests, a portable run) keeps them isolated too.
"""

from __future__ import annotations

import json
import os

LANGUAGES = frozenset({"zh", "en"})
SOURCES = frozenset({"stable", "main", "local"})


def load(paths) -> dict[str, str]:
    """Read the remembered choices; a missing or broken file means none."""
    try:
        data = json.loads(paths.settings_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    remembered = {}
    if data.get("lang") in LANGUAGES:
        remembered["lang"] = data["lang"]
    if data.get("source") in SOURCES:
        remembered["source"] = data["source"]
    return remembered


def save(paths, *, lang: str | None = None, source: str | None = None) -> None:
    """Update one or both choices; the other remembered value survives."""
    remembered = load(paths)
    if lang in LANGUAGES:
        remembered["lang"] = lang
    if source in SOURCES:
        remembered["source"] = source
    if not remembered:
        return
    path = paths.settings_file
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(remembered, sort_keys=True) + "\n",
                             encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        # A read-only home must not stop an install; the next run falls back
        # to the language/env and the stable source.
        pass
