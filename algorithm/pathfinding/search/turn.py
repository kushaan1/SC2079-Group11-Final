# Derived from Pante/SC2079 (AY2023 S2, Group 14). See algorithm/PROVENANCE.md
from __future__ import annotations

from dataclasses import dataclass
from math import atan2, ceil, cos, degrees, radians, sin

import numpy as np

import config
from pathfinding.search.instructions import TurnInstruction
from pathfinding.world.primitives import Direction, Vector
from pathfinding.world.world import World, Robot


@dataclass(frozen=True, eq=False)
class _Arc:
    """
    One turn's shape, as offsets from the starting cell.

    Every expression in :func:`__geometry` is the starting cell plus a constant, so a turn's
    arc is the same set of offsets wherever it starts: only ``(direction, instruction,
    turning_radius, offset, robot extents)`` change its shape, and those are fixed for a
    world. That is what makes the shape cacheable and the check a translation.

    :param direction: The post-turn facing, shared by every cell of the arc and the end pose.
    :param cells: The arc's offsets in :func:`__offsets` order - the interleaved a, b pairs -
        used to rebuild the returned vectors. Collision-checked.
    :param xs: ``cells``' x offsets, for the vectorised check.
    :param ys: ``cells``' y offsets.
    :param box: ``cells``' ``(min x, max x, min y, max y)``. Most turns the search tries are
        rejected, and this rejects the ones that leave the arena for four integer
        comparisons, without touching numpy at all.
    :param end: The end pose's offset. Appended to the path but NOT collision-checked, which
        is what the Python loop did.
    """

    # eq=False above so this compares and hashes by identity: a generated __eq__ over the
    # numpy fields would raise "truth value of an array is ambiguous" for anyone who tried.
    direction: Direction
    cells: tuple[tuple[int, int], ...]
    xs: np.ndarray
    ys: np.ndarray
    box: tuple[int, int, int, int]
    end: tuple[int, int]


# Keyed by everything a turn's shape depends on, so a new robot size or a runtime radius
# change lands on a fresh key instead of reusing a stale arc. Bounded by 4 directions x 4
# instructions x however many robot/radius combinations one process plans.
_ARCS: dict[tuple, _Arc | None] = {}

# Which side of the robot the turning circle sits on. The steering lock decides it, not the
# direction of travel, so forward-left and backward-left share a centre.
_LEFT_LOCK = ('FORWARD_LEFT', 'BACKWARD_LEFT')

# The two locks that swing the nose anticlockwise. Reversing with the wheel held left swings
# the nose right, which is why the backward pair are mirrored.
_ANTICLOCKWISE = ('FORWARD_LEFT', 'BACKWARD_RIGHT')


def __turned(instruction: TurnInstruction) -> int:
    """How far this turn swings the compass heading, signed clockwise."""
    magnitude = instruction.degrees
    return -magnitude if instruction.lock in _ANTICLOCKWISE else magnitude


# This turning function does not properly account for different points of the robot having different turning radii.
# I'm too lazy to fix it. The workaround is to ensure that the robot is an odd number of cells.
def turn(world: World, start: Vector, instruction: TurnInstruction) -> list[Vector] | None:
    """
    Performs a turn.

    The arc's shape is computed once per ``(direction, instruction, radius, offset, robot
    extents)`` and cached as offsets; a call translates those offsets by ``start``, rejects
    the arc outright if its bounding box leaves the arena, and otherwise reads every cell of
    it in one numpy operation. The returned list is identical, cell for cell and in the same
    order, to the per-cell Python loop this replaced - see ``tests/test_turn_cache.py``,
    which keeps that loop as its oracle and compares the two.

    :param world: The world.
    :param start: The initial vector.
    :param instruction: The turn instruction.
    :return: The path of the turn if it is legal, otherwise returns None.
    """

    # The turning radius (in grid cells), read from config on every call so that
    # freshly measured radii can be dropped in at runtime. Both numbers are part of the
    # cache key, so a config change at runtime invalidates the cached shape by itself.
    # cell_size is a property that reads config and divides; once is enough.
    cell_size = world.cell_size
    turning_radius = instruction.radius(cell_size)
    offset = config.TURN_PIVOT_OFFSET_CM // cell_size

    robot = world.robot
    key = (start.direction, instruction, turning_radius, offset,
           robot.north_length, robot.east_length, robot.south_length, robot.west_length)

    try:
        arc = _ARCS[key]
    except KeyError:
        arc = _ARCS[key] = __arc(start.direction, instruction, turning_radius, offset, robot)

    if arc is None:
        return None

    x, y = start.x, start.y

    # One check for the whole arc. The Python loop returned on the FIRST cell outside the
    # world, which is the same answer: nothing observes which cell failed.
    if not world.contains_all(arc.xs, arc.ys, arc.box, x, y):
        return None

    direction = arc.direction
    path = [Vector(direction, x + dx, y + dy) for dx, dy in arc.cells]
    end_x, end_y = x + arc.end[0], y + arc.end[1]
    # The end pose is dropped when the arc already finishes on that cell, which is what the
    # de-interleaving in the search used to do before arcs left this module as paths.
    if not path or (path[-1].x, path[-1].y) != (end_x, end_y):
        path.append(Vector(direction, end_x, end_y))
    return path


def __arc(
    direction: Direction,
    instruction: TurnInstruction,
    turning_radius: int,
    offset: int,
    robot: Robot,
) -> _Arc | None:
    """Builds one cache entry: the turn's cells as offsets from the starting cell."""
    geometry = __geometry(Vector(direction, 0, 0), instruction, turning_radius, offset, robot)
    if geometry is None:
        return None

    end, centre_x, centre_y, starts, swept, rear = geometry

    # The midpoint circle is kept for the quarter turns it was written for, so those arcs come
    # out cell for cell as they always have; everything else is sampled.
    if instruction.degrees == 90 and not direction.diagonal:
        drawn = __offsets(turning_radius, round(centre_x), round(centre_y), __quadrant(starts, swept))
        cells = __in_driving_order(drawn, rear)
    else:
        cells = __sampled(centre_x, centre_y, turning_radius, starts, swept)

    xs = [cell[0] for cell in cells]
    ys = [cell[1] for cell in cells]

    return _Arc(
        end.direction,
        cells,
        np.array(xs),
        np.array(ys),
        (min(xs), max(xs), min(ys), max(ys)),
        (end.x, end.y),
    )


def __geometry(
    start: Vector,
    instruction: TurnInstruction,
    turning_radius: int,
    offset: int,
    robot: Robot,
) -> tuple[Vector, float, float, float, float, tuple[int, int]] | None:
    """
    The turn's ``(end pose, centre x, centre y, start angle, swept angle, rear point)``.

    Derived rather than written out. The reference had sixteen hand-written cases, one per
    heading and turn type, and Fix 6 was a term in the wrong place in one of them that nothing
    else could catch. They are all the same manoeuvre seen from four headings, so this states
    it once, and it then serves eight headings and two turn sizes for free:

    * the robot pivots about a point ``lead`` cells BEHIND its centre, roughly the rear axle;
    * the turning circle's centre sits ``turning_radius`` to the left or right of that point,
      chosen by the steering lock, which is why forward-left and backward-left share a centre;
    * the rear point rides that circle through the same angle the robot turns through;
    * the new centre is ``lead`` ahead of where the rear point lands, along the new heading.

    Angles are maths angles, anticlockwise from the x axis, which is why the compass delta is
    negated. Every coordinate is ``start.x`` or ``start.y`` plus a constant, which is why
    :func:`__arc` can evaluate this at the origin once and translate the result.

    Assumes a square robot, so that one ``lead`` serves every heading. ``Entity`` asserts the
    corners are square and the parity bump keeps the extents equal, so that holds by
    construction.
    """
    lead = robot.south_length - offset
    ux, uy = start.direction.unit

    # The rear point: what actually rides the circle.
    rear_x = round(start.x - lead * ux)
    rear_y = round(start.y - lead * uy)

    # Left of the heading is (-uy, ux); right is its negation.
    side_x, side_y = (-uy, ux) if instruction.lock in _LEFT_LOCK else (uy, -ux)
    centre_x = rear_x + turning_radius * side_x
    centre_y = rear_y + turning_radius * side_y

    turned = __turned(instruction)
    swept = -turned
    end_direction = Direction.of_degrees(start.direction.degrees + turned)

    starts = degrees(atan2(rear_y - centre_y, rear_x - centre_x))
    finish = radians(starts + swept)
    end_x = centre_x + turning_radius * cos(finish)
    end_y = centre_y + turning_radius * sin(finish)

    fx, fy = end_direction.unit
    end = Vector(end_direction, round(end_x + lead * fx), round(end_y + lead * fy))

    return end, centre_x, centre_y, starts, swept, (rear_x, rear_y)


def __sampled(
    centre_x: float, centre_y: float, turning_radius: int, starts: float, swept: float
) -> tuple[tuple[int, int], ...]:
    """
    An arc walked in driving order, about one cell per step.

    The midpoint-circle walk below only knows axis-aligned quarters, so anything starting on a
    diagonal or sweeping 45 degrees is sampled instead. Consecutive duplicates are dropped, so
    the result is a path rather than a set.
    """
    steps = max(1, ceil(abs(radians(swept)) * turning_radius))
    cells: list[tuple[int, int]] = []
    for step in range(steps + 1):
        angle = radians(starts + swept * step / steps)
        cell = (round(centre_x + turning_radius * cos(angle)),
                round(centre_y + turning_radius * sin(angle)))
        if not cells or cell != cells[-1]:
            cells.append(cell)
    return tuple(cells)


def __in_driving_order(
    cells: tuple[tuple[int, int], ...], rear: tuple[int, int]
) -> tuple[tuple[int, int], ...]:
    """
    Put :func:`__offsets`' interleaved output into driving order.

    It fills the quarter from both ends at once, ``a0, b0, a1, b1, ...``, so the two halves are
    de-interleaved and joined at the 45 degree point, starting from whichever end is nearest
    the rear point the robot actually sets off from. Doing it here rather than in the search
    means every arc leaves this module as a path, whichever way it was drawn.
    """
    a, b = list(cells[0::2]), list(cells[1::2])
    forward = a + b[::-1]
    backward = b + a[::-1]

    def gap(cell: tuple[int, int]) -> int:
        return abs(cell[0] - rear[0]) + abs(cell[1] - rear[1])

    ordered = forward if gap(forward[0]) <= gap(backward[0]) else backward

    walked: list[tuple[int, int]] = []
    for cell in ordered:
        if not walked or cell != walked[-1]:
            walked.append(cell)
    return tuple(walked)


def __quadrant(starts: float, swept: float) -> int:
    """
    Which quarter of the circle an axis-aligned arc lies in, in :func:`__offsets`' numbering.
    """
    return (int(min(round(starts), round(starts + swept)) // 90) % 4) + 1


def __offsets(turning_radius: int, centre_x: int, centre_y: int, quadrant: int) -> tuple[tuple[int, int], ...]:
    """
    Uses a modified Midpoint circle algorithm to determine the curved path of a robot when turning.

    The reference walked this circle on every expansion of the search and called
    ``world.contains`` on each cell as it went; this is the same walk, run once per cache key
    and with no world to check against, so the cells come out in exactly the order the
    reference appended them - a0, b0, a1, b1, ... - and may still contain duplicates.
    ``search._ordered_arc`` de-interleaves them, so that order is load-bearing.

    :param centre_x: The centre of the turning radius's x value.
    :param centre_y: The centre of the turning radius's y value.
    :param quadrant: The quadrant of the circle.
        Quadrants:
              2 | 1
            ----+----
              3 | 4
    :return: the cells in the curve, may contain duplicates
    """
    assert 1 <= quadrant <= 4

    x = turning_radius
    y = 0
    err = 0

    # The original Midpoint circle algorithm fills in quadrants from two extremes. We store them in separate lists to
    # ensure an ordered list of vectors starting from the starting vector is returned.
    cells: list[tuple[int, int]] = []
    a_map = None
    b_map = None

    match quadrant:
        case 1:
            a_map = lambda _x, _y: (centre_x + _x, centre_y + _y)
            b_map = lambda _x, _y: (centre_x + _y, centre_y + _x)
        case 2:
            a_map = lambda _x, _y: (centre_x - _y, centre_y + _x)
            b_map = lambda _x, _y: (centre_x - _x, centre_y + _y)
        case 3:
            a_map = lambda _x, _y: (centre_x - _x, centre_y - _y)
            b_map = lambda _x, _y: (centre_x - _y, centre_y - _x)
        case 4:
            a_map = lambda _x, _y: (centre_x + _y, centre_y - _x)
            b_map = lambda _x, _y: (centre_x + _x, centre_y - _y)

    while x >= y:
        cells.append(a_map(x, y))
        cells.append(b_map(x, y))

        y += 1
        err += 1 + 2 * y
        if 2 * (err - x) + 1 > 0:
            x -= 1
            err += 1 - 2 * x

    return tuple(cells)
