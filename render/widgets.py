"""Drawing primitives: width, clipping, wrapping, lists, bars, dialogs.

The functions that do not need a screen (``_width``, ``_clip``, ``_wrap``) are
plain string arithmetic, so the layout tests can check Chinese, English and long
paths without a terminal.  :class:`Canvas` is the only thing that touches curses
and every write goes through it, which is what keeps text inside its pane.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

import curses

from .theme import TEXT, Theme


def _wide(char: str) -> int:
    return 2 if unicodedata.east_asian_width(char) in "WF" else 1


def _width(text: str) -> int:
    return sum(_wide(char) for char in text)


def _clip(text: str, cells: int, mark: str = "…") -> str:
    """Cut to ``cells`` display cells, marking the cut with ``mark``."""
    if cells <= 0:
        return ""
    if _width(text) <= cells:
        return text
    room = cells - _width(mark)
    if room <= 0:
        return mark[:cells]
    kept, used = [], 0
    for char in text:
        if used + _wide(char) > room:
            break
        kept.append(char)
        used += _wide(char)
    return "".join(kept) + mark


_NO_LINE_START = "、。，；：）」』】！？!?,.;:)]}"


def _is_cjk(char: str) -> bool:
    return unicodedata.east_asian_width(char) in "WF"


def _wrap(text: str, cells: int) -> list[str]:
    """Wrap by display width, without breaking Latin words or starting a line
    with CJK punctuation."""
    lines = []
    while text:
        used, cut = 0, 0
        for index, char in enumerate(text):
            if used + _wide(char) > cells:
                break
            used += _wide(char)
            cut = index + 1
        cut = max(cut, 1)
        chunk, rest = text[:cut], text[cut:]
        if rest and not rest[0].isspace() and not _is_cjk(rest[0]) and not _is_cjk(chunk[-1]):
            # A Latin word straddles the cut. Moving the whole word down beats
            # splitting "sudo" into "s" + "udo"; the nearest space is useless
            # here because mixed CJK text can be a whole phrase without one.
            word_start = len(chunk)
            while word_start > 0 and (chunk[word_start - 1].isalnum()
                                      or chunk[word_start - 1] in "-_"):
                word_start -= 1
            # Only leave the word for the next line when something stays on
            # this one; word_start == 0 would emit an empty line forever.
            if 0 < word_start and len(chunk) - word_start <= 16:
                chunk, rest = text[:word_start], text[word_start:]
            else:
                space = chunk.rfind(" ")
                if space > 0 and len(chunk) - space <= 24 and not any(
                        _is_cjk(char) for char in chunk[space + 1:]):
                    chunk, rest = text[:space], text[space + 1:]
        if rest and rest[0] in _NO_LINE_START:
            if _width(chunk) + _wide(rest[0]) <= cells:
                # Pull closing punctuation up, but never past the cell budget.
                chunk, rest = chunk + rest[0], rest[1:]
            elif len(chunk) > 1:
                # No room: take the last character with it rather than start a
                # line with "）" or "，".
                chunk, rest = chunk[:-1], chunk[-1] + rest
        lines.append(chunk.rstrip())
        text = rest.lstrip()
    return lines


@dataclass
class Row:
    text: str
    role: str = TEXT
    bold: bool = False


class Canvas:
    """One frame of output; every write is clipped to the terminal."""

    def __init__(self, win, theme: Theme) -> None:
        self.win = win
        self.theme = theme
        self.height, self.width = win.getmaxyx()

    # -- raw writing ----------------------------------------------------
    def paint(self, y: int, x: int, text: str, attr: int = 0, width: int | None = None) -> None:
        if y < 0 or y >= self.height or x < 0 or x >= self.width or not text:
            return
        limit = self.width - x if width is None else min(width, self.width - x)
        if y == self.height - 1 and x + limit >= self.width:
            # Writing the very last cell of the screen raises in curses; every
            # other row may use its last column.
            limit -= 1
        if limit <= 0:
            return
        clipped = _clip(text, limit, self.theme.glyphs.more)
        try:
            self.win.addnstr(y, x, clipped, limit, attr)
        except curses.error:
            pass

    def put(self, y: int, x: int, text: str, role: str = TEXT, bold: bool = False,
            width: int | None = None) -> None:
        self.paint(y, x, text, self.theme.attr(role, bold), width)

    def rule(self, y: int, x: int, width: int) -> None:
        # Drawn as text, not through hline(): curses' hline takes a chtype and
        # raises on a multi-byte character like "─".
        if width <= 0:
            return
        self.put(y, x, self.theme.glyphs.box_h * width, "secondary", False, width)

    def vrule(self, x: int, y: int, height: int) -> None:
        for offset in range(max(0, height)):
            self.put(y + offset, x, self.theme.glyphs.box_v, "secondary", False, 2)

    # -- composite ------------------------------------------------------
    def wrapped(self, y: int, x: int, width: int, lines: int, text: str,
                role: str = TEXT, bold: bool = False) -> int:
        """Write ``text`` wrapped, at most ``lines`` rows; returns the next y."""
        chunks = _wrap(text, max(1, width))[:max(0, lines)]
        for index, chunk in enumerate(chunks):
            self.put(y + index, x, chunk, role, bold, width)
        return y + len(chunks)

    def bar(self, y: int, x: int, width: int, fraction: float | None) -> None:
        """A bar drawn only from real progress; ``None`` is indeterminate."""
        glyphs = self.theme.glyphs
        width = max(4, width)
        if fraction is None:
            self.put(y, x, glyphs.bar_empty * width, "secondary", False, width + 1)
            return
        filled = int(width * max(0.0, min(1.0, fraction)))
        self.put(y, x, glyphs.bar_full * filled + glyphs.bar_empty * (width - filled),
                 "brand", False, width + 1)

    def rows(self, box, rows: list[Row], selected: int | None = None,
             start: int = 0, pointer: bool = True) -> None:
        """Draw list rows; the selected one gets a full-width reversed bar.

        Width contract: with ``pointer=False`` the text gets all ``box.w``
        cells, so text wrapped to ``box.w`` is never clipped. With a pointer
        the marker takes three cells and callers size their text accordingly.
        """
        glyphs = self.theme.glyphs
        marker = "   " if pointer else ""
        for offset in range(max(0, min(box.h, len(rows) - start))):
            index = start + offset
            row = rows[index]
            y = box.y + offset
            if index == selected:
                prefix = f" {glyphs.pointer} " if pointer else ""
                line = _clip(prefix + row.text, box.w, glyphs.more)
                self.paint(y, box.x, line + " " * max(0, box.w - _width(line)),
                           self.theme.attr("selected"), box.w)
            else:
                self.put(y, box.x, marker + row.text, row.role, row.bold, box.w)

    def dialog(self, title: str, lines: list[str], keys: str) -> None:
        """A centred box over the page; the caller owns the blocking read."""
        g = self.theme.glyphs
        body = [*lines, "", keys]
        inner = max([_width(title), *(_width(line) for line in body)]) + 4
        width = max(20, min(self.width - 2, inner))
        height = len(body) + 4
        y = max(0, (self.height - height) // 2)
        x = max(0, (self.width - width) // 2)
        blank = " " * max(0, width - 1)
        for offset in range(height):
            self.paint(y + offset, x, blank, 0, width)
        self.paint(y, x, g.box_tl + g.box_h * max(0, width - 2) + g.box_tr,
                   self.theme.attr("brand"), width)
        self.paint(y + height - 1, x, g.box_bl + g.box_h * max(0, width - 2) + g.box_br,
                   self.theme.attr("brand"), width)
        for offset in range(1, height - 1):
            self.paint(y + offset, x, g.box_v, self.theme.attr("brand"), 1)
            self.paint(y + offset, x + width - 1, g.box_v, self.theme.attr("brand"), 1)
        self.put(y + 1, x + 2, title, "brand", True, width - 4)
        for offset, line in enumerate(body):
            role = "secondary" if offset == len(body) - 1 else TEXT
            self.put(y + 2 + offset, x + 2, line, role, False, width - 4)


def _printable(text: str) -> str:
    """Strip control characters: a log line must never move the cursor."""
    return "".join(char if char.isprintable() else " "
                   for char in text.expandtabs(4))
