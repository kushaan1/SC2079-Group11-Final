from __future__ import annotations

import config

# Display scale: pixels per centimetre
SCALE_PX_PER_CM = 3
ARENA_PX = config.ARENA_SIZE_CM * SCALE_PX_PER_CM
GRID_STEP_CM = 10


def to_canvas(x_cm: float, y_cm: float) -> tuple[float, float]:
    """Arena centimetres (origin bottom-left, y up) -> canvas pixels (origin top-left, y down)."""
    return x_cm * SCALE_PX_PER_CM, (config.ARENA_SIZE_CM - y_cm) * SCALE_PX_PER_CM


def to_arena(px: float, py: float) -> tuple[int, int]:
    """Canvas pixels -> arena centimetres (rounded to int)."""
    x_cm = int(px / SCALE_PX_PER_CM)
    y_cm = int((ARENA_PX - py) / SCALE_PX_PER_CM)
    return x_cm, y_cm


def cell_rect(x_cm: int, y_cm: int, size_cm: int) -> tuple[float, float, float, float]:
    """Return (x0,y0,x1,y1) canvas bbox for a square with south-west corner at (x_cm,y_cm)."""
    x0, y1 = to_canvas(x_cm, y_cm)
    x1, y0 = to_canvas(x_cm + size_cm, y_cm + size_cm)
    return x0, y0, x1, y1


def snap(value_cm: float, step_cm: int) -> int:
    return int(value_cm // step_cm) * step_cm
