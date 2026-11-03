"""Which appearance the terminal is: dark or light.

The palette is already the terminal's own (``ansi_color`` + ``ansi_default``);
only the mode has to be known, because "quieter than body" means different
colours on the two: dimming the foreground reads as quieter on a dark
background and as washed out on a light one.

Detection order: the explicit ``--theme``/config value, then ``KOS_THEME``, then
the terminal's ``COLORFGBG`` (background index 0-6 and 8 are dark, 7 and 9-15
light). Terminals which report neither get dark.
"""

from __future__ import annotations

import os

_LIGHT_BACKGROUNDS = frozenset(range(9, 16)) | {7}


def resolve_mode(explicit: str | None = None, env=None) -> str:
    """``"dark"`` or ``"light"``; ``system`` and ``None`` detect."""
    env = os.environ if env is None else env
    if explicit in ("dark", "light"):
        return explicit
    chosen = env.get("KOS_THEME", "").strip().lower()
    if chosen in ("dark", "light"):
        return chosen
    background = env.get("COLORFGBG", "").split(";")[-1].strip()
    if background.isdigit():
        return "light" if int(background) in _LIGHT_BACKGROUNDS else "dark"
    return "dark"
