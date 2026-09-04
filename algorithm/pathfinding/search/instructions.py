# Derived from Pante/SC2079 (AY2023 S2, Group 14). See algorithm/PROVENANCE.md
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import radians

from pydantic import BaseModel, Field

import config
from pathfinding.world.primitives import Vector


class MiscInstruction(str, Enum):
    CAPTURE_IMAGE = 'CAPTURE_IMAGE'


class MoveInstruction(BaseModel):
    move: Straight
    amount: int = Field(
        ge=1, description="The amount to move the robot in centimetres."
    )


@dataclass
class Move:
    move: Straight
    vectors: list[Vector]


class Straight(str, Enum):
    FORWARD = 'FORWARD'
    BACKWARD = 'BACKWARD'


class TurnInstruction(str, Enum):
    """
    A turn. The bare names are the original quarter turns; the ``_45`` variants are the same
    steering lock held for half as long, so they share a radius and cost half the arc.
    """

    FORWARD_LEFT = 'FORWARD_LEFT'
    FORWARD_RIGHT = 'FORWARD_RIGHT'
    BACKWARD_LEFT = 'BACKWARD_LEFT'
    BACKWARD_RIGHT = 'BACKWARD_RIGHT'
    FORWARD_LEFT_45 = 'FORWARD_LEFT_45'
    FORWARD_RIGHT_45 = 'FORWARD_RIGHT_45'
    BACKWARD_LEFT_45 = 'BACKWARD_LEFT_45'
    BACKWARD_RIGHT_45 = 'BACKWARD_RIGHT_45'

    @property
    def degrees(self) -> int:
        """How far this turn swings the robot."""
        return 45 if self.value.endswith('_45') else 90

    @property
    def lock(self) -> str:
        """The steering lock, which is what decides the radius. Both variants share one."""
        return self.value.removesuffix('_45')

    def radius(self, cell_size: int) -> int:
        """
        The turning radius (in grid cells). The turning radius is different for each direction.

        Call-time config rule: the radii are read from ``config.TURN_RADIUS_CM`` on every call,
        so a caller may drop in freshly measured values at runtime without touching this module.

        :param cell_size: the cell size
        :return: the turning radius in grid cells.
        """
        return config.TURN_RADIUS_CM[self.lock] // cell_size

    def arc_length(self, cell_size: int) -> int:
        return round(self.radius(cell_size) * radians(self.degrees))


@dataclass
class Turn:
    turn: TurnInstruction
    vectors: list[Vector]
