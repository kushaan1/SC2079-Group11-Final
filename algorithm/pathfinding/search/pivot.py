# Derived from Pante/SC2079 (AY2023 S2, Group 14). See algorithm/PROVENANCE.md
"""
The pivot: turning on the spot, for a car that cannot.

The chassis is Ackermann-steered and has no zero-radius solution, so "on the spot" is driven as
a SHUFFLE - full steering lock forward, full lock back the other way, repeated - with both
strokes swinging the nose the same way. The rotations add; the translations, being one forward
and one back, very nearly cancel. What is left over is a few centimetres of drift, and that
drift is INHERENT, not a defect waiting to be tuned out: the two strokes of a pair turn about
two circles that are not concentric, so the pair does not close. Matching the forward and
backward radii buys about 12% of it - 3.52 cm per 45 degrees at the placeholder 40/37 against
3.09 cm at a matched 40/40 - and no more. What the planner needs from it is only that it is
systematic rather than noise, which is why this module can model it exactly instead of padding
for it.

This module is `turn.py` applied to that compound manoeuvre, and it is deliberately the same
shape: one derivation of the geometry, cached as offsets from the origin, rejected on a
bounding box, then checked in a single numpy read and translated. The difference worth knowing
about is in :func:`__shuffle`: a turn ends on a heading the `Direction` enum names, but a
pivot PASSES THROUGH headings it does not - 22.5 degrees at the default stroke count - so the
derivation carries the heading as a float and resolves it to a `Direction` only at the end.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import atan2, ceil, cos, degrees, radians, sin

import numpy as np

import config
from pathfinding.search.instructions import PivotInstruction, TurnInstruction
from pathfinding.search.turn import _ANTICLOCKWISE, _LEFT_LOCK
from pathfinding.world.primitives import Direction, Vector
from pathfinding.world.world import World, Robot


@dataclass(frozen=True, eq=False)
class _Shuffle:
    """
    One pivot's shape, as offsets from the starting cell.

    Cacheable for the reason :class:`~pathfinding.search.turn._Arc` is: every coordinate
    :func:`__shuffle` produces is the starting cell plus a constant, so the shape depends only
    on ``(direction, instruction, both radii, offset, stroke count, robot extents)`` and a call
    is a translation. A pivot's shape is dearer to derive than an arc's - it is several strokes
    of sampled arc rather than one - which makes the cache worth more here, not less.

    :param direction: The post-pivot facing, shared by every cell and the end pose. The heading
        genuinely sweeps through the manoeuvre, but ``Vector`` has nowhere to put a heading the
        enum cannot name, so this mirrors what ``turn()`` does with an arc and leaves the sweep
        to the simulator, which interpolates it across the cells.
    :param cells: The cells the robot's CENTRE passes through, in driving order, consecutive
        duplicates dropped. Collision-checked. Note that these are centres, where an arc's are
        the rear points that ride the circle: a rotating robot is off-axis at every one of
        them, so the centre path is what the clearance model has to be given.
    :param xs: ``cells``' x offsets, for the vectorised check.
    :param ys: ``cells``' y offsets.
    :param box: ``cells``' ``(min x, max x, min y, max y)``, so a pivot that leaves the arena is
        rejected on four integer comparisons without touching numpy.
    :param end: The end pose's offset - the rounded final centre.
    """

    # eq=False for the same reason _Arc has it: a generated __eq__ over the numpy fields would
    # raise "truth value of an array is ambiguous" for anyone who compared two of these.
    direction: Direction
    cells: tuple[tuple[int, int], ...]
    xs: np.ndarray
    ys: np.ndarray
    box: tuple[int, int, int, int]
    end: tuple[int, int]


# Keyed by everything a pivot's shape depends on. The stroke count and both radii are in the key
# as well as the robot, because all three are config the STM owner is expected to replace at
# runtime, and a stale shape would be a plan for a manoeuvre the car no longer drives.
_SHUFFLES: dict[tuple, _Shuffle] = {}

# The two steering locks one pivot alternates, forward stroke first, keyed by which way its nose
# swings.
#
# Read out of `turn._ANTICLOCKWISE` rather than written out here, because that tuple already
# states the fact the whole manoeuvre rests on: the two locks it names swing the nose left, and
# the two it omits swing it right. Pairing a forward lock with the backward lock on the SAME
# side of it is therefore what makes a shuffle a shuffle. Written out by hand, this table could
# disagree with that tuple and nothing would catch it - the planner would draw a pivot and the
# car would drive an arc, since the two strokes would then cancel rotation instead of
# translation. The `degrees == 90` filter drops the `_45` variants, which share a `.lock`; a
# stroke is a full lock held for however long the stroke lasts, not a 45 degree turn.
_LOCKS: dict[bool, tuple[TurnInstruction, ...]] = {
    clockwise: tuple(
        lock
        for travel in ('FORWARD', 'BACKWARD')
        for lock in TurnInstruction
        if lock.degrees == 90
        and lock.lock.startswith(travel)
        and (lock.lock in _ANTICLOCKWISE) is not clockwise
    )
    for clockwise in (True, False)
}


def pivot(world: World, start: Vector, instruction: PivotInstruction) -> list[Vector] | None:
    """
    Performs a pivot: a shuffle turn, close to on the spot.

    Same contract as :func:`~pathfinding.search.turn.turn`, and the same machinery behind it.
    The shape is derived once per ``(direction, instruction, radii, offset, strokes, robot
    extents)`` and cached as offsets; a call translates them by ``start``, rejects the pivot
    outright if its bounding box leaves the arena, and otherwise reads every cell in one numpy
    operation.

    The cells are the robot's CENTRE path. They are checked against whatever grid ``world``
    carries, which is NOT on its own enough for a pivot: the ordinary grid inflates obstacles
    for a robot squared up to its heading, and a rotating robot needs its circumscribed radius.
    Getting that extra clearance in is the caller's job (see the design spec's "Clearance"
    section) - this module's contract is only that the centre path is exactly these cells, so
    that the caller has something correct to check.

    :param world: The world.
    :param start: The initial vector.
    :param instruction: The pivot instruction.
    :return: The path of the pivot if it is legal, otherwise returns None.
    """

    # Call-time config rule: the radii, the pivot offset and the stroke count are all read from
    # config on every call, so freshly measured values can be dropped in at runtime. All three
    # are part of the cache key, so doing so invalidates the cached shape by itself.
    cell_size = world.cell_size
    locks = _LOCKS[instruction.clockwise]
    radii = tuple(lock.radius(cell_size) for lock in locks)
    offset = config.TURN_PIVOT_OFFSET_CM // cell_size
    strokes = instruction.strokes()

    robot = world.robot
    key = (start.direction, instruction, radii, offset, strokes,
           robot.north_length, robot.east_length, robot.south_length, robot.west_length)

    try:
        shuffle = _SHUFFLES[key]
    except KeyError:
        shuffle = _SHUFFLES[key] = __shuffle(
            start.direction, instruction, locks, radii, offset, strokes, robot
        )

    x, y = start.x, start.y

    # One check for the whole manoeuvre, exactly as turn() does it.
    if not world.contains_all(shuffle.xs, shuffle.ys, shuffle.box, x, y):
        return None

    direction = shuffle.direction
    path = [Vector(direction, x + dx, y + dy) for dx, dy in shuffle.cells]
    end_x, end_y = x + shuffle.end[0], y + shuffle.end[1]
    # The end pose is appended rather than checked, which is turn()'s rule. Here the append
    # NEVER fires: `end` and the last cell are both `(round(x), round(y))` off the same final
    # iteration of the stroke loop, and de-duplication can only drop a repeat, never change its
    # value, so the two are identical by construction rather than by luck. The guard is kept to
    # mirror turn() exactly, not because it is a live branch. The consequence is that a pivot's
    # end pose IS collision-checked where a turn's is not, and that is the right way round: it
    # is the cell the car comes to rest on, rotated.
    if not path or (path[-1].x, path[-1].y) != (end_x, end_y):
        path.append(Vector(direction, end_x, end_y))
    return path


def __shuffle(
    direction: Direction,
    instruction: PivotInstruction,
    locks: tuple[TurnInstruction, ...],
    radii: tuple[int, ...],
    offset: int,
    strokes: int,
    robot: Robot,
) -> _Shuffle:
    """
    Builds one cache entry: the pivot's centre path as offsets from the starting cell.

    Per stroke this is `turn.__geometry`'s statement of a turn, unchanged - the robot pivots
    about a point ``lead`` behind its centre, the turning circle sits ``radius`` to the side the
    steering lock chooses, the rear point rides that circle through the angle the robot turns
    through, and the new centre is ``lead`` ahead of where the rear point lands - run once per
    stroke with the locks alternating and each stroke starting from where the last one left off.
    Deriving it rather than writing it out is the same bet `turn.__geometry` made and won:
    sixteen hand-written cases there became one derivation that then served eight headings and
    two turn sizes for free, and this serves four instructions from eight headings at any
    stroke count with no new cases either.

    Two things are NOT `turn.__geometry`, and both matter:

    * **The heading is a float.** At the default two strokes per 45 degrees the car passes
      through 22.5 degrees, which no `Direction` names, so the derivation works in continuous
      compass degrees and `Direction.of_degrees` is called once, at the end. Reaching for
      `Direction.unit` mid-manoeuvre - the obvious thing, and what a turn does - would quantise
      every intermediate pose to the nearest eighth and the strokes would stop cancelling.
    * **Nothing is rounded until a cell is emitted.** A turn rounds its rear point because it is
      an integer anchor for a midpoint-circle walk; here each stroke's end is the next stroke's
      start, so rounding would accumulate over the strokes and show up as drift the car does not
      actually have. The grid only ever sees `round` applied to a finished centre.

    Angles are maths angles, anticlockwise from the x axis, which is why the compass delta is
    negated. Assumes a square robot, so that one ``lead`` serves every heading; `Entity` and the
    parity bump make that true by construction.
    """
    lead = robot.south_length - offset
    theta = instruction.degrees / strokes

    heading = float(direction.degrees)
    x, y = 0.0, 0.0
    cells: list[tuple[int, int]] = []

    for stroke in range(strokes):
        lock, radius = locks[stroke % 2], radii[stroke % 2]
        ux, uy = sin(radians(heading)), cos(radians(heading))

        # The rear point: what actually rides the circle.
        rear_x, rear_y = x - lead * ux, y - lead * uy

        # Left of the heading is (-uy, ux); right is its negation. The lock decides it, not the
        # direction of travel, which is why the two strokes of a pivot circle opposite sides.
        side_x, side_y = (-uy, ux) if lock.lock in _LEFT_LOCK else (uy, -ux)
        circle_x, circle_y = rear_x + radius * side_x, rear_y + radius * side_y

        # Both locks of a pair sit on the same side of _ANTICLOCKWISE, so `turned` keeps its
        # sign across the whole pivot: the heading is monotone, and the simulator may sweep it.
        turned = -theta if lock.lock in _ANTICLOCKWISE else theta
        starts = degrees(atan2(rear_y - circle_y, rear_x - circle_x))
        steps = max(1, ceil(radians(abs(theta)) * radius))

        for step in range(1, steps + 1):
            swung = heading + turned * step / steps
            angle = radians(starts - turned * step / steps)
            arc_x, arc_y = circle_x + radius * cos(angle), circle_y + radius * sin(angle)
            x = arc_x + lead * sin(radians(swung))
            y = arc_y + lead * cos(radians(swung))
            cell = (round(x), round(y))
            # Consecutive duplicates dropped, so what comes out is a path and not a set. The
            # strokes are walked into one list rather than concatenated, so the join between two
            # strokes - where the car reverses and the same cell is the obvious candidate to
            # repeat - is de-duplicated like any other step.
            if not cells or cell != cells[-1]:
                cells.append(cell)

        heading += turned

    xs = [cell[0] for cell in cells]
    ys = [cell[1] for cell in cells]

    return _Shuffle(
        Direction.of_degrees(heading),
        tuple(cells),
        np.array(xs),
        np.array(ys),
        (min(xs), max(xs), min(ys), max(ys)),
        (round(x), round(y)),
    )
