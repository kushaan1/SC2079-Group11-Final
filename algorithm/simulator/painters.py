"""
What arena_view draws with. A Painter is five primitives in canvas pixels; the window backs it
with a tk.Canvas and `--snapshot` backs it with a Pillow image, so one drawing routine serves
both. RecordingPainter is for tests.
"""
from __future__ import annotations

from typing import Protocol, Sequence

Points = Sequence[tuple[float, float]]


class Painter(Protocol):
    def rect(self, x0: float, y0: float, x1: float, y1: float, *, fill: str | None = None,
             outline: str | None = None, width: float = 1.0, dash: tuple[int, ...] | None = None) -> None: ...

    def line(self, points: Points, *, fill: str, width: float = 1.0,
             dash: tuple[int, ...] | None = None) -> None: ...

    def polygon(self, points: Points, *, fill: str | None = None, outline: str | None = None,
                width: float = 1.0) -> None: ...

    def oval(self, x0: float, y0: float, x1: float, y1: float, *, fill: str | None = None,
             outline: str | None = None, width: float = 1.0) -> None: ...

    def text(self, x: float, y: float, text: str, *, fill: str, size: int, bold: bool = False,
             mono: bool = False, anchor: str = "center") -> None: ...


class RecordingPainter:
    """Records every call as (op, args, kwargs). Tests assert on what was drawn, not pixels."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def rect(self, *args, **kwargs):
        self.calls.append(("rect", args, kwargs))

    def line(self, *args, **kwargs):
        self.calls.append(("line", args, kwargs))

    def polygon(self, *args, **kwargs):
        self.calls.append(("polygon", args, kwargs))

    def oval(self, *args, **kwargs):
        self.calls.append(("oval", args, kwargs))

    def text(self, *args, **kwargs):
        self.calls.append(("text", args, kwargs))


class PilPainter:
    """Paints onto a Pillow image. Fonts: the first system TTF found from the same candidate
    families the window uses, else Pillow's default. Dev-only; the window never imports this."""

    UI_FILES = ("Avenir Next.ttc", "HelveticaNeue.ttc", "segoeui.ttf", "DejaVuSans.ttf", "Helvetica.ttc")
    MONO_FILES = ("Menlo.ttc", "consola.ttf", "DejaVuSansMono.ttf", "Courier New.ttf")

    def __init__(self, image) -> None:
        from PIL import ImageDraw
        self.image = image
        self.draw = ImageDraw.Draw(image)
        self._fonts: dict[tuple[bool, bool, int], object] = {}

    def _font(self, mono: bool, bold: bool, size: int):
        key = (mono, bold, size)
        if key not in self._fonts:
            self._fonts[key] = self._load(self.MONO_FILES if mono else self.UI_FILES, bold, size)
        return self._fonts[key]

    @staticmethod
    def _load(files: tuple[str, ...], bold: bool, size: int):
        """
        The first candidate family that is installed, at the weight asked for.

        The face is picked by NAME, not by index. A collection's face order is not
        standardised: macOS "Avenir Next.ttc" is Bold at index 0 and Bold Italic at index 1,
        so choosing by index draws every label bold and every bold label italic. Falls back to
        the family's first face, then to Pillow's default.
        """
        from PIL import ImageFont
        wanted = "bold" if bold else "regular"
        for name in files:
            faces = []
            for index in range(64):
                try:
                    faces.append(ImageFont.truetype(name, size, index=index))
                except OSError:
                    break
            if faces:
                return next((f for f in faces if f.getname()[1].lower() == wanted), faces[0])
        return ImageFont.load_default(size)

    def rect(self, x0, y0, x1, y1, *, fill=None, outline=None, width=1.0, dash=None):
        if dash and outline:
            self.draw.rectangle([x0, y0, x1, y1], fill=fill)
            self._dashed([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], outline, width, dash)
        else:
            self.draw.rectangle([x0, y0, x1, y1], fill=fill, outline=outline, width=max(1, round(width)))

    def line(self, points, *, fill, width=1.0, dash=None):
        if dash:
            self._dashed(list(points), fill, width, dash)
        else:
            self.draw.line(list(points), fill=fill, width=max(1, round(width)), joint="curve")

    def polygon(self, points, *, fill=None, outline=None, width=1.0):
        self.draw.polygon(list(points), fill=fill, outline=outline, width=max(1, round(width)))

    def oval(self, x0, y0, x1, y1, *, fill=None, outline=None, width=1.0):
        self.draw.ellipse([x0, y0, x1, y1], fill=fill, outline=outline, width=max(1, round(width)))

    def text(self, x, y, text, *, fill, size, bold=False, mono=False, anchor="center"):
        # tk's southern anchors sit on the text bbox's bottom edge, so they map to Pillow's
        # descender row (d), not its baseline (s).
        pil_anchor = {"center": "mm", "n": "ma", "s": "md", "e": "rm", "w": "lm",
                      "nw": "la", "ne": "ra", "sw": "ld", "se": "rd"}[anchor]
        self.draw.text((x, y), text, fill=fill, font=self._font(mono, bold, size), anchor=pil_anchor)

    def _dashed(self, points, colour, width, dash):
        import math
        on, off = dash[0], dash[1] if len(dash) > 1 else dash[0]
        w = max(1, round(width))
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            length = math.hypot(bx - ax, by - ay)
            if length == 0:
                continue
            ux, uy = (bx - ax) / length, (by - ay) / length
            pos = 0.0
            while pos < length:
                end = min(pos + on, length)
                self.draw.line([(ax + ux * pos, ay + uy * pos), (ax + ux * end, ay + uy * end)], fill=colour, width=w)
                pos = end + off


class TkPainter:
    """
    Paints onto a tk.Canvas. Everything it creates carries `tag`, so one layer clears at a time:
    the window keeps a static painter and a dynamic painter over the same canvas and redraws the
    moving parts every frame without rebuilding the grid.

    Takes the canvas and a Fonts rather than importing tkinter, so this module still imports on
    a machine with no tk.
    """

    def __init__(self, canvas, fonts, tag: str) -> None:
        self.canvas, self.fonts, self.tag = canvas, fonts, tag

    def rect(self, x0, y0, x1, y1, *, fill=None, outline=None, width=1.0, dash=None):
        self.canvas.create_rectangle(x0, y0, x1, y1, fill=fill or "", outline=outline or "",
                                     width=width, dash=dash or (), tags=self.tag)

    def line(self, points, *, fill, width=1.0, dash=None):
        flat = [c for point in points for c in point]
        self.canvas.create_line(*flat, fill=fill, width=width, dash=dash or (), capstyle="round",
                                joinstyle="round", tags=self.tag)

    def polygon(self, points, *, fill=None, outline=None, width=1.0):
        flat = [c for point in points for c in point]
        self.canvas.create_polygon(*flat, fill=fill or "", outline=outline or "", width=width, tags=self.tag)

    def oval(self, x0, y0, x1, y1, *, fill=None, outline=None, width=1.0):
        self.canvas.create_oval(x0, y0, x1, y1, fill=fill or "", outline=outline or "", width=width, tags=self.tag)

    def text(self, x, y, text, *, fill, size, bold=False, mono=False, anchor="center"):
        font = self.fonts.mono(size) if mono else self.fonts.ui(size, bold)
        self.canvas.create_text(x, y, text=text, fill=fill, font=font, anchor=anchor, tags=self.tag)
