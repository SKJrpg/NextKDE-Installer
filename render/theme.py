"""Semantic colours and status glyphs for the terminal screens.

A screen names a *role* (brand, secondary, ok, warn, fail, selected) and a
*status*; the colour pair and the glyph are chosen here.  That is what lets the
same code draw "✔" on a UTF-8 terminal and "[ok]" on a Linux console or a
`LC_ALL=C` terminal, without any screen hard-coding either.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import curses

BRAND, TEXT, SECONDARY, SELECTED, OK, WARN, FAIL = (
    "brand", "text", "secondary", "selected", "ok", "warn", "fail")

# Pair numbers registered once in UI._loop; roles without a pair draw in the
# terminal's own foreground colour.
# Secondary text keeps the terminal's own foreground and only dims it, so a
# light-background terminal stays readable (white-on-white was the old bug).
PAIRS = {BRAND: 1, OK: 2, WARN: 3, FAIL: 4}


@dataclass(frozen=True)
class Glyphs:
    ok: str = "✔"
    warn: str = "⚠"
    fail: str = "✖"
    info: str = "·"
    checked: str = "[x]"
    unchecked: str = "[ ]"
    pointer: str = "❯"
    running: str = "…"
    more: str = "…"
    rule: str = "─"
    bar_full: str = "█"
    bar_empty: str = "░"
    box_h: str = "─"
    box_v: str = "│"
    box_tl: str = "┌"
    box_tr: str = "┐"
    box_bl: str = "└"
    box_br: str = "┘"
    sep: str = "·"
    up_down: str = "↑↓"
    left_right: str = "←→"


UNICODE = Glyphs()

# The console has no box drawing and no ✔; these also survive a non-UTF-8
# screen and a braille-less font.
ASCII = Glyphs(
    ok="[ok]", warn="[!]", fail="[fail]", info="-", checked="[x]", unchecked="[ ]",
    pointer=">", running="...", more="...", rule="-", bar_full="#", bar_empty="-",
    box_h="-", box_v="|", box_tl="+", box_tr="+", box_bl="+", box_br="+",
    sep="|", up_down="Up/Dn", left_right="L/R",
)

_STATUS_GLYPH = {"PASS": "ok", "WARN": "warn", "FAIL": "fail"}


def supports_unicode(encoding: str | None = None, term: str | None = None) -> bool:
    """Whether the terminal can draw the Unicode glyphs at all.

    The encoding is the real signal: a UTF-8 terminal can draw "✔" even when it
    has no CJK font (English is still shown).  The Linux console cannot, whatever
    LANG says, which is why it is excluded explicitly.
    """
    if encoding is None:
        from ..strings import ascii_terminal

        return not ascii_terminal()
    if (os.environ.get("TERM", "") if term is None else term) == "linux":
        return False
    return "utf" in encoding.lower()


def use_color() -> bool:
    """NO_COLOR (https://no-color.org) wins over curses' own capability check."""
    return not os.environ.get("NO_COLOR")


class Theme:
    def __init__(self, glyphs: Glyphs | None = None, color: bool = True) -> None:
        self.glyphs = glyphs or UNICODE
        self.color = color and use_color()

    def attr(self, role: str = TEXT, bold: bool = False) -> int:
        """curses attributes for a role; safe before start_color() (tests)."""
        if role == SECONDARY:
            return curses.A_DIM | (curses.A_BOLD if bold else 0)
        attr = 0
        if self.color:
            pair = PAIRS.get(BRAND if role == SELECTED else role)
            if pair:
                try:
                    attr = curses.color_pair(pair)
                except curses.error:
                    attr = 0
        if role == SELECTED:
            # Reverse video is also the focus cue on a monochrome terminal.
            attr |= curses.A_REVERSE
            bold = True
        return attr | (curses.A_BOLD if bold else 0)

    def glyph(self, status: str) -> str:
        name = _STATUS_GLYPH.get(status, "info")
        return getattr(self.glyphs, name)
