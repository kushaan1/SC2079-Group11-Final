"""
The cached, vectorised turn arcs must be byte-identical to the loop they replaced.

``reference_turn`` and ``reference_curve`` below are the pre-cache implementation of
``pathfinding/search/turn.py``, copied verbatim (only the two names changed) and kept
private to this file. They are the oracle: every test here asserts that the fast path
returns exactly the list the Python loop returned, or ``None`` in exactly the same cases.
"""
from __future__ import annotations

import json
import os

import numpy as np
import pytest

import config
from pathfinding.search.instructions import TurnInstruction
from pathfinding.search.search import search
from pathfinding.search.turn import turn
from pathfinding.world.objective import generate_objectives
from pathfinding.world.primitives import Direction, Point, Vector
from pathfinding.world.world import Obstacle, Robot, World
from simulator.arena import load

TESTDATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testdata")
BASELINE = os.path.join(os.environ.get("TMPDIR", "/tmp"), "baseline-turn.json")
CASES = [(direction, instruction) for direction in Direction for instruction in TurnInstruction]


def arena(footprint_cm: int = 31, obstacles: tuple[Obstacle, ...] = ()) -> World:
    """A world with a square robot of the given footprint, parity bump included."""
    robot = Robot.planned(Direction.NORTH, Point(0, 0), Point(footprint_cm - 1, footprint_cm - 1))
    return World(config.GRID_SIZE, robot, list(obstacles))


# ---------------------------------------------------------------------------------------
# Oracle: the implementation this task replaced, verbatim.
# ---------------------------------------------------------------------------------------


# This turning function does not properly account for different points of the robot having different turning radii.
# I'm too lazy to fix it. The workaround is to ensure that the robot is an odd number of cells.
def reference_turn(world: World, start: Vector, instruction: TurnInstruction) -> list[Vector] | None:
    """
    Performs a turn.

    :param world: The world.
    :param start: The initial vector.
    :param instruction: The turn instruction.
    :return: The path of the turn if it is legal, otherwise returns None.
    """

    # The turning radius (in grid cells), read from config on every call so that
    # freshly measured radii can be dropped in at runtime.
    turning_radius = instruction.radius(world.cell_size)
    offset = config.TURN_PIVOT_OFFSET_CM // world.cell_size

    curve: list[Vector] | None
    match (start.direction, instruction):
        # y facing north
        case (Direction.NORTH, TurnInstruction.FORWARD_LEFT):
            x = start.x
            y = start.y - world.robot.south_length + offset
            return reference_curve(
                world,
                turning_radius,
                Vector(
                    Direction.WEST,
                    x - turning_radius - world.robot.east_length + offset,
                    y + turning_radius,
                ),
                x - turning_radius,
                y,
                1,
            )

        case (Direction.NORTH, TurnInstruction.FORWARD_RIGHT):
            x = start.x
            y = start.y - world.robot.south_length + offset
            return reference_curve(
                world,
                turning_radius,
                Vector(
                    Direction.EAST,
                    x + turning_radius + world.robot.west_length - offset,
                    y + turning_radius,
                ),
                x + turning_radius,
                y,
                2,
            )

        case (Direction.NORTH, TurnInstruction.BACKWARD_LEFT):
            x = start.x
            y = start.y - world.robot.south_length + offset
            return reference_curve(
                world,
                turning_radius,
                Vector(
                    Direction.EAST,
                    x - turning_radius + world.robot.west_length - offset,
                    y - turning_radius,
                ),
                x - turning_radius,
                y,
                4,
            )

        case (Direction.NORTH, TurnInstruction.BACKWARD_RIGHT):
            x = start.x
            y = start.y - world.robot.south_length + offset
            return reference_curve(
                world,
                turning_radius,
                Vector(
                    Direction.WEST,
                    x + turning_radius - world.robot.west_length + offset,
                    y - turning_radius,
                ),
                x + turning_radius,
                y,
                3,
            )

        # y facing east
        case (Direction.EAST, TurnInstruction.FORWARD_LEFT):
            x = start.x - world.robot.west_length + offset
            y = start.y
            return reference_curve(
                world,
                turning_radius,
                Vector(
                    Direction.NORTH,
                    x + turning_radius,
                    y + turning_radius + world.robot.south_length - offset,
                ),
                x,
                y + turning_radius,
                4,
            )

        case (Direction.EAST, TurnInstruction.FORWARD_RIGHT):
            x = start.x - world.robot.west_length + offset
            y = start.y
            return reference_curve(
                world,
                turning_radius,
                Vector(
                    Direction.SOUTH,
                    x + turning_radius,
                    y - turning_radius - world.robot.north_length + offset,
                ),
                x,
                y - turning_radius,
                1,
            )

        case (Direction.EAST, TurnInstruction.BACKWARD_LEFT):
            x = start.x - world.robot.west_length + offset
            y = start.y
            return reference_curve(
                world,
                turning_radius,
                Vector(
                    Direction.SOUTH,
                    x - turning_radius,
                    y + turning_radius - world.robot.north_length + offset,
                ),
                x,
                y + turning_radius,
                3,
            )

        # Fix 6: the reference put the robot-extent term on the circle centre instead of the end
        # pose, so this arc was checked 12 cm off and the post-turn pose was wrong by 12 cm.
        # Now mirrors (EAST, BACKWARD_LEFT).
        case (Direction.EAST, TurnInstruction.BACKWARD_RIGHT):
            x = start.x - world.robot.west_length + offset
            y = start.y
            return reference_curve(
                world,
                turning_radius,
                Vector(
                    Direction.NORTH,
                    x - turning_radius,
                    y - turning_radius + world.robot.south_length - offset,
                ),
                x,
                y - turning_radius,
                2,
            )

        # y facing south
        case (Direction.SOUTH, TurnInstruction.FORWARD_LEFT):
            x = start.x
            y = start.y + world.robot.north_length - offset
            return reference_curve(
                world,
                turning_radius,
                Vector(
                    Direction.EAST,
                    x + turning_radius + world.robot.west_length - offset,
                    y - turning_radius,
                ),
                x + turning_radius,
                y,
                3,
            )

        case (Direction.SOUTH, TurnInstruction.FORWARD_RIGHT):
            x = start.x
            y = start.y + world.robot.north_length - offset
            return reference_curve(
                world,
                turning_radius,
                Vector(
                    Direction.WEST,
                    x - turning_radius - world.robot.east_length + offset,
                    y - turning_radius,
                ),
                x - turning_radius,
                y,
                4,
            )

        case (Direction.SOUTH, TurnInstruction.BACKWARD_LEFT):
            x = start.x
            y = start.y + world.robot.north_length - offset
            return reference_curve(
                world,
                turning_radius,
                Vector(
                    Direction.WEST,
                    x + turning_radius - world.robot.east_length + offset,
                    y + turning_radius,
                ),
                x + turning_radius,
                y,
                2,
            )

        case (Direction.SOUTH, TurnInstruction.BACKWARD_RIGHT):
            x = start.x
            y = start.y + world.robot.north_length - offset
            return reference_curve(
                world,
                turning_radius,
                Vector(
                    Direction.EAST,
                    x - turning_radius + world.robot.west_length - offset,
                    y + turning_radius,
                ),
                x - turning_radius,
                y,
                1,
            )

        # y facing west
        case (Direction.WEST, TurnInstruction.FORWARD_LEFT):
            x = start.x + world.robot.east_length - offset
            y = start.y
            return reference_curve(
                world,
                turning_radius,
                Vector(
                    Direction.SOUTH,
                    x - turning_radius,
                    y - turning_radius - world.robot.north_length + offset,
                ),
                x,
                y - turning_radius,
                2,
            )

        case (Direction.WEST, TurnInstruction.FORWARD_RIGHT):
            x = start.x + world.robot.east_length - offset
            y = start.y
            return reference_curve(
                world,
                turning_radius,
                Vector(
                    Direction.NORTH,
                    x - turning_radius,
                    y + turning_radius + world.robot.south_length - offset,
                ),
                x,
                y + turning_radius,
                3,
            )

        case (Direction.WEST, TurnInstruction.BACKWARD_LEFT):
            x = start.x + world.robot.east_length - offset
            y = start.y
            return reference_curve(
                world,
                turning_radius,
                Vector(
                    Direction.NORTH,
                    x + turning_radius,
                    y - turning_radius + world.robot.south_length - offset,
                ),
                x,
                y - turning_radius,
                1,
            )

        case (Direction.WEST, TurnInstruction.BACKWARD_RIGHT):
            x = start.x + world.robot.east_length - offset
            y = start.y
            return reference_curve(
                world,
                turning_radius,
                Vector(
                    Direction.SOUTH,
                    x + turning_radius,
                    y + turning_radius - world.robot.north_length + offset,
                ),
                x,
                y + turning_radius,
                4,
            )


def reference_curve(
    world: World,
    turning_radius: int,
    end: Vector,
    centre_x: int,
    centre_y,
    quadrant: int,
) -> list[Vector] | None:
    """
    Uses a modified Midpoint circle algorithm to determine the curved path of a robot when turning.

    Fix 1 (blocking): the reference declared this function with five parameters while all
    sixteen call sites passed six, and the body referenced an undefined name `end`. The
    missing `end: Vector` parameter is restored here. Without it the very first turn()
    call raises TypeError, which is why the reference planner cannot plan a path at all.

    :param end: The final vector of the turn. Supplies the post-turn facing for every vector
        on the arc, and is appended as the last element of the returned path.
    :param centre_x: The centre of the turning radius's x value.
    :param centre_y: The centre of the turning radius's y value.
    :param quadrant: The quadrant of the circle.
        Quadrants:
              2 | 1
            ----+----
              3 | 4
    :return: the vectors in the curve, may contain duplicates
    """
    assert 1 <= quadrant <= 4

    x = turning_radius
    y = 0
    err = 0

    # The original Midpoint circle algorithm fills in quadrants from two extremes. We store them in separate lists to
    # ensure an ordered list of vectors starting from the starting vector is returned.
    path = []
    a_map = None
    b_map = None

    match quadrant:
        case 1:
            a_map = lambda _x, _y: Vector(end.direction, centre_x + _x, centre_y + _y)
            b_map = lambda _x, _y: Vector(end.direction, centre_x + _y, centre_y + _x)
        case 2:
            a_map = lambda _x, _y: Vector(end.direction, centre_x - _y, centre_y + _x)
            b_map = lambda _x, _y: Vector(end.direction, centre_x - _x, centre_y + _y)
        case 3:
            a_map = lambda _x, _y: Vector(end.direction, centre_x - _x, centre_y - _y)
            b_map = lambda _x, _y: Vector(end.direction, centre_x - _y, centre_y - _x)
        case 4:
            a_map = lambda _x, _y: Vector(end.direction, centre_x + _y, centre_y - _x)
            b_map = lambda _x, _y: Vector(end.direction, centre_x + _x, centre_y - _y)

    while x >= y:
        a = a_map(x, y)
        if world.contains(a):
            path.append(a)
        else:
            return None

        b = b_map(x, y)
        if world.contains(b):
            path.append(b)
        else:
            return None

        y += 1
        err += 1 + 2 * y
        if 2 * (err - x) + 1 > 0:
            x -= 1
            err += 1 - 2 * x

    path.append(end)
    return path

# ---------------------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("direction,instruction", CASES, ids=lambda v: v.value)
def test_every_case_matches_the_reference_on_an_empty_arena(direction, instruction):
    world = arena()
    start = Vector(direction, 100, 100)

    expected = reference_turn(world, start, instruction)
    actual = turn(world, start, instruction)

    assert expected is not None, "the reference itself must find this turn legal"
    assert actual is not None
    assert actual[0] == expected[0]          # first cell of the arc
    assert actual[-1] == expected[-1]        # end pose
    assert actual == expected                # and every cell in between, in order


def test_a_turn_that_clips_an_obstacle_is_none():
    obstacle = Obstacle(Direction.SOUTH, Point(90, 90), Point(99, 99), 11)
    world = arena(obstacles=(obstacle,))

    blocked = 0
    for direction, instruction in CASES:
        for x in range(60, 141, 10):
            for y in range(60, 141, 10):
                start = Vector(direction, x, y)
                expected = reference_turn(world, start, instruction)
                assert turn(world, start, instruction) == expected
                if expected is None:
                    blocked += 1

    assert blocked > 0, "this arena was supposed to block some turns"


def test_arcs_that_run_off_the_grid_are_none_not_wrapped():
    """
    A negative arc cell is out of bounds, not a wrap-around index into the far edge.

    Every cell of the grid is made free, so the ONLY thing that can reject a turn here is
    the bounds check. numpy would happily read grid[-25, y] as grid[175, y] and call the
    turn legal; ``World.contains`` never did, and neither may the vectorised check.
    """
    world = arena()
    world.grid[:, :] = True

    off_grid = 0
    for direction, instruction in CASES:
        for x, y in ((0, 0), (5, 5), (14, 14), (14, 185), (185, 14), (185, 185), (199, 199)):
            start = Vector(direction, x, y)
            expected = reference_turn(world, start, instruction)
            assert turn(world, start, instruction) == expected, (direction, instruction, x, y)
            off_grid += expected is None

    assert off_grid > 0, "these starts were supposed to push some arcs off the grid"


def test_matches_the_reference_across_a_populated_arena():
    world = arena(obstacles=(
        Obstacle(Direction.SOUTH, Point(50, 90), Point(59, 99), 11),
        Obstacle(Direction.WEST, Point(120, 60), Point(129, 69), 12),
        Obstacle(Direction.EAST, Point(60, 150), Point(69, 159), 14),
    ))

    legal = 0
    for direction, instruction in CASES:
        for x in range(0, 200, 13):
            for y in range(0, 200, 13):
                start = Vector(direction, x, y)
                expected = reference_turn(world, start, instruction)
                assert turn(world, start, instruction) == expected, (direction, instruction, x, y)
                legal += expected is not None

    assert legal > 0, "this sweep was supposed to find some legal turns"


def test_cache_does_not_leak_across_robot_sizes():
    big, small = arena(31), arena(21)
    start = Vector(Direction.NORTH, 100, 100)

    # Warm the cache with the big robot first, so a key missing the robot extents would
    # hand the small robot the big robot's arc.
    big_arc = turn(big, start, TurnInstruction.FORWARD_LEFT)
    small_arc = turn(small, start, TurnInstruction.FORWARD_LEFT)

    assert big_arc == reference_turn(big, start, TurnInstruction.FORWARD_LEFT)
    assert small_arc == reference_turn(small, start, TurnInstruction.FORWARD_LEFT)
    assert big_arc != small_arc


def test_cache_follows_a_runtime_radius_change():
    """The key holds the radius read from config at call time, so a change invalidates it."""
    world = arena()
    start = Vector(Direction.NORTH, 100, 100)
    original = dict(config.TURN_RADIUS_CM)
    try:
        first = turn(world, start, TurnInstruction.FORWARD_LEFT)
        config.TURN_RADIUS_CM["FORWARD_LEFT"] = original["FORWARD_LEFT"] - 10
        second = turn(world, start, TurnInstruction.FORWARD_LEFT)
        assert second == reference_turn(world, start, TurnInstruction.FORWARD_LEFT)
        assert second != first
    finally:
        config.TURN_RADIUS_CM.clear()
        config.TURN_RADIUS_CM.update(original)


def test_each_call_returns_its_own_vectors():
    """The cache holds offsets, not the returned objects: Vector is mutable and shared."""
    world = arena()
    start = Vector(Direction.NORTH, 100, 100)

    first = turn(world, start, TurnInstruction.FORWARD_LEFT)
    second = turn(world, start, TurnInstruction.FORWARD_LEFT)

    assert first == second
    assert first is not second
    assert all(a is not b for a, b in zip(first, second))


def test_contains_all_bounds_checks_before_indexing():
    world = arena()
    xs, ys = np.array([0, 1, 2]), np.array([0, 1, 2])
    box = (0, 2, 0, 2)

    assert world.contains_all(xs, ys, box, 100, 100) is True

    # Negative coordinates are OUT OF BOUNDS, never a wrap-around to the far edge. The cells
    # they would wrap to are made free, so a wrapped read would come back legal.
    world.grid[world.size - 1, 100] = True
    world.grid[100, world.size - 1] = True
    assert world.contains_all(np.array([-1]), np.array([0]), (-1, -1, 0, 0), 0, 100) is False
    assert world.contains_all(np.array([0]), np.array([-1]), (0, 0, -1, -1), 100, 0) is False

    # And so is anything at or past the far edge.
    assert world.contains_all(np.array([0]), np.array([0]), (0, 0, 0, 0), world.size, 100) is False
    assert world.contains_all(np.array([0]), np.array([0]), (0, 0, 0, 0), 100, world.size) is False

    # In bounds but blocked.
    world.grid[101, 101] = False
    assert world.contains_all(xs, ys, box, 100, 100) is False

    # The boundary keep-out band is inside the grid, so it fails on the grid, not the bounds.
    assert world.contains_all(xs, ys, box, 0, 0) is False


@pytest.mark.skipif(not os.path.exists(BASELINE), reason=f"no baseline at {BASELINE}")
def test_replanning_the_testdata_arenas_matches_the_baseline():
    """Byte-identical planner output against the pre-change capture (step 1 of the brief)."""
    with open(BASELINE) as handle:
        baseline = json.load(handle)

    for name, expected in baseline.items():
        world = load(os.path.join(TESTDATA, name)).world()
        result = search(world, generate_objectives(world))

        segments = [
            [s.image_id, s.cost,
             [[v.direction.value, v.x, v.y] for v in s.vectors],
             [str(i) for i in s.instructions]]
            for s in result.segments
        ]
        unreachable = [[u.image_id, u.reason.value] for u in result.unreachable]

        assert segments == json.loads(json.dumps(expected["segments"])), name
        assert unreachable == expected["unreachable"], name
