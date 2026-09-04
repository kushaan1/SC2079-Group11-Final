# Derived from Pante/SC2079 (AY2023 S2, Group 14). See algorithm/PROVENANCE.md
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import math


@dataclass(eq=True, unsafe_hash=True, order=True)
class Vector:
    direction: Direction
    x: int
    y: int


@dataclass(frozen=True)
class Point:
    x: int
    y: int


class Direction(str, Enum):
    """
    A heading. The four cardinals are the only ones an obstacle face or a start pose may take;
    the diagonals exist so the search can drive and turn through them.
    """

    NORTH = 'NORTH'
    NORTHEAST = 'NORTHEAST'
    EAST = 'EAST'
    SOUTHEAST = 'SOUTHEAST'
    SOUTH = 'SOUTH'
    SOUTHWEST = 'SOUTHWEST'
    WEST = 'WEST'
    NORTHWEST = 'NORTHWEST'

    @property
    def degrees(self) -> int:
        """Compass heading in degrees, clockwise from north."""
        return _DEGREES[self]

    @property
    def step(self) -> tuple[int, int]:
        """One cell along this heading. A diagonal step moves on both axes, so it is 1.41 cm."""
        return _STEPS[self]

    @property
    def unit(self) -> tuple[float, float]:
        """The true unit vector, for placing a point a measured distance along the heading."""
        return _UNITS[self]

    @property
    def diagonal(self) -> bool:
        return self.degrees % 90 != 0

    @classmethod
    def of_degrees(cls, degrees: float) -> Direction:
        """The heading at that compass angle, to the nearest eighth. Wraps, so 450 is east."""
        return _BY_DEGREES[round(degrees / 45) * 45 % 360]


_DEGREES: dict[Direction, int] = {
    Direction.NORTH: 0,
    Direction.NORTHEAST: 45,
    Direction.EAST: 90,
    Direction.SOUTHEAST: 135,
    Direction.SOUTH: 180,
    Direction.SOUTHWEST: 225,
    Direction.WEST: 270,
    Direction.NORTHWEST: 315,
}

_STEPS: dict[Direction, tuple[int, int]] = {
    Direction.NORTH: (0, 1),
    Direction.NORTHEAST: (1, 1),
    Direction.EAST: (1, 0),
    Direction.SOUTHEAST: (1, -1),
    Direction.SOUTH: (0, -1),
    Direction.SOUTHWEST: (-1, -1),
    Direction.WEST: (-1, 0),
    Direction.NORTHWEST: (-1, 1),
}

_UNITS: dict[Direction, tuple[float, float]] = {
    d: (math.sin(math.radians(a)), math.cos(math.radians(a))) for d, a in _DEGREES.items()
}

_BY_DEGREES: dict[int, Direction] = {angle: d for d, angle in _DEGREES.items()}
