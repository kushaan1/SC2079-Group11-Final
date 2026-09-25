# Derived from Pante/SC2079 (AY2023 S2, Group 14). See algorithm/PROVENANCE.md
from __future__ import annotations

from dataclasses import dataclass
from math import atan2, ceil, copysign, cos, degrees, floor, hypot, radians, sin

import numpy as np

import config
from pathfinding.search.instructions import TurnInstruction
from pathfinding.world.primitives import Direction, Vector
from pathfinding.world.world import World


@dataclass(frozen=True, eq=False)
class _Arc:
    """
    One turn's shape, as offsets from the starting cell.

    Every coordinate :func:`__frame` produces is the starting cell plus a constant, so a turn's
    arc is the same set of offsets wherever it starts: only ``(direction, instruction, the
    measured pair)`` change its shape. That is what makes the shape cacheable and the check a
    translation. The robot's planning footprint is NOT in the key any more: the pivot point is
    measured, not derived from the box, so a 21 cm and a 31 cm robot trace the same arc.

    :param direction: The post-turn facing, shared by every cell of the arc and the end pose.
    :param cells: The rear point's arc in driving order, consecutive duplicates dropped.
        Collision-checked.
    :param xs: ``cells``' x offsets, for the vectorised check.
    :param ys: ``cells``' y offsets.
    :param box: ``cells``' ``(min x, max x, min y, max y)``. Most turns the search tries are
        rejected, and this rejects the ones that leave the arena for four integer comparisons.
    :param end: The end pose's offset: the tape's displacement, rounded. Appended to the path
        but NOT collision-checked, as it never was.
    """

    # eq=False so this compares and hashes by identity: a generated __eq__ over the numpy
    # fields would raise "truth value of an array is ambiguous".
    direction: Direction
    cells: tuple[tuple[int, int], ...]
    xs: np.ndarray
    ys: np.ndarray
    box: tuple[int, int, int, int]
    end: tuple[int, int]


# Keyed by everything a turn's shape depends on, so a runtime change to the measured pair lands
# on a fresh key instead of reusing a stale arc. Bounded by 8 directions x 8 instructions x
# however many pairs one process plans with.
_ARCS: dict[tuple, _Arc] = {}

# Which side of the robot the turning circle sits on. The steering lock decides it, not the
# direction of travel, so forward-left and backward-left share a side.
_LEFT_LOCK = ('FORWARD_LEFT', 'BACKWARD_LEFT')

# The two locks that swing the nose anticlockwise. Reversing with the wheel held left swings
# the nose right, which is why the backward pair are mirrored.
_ANTICLOCKWISE = ('FORWARD_LEFT', 'BACKWARD_RIGHT')


def __turned(instruction: TurnInstruction) -> int:
    """How far this turn swings the compass heading, signed clockwise."""
    magnitude = instruction.degrees
    return -magnitude if instruction.lock in _ANTICLOCKWISE else magnitude


def __round(value: float) -> int:
    """
    Round half AWAY FROM ZERO, after snapping float noise off the value.

    One rule for every tape half, whichever way the car faces, so that a command's end offset
    from one heading is the mirror image of its end offset from the opposite one. ``round()``
    rounds half to even, which would put a 15.5 cm end at 16 and a 4.5 at 4. Half UP is not
    mirror-symmetric: it rounds 21.5 to 22 but -21.5 to -21, so the same command would end a
    centimetre shorter from one heading than from its opposite. Away from zero treats both signs
    alike. The snap is what leaves the sign as the only difference: ``Direction.unit`` is the
    sine and cosine of the heading, and cos 90 is 6e-17 rather than 0, so an exact tape half can
    arrive here a hair either side of itself depending on the heading. Nine decimals is far
    below a cell and far above that noise. The arc cells go through here too, so a turn's shape
    follows the same rule as its end.
    """
    value = round(value, 9)
    return int(copysign(floor(abs(value) + 0.5), value))


def turn(world: World, start: Vector, instruction: TurnInstruction) -> list[Vector] | None:
    """
    Performs a turn.

    The arc's shape is computed once per ``(direction, instruction, measured pair)`` and cached
    as offsets; a call translates those offsets by ``start``, rejects the arc outright if its
    bounding box leaves the arena, and otherwise reads every cell of it in one numpy operation.

    The cells are the REAR PIVOT's path - what the planner has always collision-checked - and
    the last vector is the robot CENTRE's end pose, which comes from the tape measurement in
    ``config.TURN_DISPLACEMENT_CM`` and not from the circle (see :func:`__frame`).

    :param world: The world. Only ``cell_size`` and ``contains_all`` are read.
    :param start: The initial vector, the robot's centre.
    :param instruction: The turn instruction.
    :return: The path of the turn if it is legal, otherwise None.
    """
    cell_size = world.cell_size
    across, along = instruction.displacement(cell_size)
    key = (start.direction, instruction, across, along)

    try:
        arc = _ARCS[key]
    except KeyError:
        arc = _ARCS[key] = __arc(start.direction, instruction, cell_size)

    x, y = start.x, start.y

    # One check for the whole arc; nothing observes which cell failed.
    if not world.contains_all(arc.xs, arc.ys, arc.box, x, y):
        return None

    direction = arc.direction
    path = [Vector(direction, x + dx, y + dy) for dx, dy in arc.cells]
    end_x, end_y = x + arc.end[0], y + arc.end[1]
    # The end pose is dropped when the arc already finishes on that cell, as before.
    if not path or (path[-1].x, path[-1].y) != (end_x, end_y):
        path.append(Vector(direction, end_x, end_y))
    return path


def centre_arc(start: Vector, instruction: TurnInstruction, cell_size: int) -> list[tuple[float, float]]:
    """
    The robot CENTRE's path through this turn, in cells, in driving order.

    ``start`` itself is excluded; the last point is exactly the unrounded end offset added to
    ``start``, the same displacement :func:`turn` rounds into the end pose. The centre rides a
    circle of radius ``hypot(radius, lead)`` about the same instantaneous centre of rotation the
    rear pivot rides, and the points are spaced so that consecutive ones are at most
    ``config.CENTRE_PATH_SPACING_CM`` apart (read at call time). Sampling at 0.7 of that spacing
    keeps the bound even after the caller rounds each point to a whole cell, but only because a
    cell is 1 cm, the only cell size this planner runs at; on a coarser grid the caller would
    have to round in centimetres instead. Geometry only: nothing here asks whether the turn is
    legal, so the caller checks that with :func:`turn` first.

    This is what the response's ``centre_path`` is built from. The rear-point ``path`` cells are
    the wrong thing to draw a route from: they sit ``lead`` behind the car.
    """
    frame = __frame(start.direction, instruction, cell_size)
    icr_x, icr_y, swept, end_x, end_y = frame.icr_x, frame.icr_y, frame.swept, frame.end_x, frame.end_y

    # The centre's own radius: the lead runs along the heading and the rear pivot's radius across
    # it, so this is also the distance from the start centre to the ICR.
    radius = hypot(frame.radius, frame.lead)
    starts = degrees(atan2(-icr_y, -icr_x))
    # Aim under the limit: the caller rounds both ends of every gap to whole cells, which can
    # stretch a gap by up to sqrt(2) cells, so 0.7 of the spacing keeps the ROUNDED points
    # inside it (3.5 + 1.41 < 5 at the default).
    spacing = 0.7 * config.CENTRE_PATH_SPACING_CM / cell_size
    steps = max(1, ceil(radius * abs(radians(swept)) / spacing))

    points = [
        (start.x + icr_x + radius * cos(radians(starts + swept * k / steps)),
         start.y + icr_y + radius * sin(radians(starts + swept * k / steps)))
        for k in range(1, steps)
    ]
    points.append((start.x + end_x, start.y + end_y))
    return points


@dataclass(frozen=True)
class _Frame:
    """The turn's geometry at the origin: where the rear pivot starts, where it circles, how far, and where the centre ends."""

    radius: float
    lead: float
    rear_x: float
    rear_y: float
    icr_x: float
    icr_y: float
    swept: float          # degrees, maths sense (anticlockwise positive)
    end_x: float          # the CENTRE's end offset, unrounded, straight from the tape
    end_y: float
    end_direction: Direction


def __frame(direction: Direction, instruction: TurnInstruction, cell_size: int) -> _Frame:
    """
    One statement of the manoeuvre, serving eight headings and eight commands.

    * the rear pivot - the midpoint of the rear axle - sits ``lead`` cells BEHIND the centre;
    * the car rotates about the instantaneous centre of rotation, ICR, a point on the LINE of
      the rear axle ``radius`` to the left or right of the rear pivot, chosen by the steering
      lock, which is why forward-left and backward-left share a side;
    * the rear pivot rides the circle of ``radius`` about the ICR through the angle the robot
      turns through;
    * the centre ENDS where the tape says it does: ``across`` toward the steering side and
      ``along`` along the start heading. :meth:`TurnInstruction.fit` chose ``radius`` and
      ``lead`` precisely so that the circle lands the centre there too, so the arc and the end
      pose agree analytically, and pinning the pose to the measurement rather than to the
      circle means no rounding inside the arc can move where the car is planned to stop.

    Angles are maths angles, anticlockwise from the x axis, which is why the compass delta is
    negated. Every coordinate is the start plus a constant, which is why :func:`__arc` can
    evaluate this at the origin once and translate the result.
    """
    radius, lead = instruction.fit(cell_size)
    across, along = instruction.displacement(cell_size)
    ux, uy = direction.unit

    # Left of the heading is (-uy, ux); right is its negation.
    side_x, side_y = (-uy, ux) if instruction.lock in _LEFT_LOCK else (uy, -ux)

    rear_x, rear_y = -lead * ux, -lead * uy
    icr_x, icr_y = rear_x + radius * side_x, rear_y + radius * side_y

    turned = __turned(instruction)
    return _Frame(
        radius, lead, rear_x, rear_y, icr_x, icr_y, -turned,
        across * side_x + along * ux, across * side_y + along * uy,
        Direction.of_degrees(direction.degrees + turned),
    )


def __arc(direction: Direction, instruction: TurnInstruction, cell_size: int) -> _Arc:
    """Builds one cache entry: the rear point's arc as offsets from the starting cell."""
    frame = __frame(direction, instruction, cell_size)

    starts = degrees(atan2(frame.rear_y - frame.icr_y, frame.rear_x - frame.icr_x))
    cells = __sampled(frame.icr_x, frame.icr_y, frame.radius, starts, frame.swept)

    xs = [cell[0] for cell in cells]
    ys = [cell[1] for cell in cells]

    return _Arc(
        frame.end_direction,
        cells,
        np.array(xs),
        np.array(ys),
        (min(xs), max(xs), min(ys), max(ys)),
        (__round(frame.end_x), __round(frame.end_y)),
    )


def __sampled(
    centre_x: float, centre_y: float, turning_radius: float, starts: float, swept: float
) -> tuple[tuple[int, int], ...]:
    """
    An arc walked in driving order at half-cell steps, rounded to cells, duplicates dropped.

    Half a cell rather than one: two points at most half a cell apart round to cells at most one
    apart on each axis, so the result is always 8-connected, which the per-cell grid read
    relies on to cover the circle without gaps. (Points a whole cell apart can round two cells
    apart when both sit on a half.) The midpoint-circle walk this replaces only knew
    axis-aligned quarter circles; this serves every heading and both turn sizes alike.
    """
    steps = max(1, ceil(2 * abs(radians(swept)) * turning_radius))
    cells: list[tuple[int, int]] = []
    for step in range(steps + 1):
        angle = radians(starts + swept * step / steps)
        cell = (__round(centre_x + turning_radius * cos(angle)),
                __round(centre_y + turning_radius * sin(angle)))
        if not cells or cell != cells[-1]:
            cells.append(cell)
    return tuple(cells)
