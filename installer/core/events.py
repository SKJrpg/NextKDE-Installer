"""What a running install reports to whatever is drawing it.

Nothing here imports a renderer: the Textual wizard and the plain renderer
consume the same values.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Event:
    kind: str          # "stage" | "log" | "done" | "failed" | "cancelled"
    text: str = ""
    key: str = ""
    index: int = 0      # 1-based step number for "stage"
    total: int = 0
    level: str = ""     # for "log": INFO | OK | WARN | ERROR
    # Only when the step itself reports a counter ("[12/206]"): the share of
    # the whole plan this step has done, 0..1. None means "not measurable".
    fraction: float | None = None
