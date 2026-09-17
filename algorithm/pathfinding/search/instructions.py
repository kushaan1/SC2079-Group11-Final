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


class PivotInstruction(str, Enum):
    """
    A pivot: rotating close to on the spot by shuffling - full steering lock forward, full lock
    back the other way, repeated, both strokes swinging the nose the same way.

    Deliberately NOT members of :class:`TurnInstruction`, though a pivot is built out of turn
    strokes. ``segment._TURNS`` is ``tuple(TurnInstruction)`` and the four-heading planner takes
    ``tuple(t for t in _TURNS if t.degrees == 90)`` out of it, so a ``PIVOT_*_90`` living in that
    enum would be swept up by that filter and would change every route the service ships today,
    with the pivot flag still off. Keeping the two enums apart is what makes this feature
    additive.

    The values are the wire tokens and they are PLACEHOLDERS: the RPi and STM owners have not
    settled what the firmware expects, and changing them is an edit to this block and nothing
    else.
    """

    PIVOT_LEFT_45 = 'PIVOT_LEFT_45'
    PIVOT_RIGHT_45 = 'PIVOT_RIGHT_45'
    PIVOT_LEFT_90 = 'PIVOT_LEFT_90'
    PIVOT_RIGHT_90 = 'PIVOT_RIGHT_90'

    @property
    def degrees(self) -> int:
        """
        How far this pivot swings the robot.

        Read off the suffix rather than tabulated, so that a token added to the enum cannot
        disagree with its own name - unlike :class:`TurnInstruction`, every pivot names its own
        size, so there is no default to fall through to.
        """
        return int(self.value.rsplit('_', 1)[1])

    @property
    def clockwise(self) -> bool:
        """
        Which way the nose swings. RIGHT is clockwise.

        The sense is the strokes', not a separate convention: a LEFT pivot alternates exactly
        the pair ``turn._ANTICLOCKWISE`` names (forward-left, backward-right), and a RIGHT one
        alternates the two locks absent from it.
        """
        return '_RIGHT_' in self.value

    def strokes(self) -> int:
        """
        How many shuffle strokes this pivot is driven as. Always even: one back per forward.

        A method rather than a property because it reads config, and, like
        :meth:`TurnInstruction.radius`, it reads it on EVERY call. The stroke count is the STM
        owner's to set once the firmware's shuffle is settled; binding it at import would freeze
        the geometry at whatever this module happened to load with.
        """
        return config.PIVOT_STROKES_PER_45 * self.degrees // 45


@dataclass
class Pivot:
    """One pivot, as the search emits it: the cells it sweeps, with the end pose last."""

    pivot: PivotInstruction
    vectors: list[Vector]
