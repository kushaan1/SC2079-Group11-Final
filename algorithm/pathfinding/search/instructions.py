# Derived from Pante/SC2079 (AY2023 S2, Group 14). See algorithm/PROVENANCE.md
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import cos, radians, sin

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
    A turn. The bare names are the quarter turns; the ``_45`` variants are the same steering
    lock commanded for 45 degrees. Every one of the eight is calibrated on its own from
    ``config.TURN_DISPLACEMENT_CM``: a 45 is NOT half a 90, and neither is derived from the
    other in either direction, because the car was measured doing each one.
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
        """The steering lock, which decides which side the turning circle sits on."""
        return self.value.removesuffix('_45')

    @property
    def forward(self) -> bool:
        """Whether the wheels drive forward through this turn. Decides which way the centre trails the pivot."""
        return self.value.startswith('FORWARD')

    def displacement(self, cell_size: int) -> tuple[float, float]:
        """
        ``(across, along)``: how far the robot centre moves in one of these, in grid cells.

        Call-time config rule: read from ``config.TURN_DISPLACEMENT_CM`` on every call, so the
        STM owner can drop in a fresh tape measurement at runtime. Across is toward the steering
        side, along is along the starting heading and negative for a backward command - see the
        table's own comment for the convention.
        """
        across, along = config.TURN_DISPLACEMENT_CM[self.value]
        return across / cell_size, along / cell_size

    def fit(self, cell_size: int) -> tuple[float, float]:
        """
        The rear-pivot model's two parameters for this command, ``(radius, lead)`` in cells.

        The car rotates about a point on the LINE of its rear axle, the instantaneous centre of
        rotation. The rear axle's midpoint - the rear pivot - rides a circle of ``radius`` about
        it, and the centre sits ``lead`` ahead of the rear pivot, so after a turn through
        ``theta`` the centre has moved, with ``s = sin(theta)`` and ``c = 1 - cos(theta)``::

            forward:   across = R*c + L*s      along  = R*s - L*c
            backward:  across = R*c - L*s      -along = R*s + L*c

        Two equations, two unknowns, solved here and nowhere else. The pair comes from the tape,
        so the end pose the geometry builds from this fit reproduces the measurement by
        construction; a chord alone could not have separated R from L, which is why the old
        one-number tables were wrong by the whole lead. Each command is fitted on its own - the
        eight leads come out 7-14 cm, one chassis property seen through tape noise and the
        steering transient - and keeping them separate is what makes every end pose exact.
        """
        across, along = self.displacement(cell_size)
        theta = radians(self.degrees)
        s, c = sin(theta), 1 - cos(theta)
        det = s * s + c * c
        if self.forward:
            radius = (across * c + along * s) / det
            lead = (across * s - along * c) / det
        else:
            back = -along
            radius = (across * c + back * s) / det
            lead = (back * c - across * s) / det
        return radius, lead

    def radius(self, cell_size: int) -> float:
        """The turning radius of the rear pivot, in grid cells, from :meth:`fit`. Every consumer of a
        turn's radius - the traced arc, ``arc_length``, both cost models, the pivot shuffle - reads this."""
        return self.fit(cell_size)[0]

    def lead(self, cell_size: int) -> float:
        """How far ahead of the rear pivot the robot centre sits, in grid cells, from :meth:`fit`."""
        return self.fit(cell_size)[1]

    def arc_length(self, cell_size: int) -> int:
        """The ground the rear pivot covers, in cells: what the distance model charges for a turn."""
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
