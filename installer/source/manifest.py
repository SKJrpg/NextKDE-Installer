"""The identity file kept inside a managed workspace (design §4.3)."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

NAME = "source.json"


def write(workspace, prepared) -> Path:
    """Write ``source.json`` in ``workspace`` atomically; return its path."""
    workspace = Path(workspace)
    data = {
        "mode": prepared.mode,
        "repository": prepared.repository,
        "ref": prepared.ref,
        "commit": prepared.commit,
        "prepared_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    path = workspace / NAME
    descriptor, temporary = tempfile.mkstemp(prefix=".source-", dir=str(workspace))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path


def read(workspace) -> dict:
    """The recorded identity of ``workspace``; raises when it is missing or broken."""
    return json.loads((Path(workspace) / NAME).read_text(encoding="utf-8"))
