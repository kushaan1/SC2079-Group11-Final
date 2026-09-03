"""
Font families for the window, with fallbacks, because the demo laptop can be anyone's.

The candidate lists are the same families PilPainter looks for as TTF files, so a snapshot and
the window agree about which face they are drawing with. This is the only module that queries
tk's font database.
"""
from __future__ import annotations

import tkinter
import tkinter.font as tkfont
from typing import Iterable, Sequence

UI_CANDIDATES = ("Avenir Next", "Helvetica Neue", "Segoe UI", "DejaVu Sans", "Helvetica")
MONO_CANDIDATES = ("Menlo", "Consolas", "DejaVu Sans Mono", "Courier New", "Courier")


def pick(installed: Iterable[str], candidates: Sequence[str], fallback: str) -> str:
    """The first candidate that is installed, else the fallback (a tk named font, always there)."""
    have = set(installed)
    return next((c for c in candidates if c in have), fallback)


class Fonts:
    """Cached tk fonts in the two families. One instance per window; sizes are pixels, so the
    window matches the PilPainter snapshot on every screen."""

    def __init__(self, root: tkinter.Misc) -> None:
        self.root = root
        installed = tkfont.families(root)
        self.ui_family = pick(installed, UI_CANDIDATES, "TkDefaultFont")
        self.mono_family = pick(installed, MONO_CANDIDATES, "TkFixedFont")
        self._cache: dict[tuple[str, int, bool], tkfont.Font] = {}

    def _get(self, family: str, size: int, bold: bool) -> tkfont.Font:
        key = (family, size, bold)
        if key not in self._cache:
            # Negative size means PIXELS. A positive size is points, which Tk scales by the
            # screen's DPI: the same window would render a third larger on a 96-dpi laptop and
            # would no longer match the pixel-sized text PilPainter draws in --snapshot.
            self._cache[key] = tkfont.Font(root=self.root, family=family, size=-size,
                                           weight="bold" if bold else "normal")
        return self._cache[key]

    def ui(self, size: int, bold: bool = False) -> tkfont.Font:
        return self._get(self.ui_family, size, bold)

    def mono(self, size: int) -> tkfont.Font:
        return self._get(self.mono_family, size, False)
