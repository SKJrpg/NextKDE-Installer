"""Where the panes sit for a given terminal size.

Pure arithmetic, so every mode can be asserted without a terminal.  Three modes
per the design note:

* narrow   — under 80 columns: one column, everything stacked.
* standard — 80-109: a stage column plus the content.
* wide     — 110 and up: stage column, content, and a contextual detail column.

A terminal smaller than MIN_W x MIN_H gets ``tiny``: the caller shows one honest
line instead of half a screen.  Nothing here is capped at 100 columns: the block
grows with the terminal up to MAX_USABLE and is centred past that, so wide
terminals get a real third column instead of dead space.
"""

from __future__ import annotations

from dataclasses import dataclass

MIN_W, MIN_H = 40, 12
STANDARD_W, WIDE_W = 80, 110
MAX_USABLE = 160
HEADER_H = 2          # title row + rule
FOOTER_H = 2          # rule + key hints
GAP = 2


@dataclass(frozen=True)
class Box:
    """A rectangle of cells; ``h``/``w`` may be 0 when nothing fits."""

    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def below(self, rows: int) -> "Box":
        return Box(self.x, self.y + rows, self.w, max(0, self.h - rows))


@dataclass(frozen=True)
class Layout:
    width: int
    height: int
    mode: str                      # tiny | narrow | standard | wide
    x: int
    usable: int
    top: int
    bottom: int
    content: Box
    nav: Box | None = None
    detail: Box | None = None

    @property
    def tiny(self) -> bool:
        return self.mode == "tiny"


def layout_for(width: int, height: int) -> Layout:
    usable = max(1, min(width - 2, MAX_USABLE))
    x = max(1, (width - usable) // 2)
    top = HEADER_H
    bottom = max(top, height - FOOTER_H)
    body = Box(x, top, usable, bottom - top)

    if width < MIN_W or height < MIN_H:
        return Layout(width, height, "tiny", x, usable, top, bottom, body)

    if width < STANDARD_W:
        return Layout(width, height, "narrow", x, usable, top, bottom, body)

    if width < WIDE_W:
        nav_w = max(18, min(28, usable // 3))
        nav = Box(x, top, nav_w, body.h)
        content = Box(x + nav_w + GAP, top, usable - nav_w - GAP, body.h)
        return Layout(width, height, "standard", x, usable, top, bottom, content, nav)

    # The detail column takes a third of what the stage column leaves; the
    # content keeps at least ~56 cells, which is where lists and command
    # previews stop wrapping badly.
    nav_w = 18
    detail_w = max(28, min(36, (usable - nav_w - 2 * GAP) // 3))
    content = Box(x + nav_w + GAP, top, usable - nav_w - detail_w - 2 * GAP, body.h)
    detail = Box(content.right + GAP, top, detail_w, body.h)
    return Layout(width, height, "wide", x, usable, top, bottom, content,
                  Box(x, top, nav_w, body.h), detail)


def split_rows(box: Box, top_rows: int) -> tuple[Box, Box]:
    """Cut a pane horizontally: a fixed-height part and what is left below it."""
    top_rows = max(0, min(top_rows, box.h))
    return Box(box.x, box.y, box.w, top_rows), box.below(top_rows)


def stack_list(box: Box, count: int, detail_h: int) -> tuple[Box, Box | None]:
    """A list only as tall as its rows, with the detail block right below it.

    Leaving the detail at the bottom of the pane instead would park it under a
    screenful of blank rows.
    """
    if box.h < 4:
        return box, None
    detail_h = max(0, min(detail_h, box.h - 2))
    if detail_h <= 0:
        return box, None
    list_h = max(1, min(count, box.h - detail_h - 1))
    if box.h - list_h - 1 < 2:
        return Box(box.x, box.y, box.w, box.h), None
    return (Box(box.x, box.y, box.w, list_h),
            Box(box.x, box.y + list_h + 1, box.w, min(detail_h, box.h - list_h - 1)))


def scroll_start(selected: int, count: int, height: int) -> int:
    """First visible row so that ``selected`` stays inside a ``height`` window."""
    if height <= 0 or count <= height:
        return 0
    selected = max(0, min(selected, count - 1))
    start = selected - (height - 1) // 2
    return max(0, min(start, count - height))
