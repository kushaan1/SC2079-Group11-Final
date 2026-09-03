"""
Arena centimetres <-> canvas pixels, and the small pure geometry the simulator draws with.

The arena's origin is bottom-left with y up; a canvas's origin is top-left with y down. This is
the ONLY module that converts between them. Anything that computes a pixel from a centimetre
anywhere else is a bug waiting to render the arena upside down.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import config
from pathfinding.world.primitives import Direction, Point

# Compass heading in degrees, clockwise from north. The tablet uses the same convention.
HEADING_DEG = {Direction.NORTH: 0, Direction.EAST: 90, Direction.SOUTH: 180, Direction.WEST: 270}

# Canvas size limits in pixels, and the vertical room left for the title bar and transport bar.
_MIN_ARENA_PX, _MAX_ARENA_PX, _RESERVED_PX = 480, 720, 220


@dataclass(frozen=True)
class Geometry:
    """Conversion for one canvas: `scale` pixels per centimetre over an `arena_cm` square."""

    scale: float
    arena_cm: int

    @property
    def arena_px(self) -> float:
        return self.arena_cm * self.scale

    def to_canvas(self, x_cm: float, y_cm: float) -> tuple[float, float]:
        return x_cm * self.scale, (self.arena_cm - y_cm) * self.scale

    def to_arena(self, px: float, py: float) -> tuple[float, float]:
        return px / self.scale, self.arena_cm - py / self.scale

    def rect(self, x_cm: float, y_cm: float, w_cm: float, h_cm: float) -> tuple[float, float, float, float]:
        """Canvas bbox (x0, y0, x1, y1), y0 < y1, of a box whose SOUTH-WEST corner is (x_cm, y_cm)."""
        x0, y1 = self.to_canvas(x_cm, y_cm)
        x1, y0 = self.to_canvas(x_cm + w_cm, y_cm + h_cm)
        return x0, y0, x1, y1


def fit_scale(screen_height_px: int, arena_cm: int) -> float:
    """Pixels per cm so the arena fits the screen with room for the bars, within sane bounds."""
    arena_px = max(_MIN_ARENA_PX, min(_MAX_ARENA_PX, screen_height_px - _RESERVED_PX))
    return arena_px / arena_cm


def snap(value_cm: float, step_cm: int) -> int:
    """Round down to the nearest multiple of step_cm (clicks onto the obstacle grid)."""
    return int(value_cm // step_cm) * step_cm


def cell_to_corners(cx: int, cy: int) -> tuple[Point, Point]:
    """Tablet cell -> inclusive corners of the obstacle occupying it."""
    size = config.OBSTACLE_SIZE_CM
    return Point(cx * size, cy * size), Point(cx * size + size - 1, cy * size + size - 1)


def corners_to_cell(south_west: Point) -> tuple[int, int]:
    size = config.OBSTACLE_SIZE_CM
    return south_west.x // size, south_west.y // size


def centre_to_tablet(x_cm: float, y_cm: float) -> tuple[float, float]:
    """Robot centre in cm -> the tablet's decimal cell, whose (1, 1) is the centre of the start pose."""
    size = config.OBSTACLE_SIZE_CM
    return (x_cm - size / 2) / size, (y_cm - size / 2) / size


def rotate(points: list[tuple[float, float]], cx: float, cy: float, heading_deg: float) -> list[tuple[float, float]]:
    """
    Place local points around (cx, cy). Local +y is "forward" and local +x is the robot's
    right-hand side; heading is clockwise from north, so facing EAST sends forward to +x.
    """
    t = math.radians(heading_deg)
    s, c = math.sin(t), math.cos(t)
    return [(cx + dx * c + dy * s, cy - dx * s + dy * c) for dx, dy in points]


@dataclass(frozen=True)
class CarShapes:
    body: list[tuple[float, float]]
    wheels: list[list[tuple[float, float]]]
    camera: tuple[float, float, float]


def car_shapes(cx_cm: float, cy_cm: float, direction: Direction) -> CarShapes:
    """The top-down car at a pose, in arena cm: chamfered body, four wheels, camera dot at the front."""
    w, l = config.ROBOT_BODY_CM
    hw, hl, ch = w / 2, l / 2, 2.0          # half width, half length, corner chamfer
    body = [(-hw + ch, hl), (hw - ch, hl), (hw, hl - ch), (hw, -hl + ch),
            (hw - ch, -hl), (-hw + ch, -hl), (-hw, -hl + ch), (-hw, hl - ch)]
    ww, wl = 3.0, 6.0                       # wheel width and length
    wheels = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            x, y = sx * (hw + ww / 2 - 0.5), sy * (hl - wl / 2 - 2)
            wheels.append([(x - ww / 2, y + wl / 2), (x + ww / 2, y + wl / 2),
                           (x + ww / 2, y - wl / 2), (x - ww / 2, y - wl / 2)])
    heading = HEADING_DEG[direction]
    (camx, camy), = rotate([(0, hl - 2.5)], cx_cm, cy_cm, heading)
    return CarShapes(
        body=rotate(body, cx_cm, cy_cm, heading),
        wheels=[rotate(q, cx_cm, cy_cm, heading) for q in wheels],
        camera=(camx, camy, 2.0),
    )
