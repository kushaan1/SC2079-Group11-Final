"""
The cached, translated turn arcs must answer exactly what a per-cell check of the same cells would.

``slow_turn`` below is the oracle: it takes the arc's shape as ``turn()`` traces it on an
all-free arena, translates every cell to the start by hand, and asks ``World.contains`` about
each one - the way the pre-cache implementation did. Every test asserts that the fast path (one
bounding-box test, one vectorised grid read) agrees with it cell for cell and is None in exactly
the same cases. The shape is pinned by ``tests/test_turn_calibration.py``: the end pose, the
centre arc, and the rear arc's start, end and radius - the cells this file compares are only
right if that file passes too. This file is about the translation and the check.
"""
from __future__ import annotations

import numpy as np
import pytest

import config
from pathfinding.search.instructions import TurnInstruction
from pathfinding.search.turn import turn
from pathfinding.world.primitives import Direction, Point, Vector
from pathfinding.world.world import Obstacle, Robot, World

CASES = [(direction, instruction) for direction in Direction for instruction in TurnInstruction]


def arena(footprint_cm: int = 31, obstacles: tuple[Obstacle, ...] = ()) -> World:
    robot = Robot.planned(Direction.NORTH, Point(0, 0), Point(footprint_cm - 1, footprint_cm - 1))
    return World(config.GRID_SIZE, robot, list(obstacles))


def shape(direction: Direction, instruction: TurnInstruction):
    """The arc's cells and end pose as offsets from the start, traced where nothing can clip it."""
    world = arena()
    world.grid[:, :] = True
    *cells, end = turn(world, Vector(direction, 100, 100), instruction)
    return [(v.x - 100, v.y - 100) for v in cells], (end.x - 100, end.y - 100), end.direction


def slow_turn(world: World, start: Vector, instruction: TurnInstruction) -> list[Vector] | None:
    cells, (ex, ey), facing = shape(start.direction, instruction)
    if not all(world.contains(Point(start.x + dx, start.y + dy)) for dx, dy in cells):
        return None
    path = [Vector(facing, start.x + dx, start.y + dy) for dx, dy in cells]
    if not path or (path[-1].x, path[-1].y) != (start.x + ex, start.y + ey):
        path.append(Vector(facing, start.x + ex, start.y + ey))
    return path


@pytest.mark.parametrize("direction,instruction", CASES, ids=lambda v: v.value)
def test_every_case_matches_the_oracle_on_an_empty_arena(direction, instruction):
    world = arena()
    start = Vector(direction, 100, 100)
    expected = slow_turn(world, start, instruction)
    assert expected is not None, "the oracle itself must find this turn legal mid-arena"
    assert turn(world, start, instruction) == expected


def test_a_turn_that_clips_an_obstacle_is_none():
    world = arena(obstacles=(Obstacle(Direction.SOUTH, Point(90, 90), Point(99, 99), 11),))
    blocked = 0
    for direction, instruction in CASES:
        for x in range(60, 141, 10):
            for y in range(60, 141, 10):
                start = Vector(direction, x, y)
                expected = slow_turn(world, start, instruction)
                assert turn(world, start, instruction) == expected, (direction, instruction, x, y)
                blocked += expected is None
    assert blocked > 0, "this arena was supposed to block some turns"


def test_arcs_that_run_off_the_grid_are_none_not_wrapped():
    """
    A negative arc cell is out of bounds, not a wrap-around index into the far edge. Every cell
    of the grid is made free, so the ONLY thing that can reject a turn here is the bounds check.
    """
    world = arena()
    world.grid[:, :] = True
    off_grid = 0
    for direction, instruction in CASES:
        for x, y in ((0, 0), (5, 5), (14, 14), (14, 185), (185, 14), (185, 185), (199, 199)):
            start = Vector(direction, x, y)
            expected = slow_turn(world, start, instruction)
            assert turn(world, start, instruction) == expected, (direction, instruction, x, y)
            off_grid += expected is None
    assert off_grid > 0


def test_matches_the_oracle_across_a_populated_arena():
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
                expected = slow_turn(world, start, instruction)
                assert turn(world, start, instruction) == expected, (direction, instruction, x, y)
                legal += expected is not None
    assert legal > 0


def test_cache_follows_a_runtime_table_change(monkeypatch):
    """The key holds the measured pair read from config at call time, so a change invalidates it."""
    world = arena()
    start = Vector(Direction.NORTH, 100, 100)
    first = turn(world, start, TurnInstruction.FORWARD_LEFT)
    table = dict(config.TURN_DISPLACEMENT_CM)
    across, along = table["FORWARD_LEFT"]
    table["FORWARD_LEFT"] = (across - 10, along)
    monkeypatch.setattr(config, "TURN_DISPLACEMENT_CM", table)
    second = turn(world, start, TurnInstruction.FORWARD_LEFT)
    assert second == slow_turn(world, start, TurnInstruction.FORWARD_LEFT)
    assert second != first


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
    # The boundary keep-out band is INSIDE the grid, so the same shape in it must fail on the
    # grid read, not on the bounds check: every cell is in bounds, and every cell is blocked.
    assert 0 <= 5 + box[0] and 5 + box[1] < world.size and 0 <= 100 + box[2] and 100 + box[3] < world.size
    assert not world.grid[xs + 5, ys + 100].any()
    assert world.contains_all(xs, ys, box, 5, 100) is False
    world.grid[world.size - 1, 100] = True
    world.grid[100, world.size - 1] = True
    assert world.contains_all(np.array([-1]), np.array([0]), (-1, -1, 0, 0), 0, 100) is False
    assert world.contains_all(np.array([0]), np.array([-1]), (0, 0, -1, -1), 100, 0) is False
    assert world.contains_all(np.array([0]), np.array([0]), (0, 0, 0, 0), world.size, 100) is False
    assert world.contains_all(np.array([0]), np.array([0]), (0, 0, 0, 0), 100, world.size) is False
    world.grid[101, 101] = False
    assert world.contains_all(xs, ys, box, 100, 100) is False
