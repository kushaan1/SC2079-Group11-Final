# Derived from Pante/SC2079 (AY2023 S2, Group 14). See algorithm/PROVENANCE.md
from __future__ import annotations

from dataclasses import dataclass

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
    path.append(Vector(direction, x + arc.end[0], y + arc.end[1]))
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

    end, centre_x, centre_y, quadrant = geometry
    cells = __offsets(turning_radius, centre_x, centre_y, quadrant)
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
) -> tuple[Vector, int, int, int] | None:
    """
    The turn's ``(end pose, centre_x, centre_y, quadrant)``, or None if there is no such turn.

    The sixteen cases are the reference's, unchanged; only the ``__curve`` call they used to
    make has become the tuple it was going to be called with. Every coordinate here is
    ``start.x`` or ``start.y`` plus a constant, which is why :func:`__arc` can evaluate this
    at the origin once and translate the result.
    """
    match (start.direction, instruction):
        # y facing north
        case (Direction.NORTH, TurnInstruction.FORWARD_LEFT):
            x = start.x
            y = start.y - robot.south_length + offset
            return (
                Vector(
                    Direction.WEST,
                    x - turning_radius - robot.east_length + offset,
                    y + turning_radius,
                ),
                x - turning_radius,
                y,
                1,
            )

        case (Direction.NORTH, TurnInstruction.FORWARD_RIGHT):
            x = start.x
            y = start.y - robot.south_length + offset
            return (
                Vector(
                    Direction.EAST,
                    x + turning_radius + robot.west_length - offset,
                    y + turning_radius,
                ),
                x + turning_radius,
                y,
                2,
            )

        case (Direction.NORTH, TurnInstruction.BACKWARD_LEFT):
            x = start.x
            y = start.y - robot.south_length + offset
            return (
                Vector(
                    Direction.EAST,
                    x - turning_radius + robot.west_length - offset,
                    y - turning_radius,
                ),
                x - turning_radius,
                y,
                4,
            )

        case (Direction.NORTH, TurnInstruction.BACKWARD_RIGHT):
            x = start.x
            y = start.y - robot.south_length + offset
            return (
                Vector(
                    Direction.WEST,
                    x + turning_radius - robot.west_length + offset,
                    y - turning_radius,
                ),
                x + turning_radius,
                y,
                3,
            )

        # y facing east
        case (Direction.EAST, TurnInstruction.FORWARD_LEFT):
            x = start.x - robot.west_length + offset
            y = start.y
            return (
                Vector(
                    Direction.NORTH,
                    x + turning_radius,
                    y + turning_radius + robot.south_length - offset,
                ),
                x,
                y + turning_radius,
                4,
            )

        case (Direction.EAST, TurnInstruction.FORWARD_RIGHT):
            x = start.x - robot.west_length + offset
            y = start.y
            return (
                Vector(
                    Direction.SOUTH,
                    x + turning_radius,
                    y - turning_radius - robot.north_length + offset,
                ),
                x,
                y - turning_radius,
                1,
            )

        case (Direction.EAST, TurnInstruction.BACKWARD_LEFT):
            x = start.x - robot.west_length + offset
            y = start.y
            return (
                Vector(
                    Direction.SOUTH,
                    x - turning_radius,
                    y + turning_radius - robot.north_length + offset,
                ),
                x,
                y + turning_radius,
                3,
            )

        # Fix 6: the reference put the robot-extent term on the circle centre instead of the end
        # pose, so this arc was checked 12 cm off and the post-turn pose was wrong by 12 cm.
        # Now mirrors (EAST, BACKWARD_LEFT).
        case (Direction.EAST, TurnInstruction.BACKWARD_RIGHT):
            x = start.x - robot.west_length + offset
            y = start.y
            return (
                Vector(
                    Direction.NORTH,
                    x - turning_radius,
                    y - turning_radius + robot.south_length - offset,
                ),
                x,
                y - turning_radius,
                2,
            )

        # y facing south
        case (Direction.SOUTH, TurnInstruction.FORWARD_LEFT):
            x = start.x
            y = start.y + robot.north_length - offset
            return (
                Vector(
                    Direction.EAST,
                    x + turning_radius + robot.west_length - offset,
                    y - turning_radius,
                ),
                x + turning_radius,
                y,
                3,
            )

        case (Direction.SOUTH, TurnInstruction.FORWARD_RIGHT):
            x = start.x
            y = start.y + robot.north_length - offset
            return (
                Vector(
                    Direction.WEST,
                    x - turning_radius - robot.east_length + offset,
                    y - turning_radius,
                ),
                x - turning_radius,
                y,
                4,
            )

        case (Direction.SOUTH, TurnInstruction.BACKWARD_LEFT):
            x = start.x
            y = start.y + robot.north_length - offset
            return (
                Vector(
                    Direction.WEST,
                    x + turning_radius - robot.east_length + offset,
                    y + turning_radius,
                ),
                x + turning_radius,
                y,
                2,
            )

        case (Direction.SOUTH, TurnInstruction.BACKWARD_RIGHT):
            x = start.x
            y = start.y + robot.north_length - offset
            return (
                Vector(
                    Direction.EAST,
                    x - turning_radius + robot.west_length - offset,
                    y + turning_radius,
                ),
                x - turning_radius,
                y,
                1,
            )

        # y facing west
        case (Direction.WEST, TurnInstruction.FORWARD_LEFT):
            x = start.x + robot.east_length - offset
            y = start.y
            return (
                Vector(
                    Direction.SOUTH,
                    x - turning_radius,
                    y - turning_radius - robot.north_length + offset,
                ),
                x,
                y - turning_radius,
                2,
            )

        case (Direction.WEST, TurnInstruction.FORWARD_RIGHT):
            x = start.x + robot.east_length - offset
            y = start.y
            return (
                Vector(
                    Direction.NORTH,
                    x - turning_radius,
                    y + turning_radius + robot.south_length - offset,
                ),
                x,
                y + turning_radius,
                3,
            )

        case (Direction.WEST, TurnInstruction.BACKWARD_LEFT):
            x = start.x + robot.east_length - offset
            y = start.y
            return (
                Vector(
                    Direction.NORTH,
                    x + turning_radius,
                    y - turning_radius + robot.south_length - offset,
                ),
                x,
                y - turning_radius,
                1,
            )

        case (Direction.WEST, TurnInstruction.BACKWARD_RIGHT):
            x = start.x + robot.east_length - offset
            y = start.y
            return (
                Vector(
                    Direction.SOUTH,
                    x + turning_radius,
                    y + turning_radius - robot.north_length + offset,
                ),
                x,
                y + turning_radius,
                4,
            )


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
