"""
The cap on how far one FORWARD/BACKWARD command may ask the STM to drive.

The planner merges consecutive same-direction chunks into one command with no upper bound, so
a clear run across the arena arrives as a single large `amount`. Measured on 2026-09-17: a lone
obstacle at (100,80) facing NORTH produces a 140 cm FORWARD, and a sweep of 300 random 4-8
obstacle arenas produced one of 160 cm. The STM's forward motion is calibrated over a narrower
band than that, so the wire format needs a ceiling the firmware owner can set.

This is a wire-format concern only: the path, its cells and its cost are identical either way,
and only the chunking of the command stream changes.
"""

import config
import pytest

from pathfinding.search.instructions import MoveInstruction
from pathfinding.search.search import search, split_straight
from pathfinding.world.objective import generate_objectives
from pathfinding.world.primitives import Direction, Point
from pathfinding.world.world import Obstacle, Robot, World


def long_straight_world() -> World:
    """
    The arena that provokes the longest straight found on a single-obstacle sweep: one obstacle
    at (100,80) facing NORTH, from the configured start pose. The greedy planner drives straight
    at it, giving `FORWARD(140cm) -> BACKWARD_RIGHT -> BACKWARD_RIGHT -> CAPTURE_IMAGE`.
    """
    robot = Robot.planned(
        Direction(config.START_POSE["direction"]),
        Point(*config.START_POSE["south_west"]),
        Point(*config.START_POSE["north_east"]),
    )
    return World(config.GRID_SIZE, robot, [Obstacle(Direction.NORTH, Point(100, 80), Point(109, 89), 11)])


def straights(world: World) -> list[int]:
    """Every straight amount the planner emits for `world`, in driving order."""
    result = search(world, generate_objectives(world))
    return [i.amount for s in result.segments for i in s.instructions if isinstance(i, MoveInstruction)]


def test_split_leaves_a_move_within_the_limit_alone():
    assert split_straight(50, 100) == [50]
    assert split_straight(100, 100) == [100]


def test_split_divides_evenly_rather_than_leaving_a_stub():
    """
    The reason this function exists rather than a plain `while amount > limit: emit(limit)`.
    Taking the limit greedily would turn 105 into `100 + 5`, and a 5 cm command is the worst
    case for both start/stop overhead and proportional distance error - the error of a 5 cm
    move is nearly all of it fixed. Two near-equal halves cost the same and drive better.
    """
    assert split_straight(105, 100) == [53, 52]
    assert split_straight(140, 100) == [70, 70]
    assert split_straight(250, 100) == [84, 83, 83]


def test_split_preserves_the_distance_and_never_exceeds_the_limit():
    for amount in range(1, 301):
        pieces = split_straight(amount, 100)
        assert sum(pieces) == amount, amount
        assert max(pieces) <= 100, amount
        assert min(pieces) >= 1, amount


def test_split_treats_a_limit_below_one_as_no_cap():
    """`MAX_STRAIGHT_CM = 0` must not be a division by zero or an infinite stream of 0 cm moves."""
    assert split_straight(140, 0) == [140]


def test_planner_does_not_emit_a_straight_over_the_cap(monkeypatch):
    monkeypatch.setattr(config, "MAX_STRAIGHT_CM", 100)
    amounts = straights(long_straight_world())
    assert amounts, "the arena is supposed to produce at least one straight"
    assert max(amounts) <= 100


def test_capping_splits_the_command_without_changing_the_distance(monkeypatch):
    monkeypatch.setattr(config, "MAX_STRAIGHT_CM", 200)
    uncapped = straights(long_straight_world())
    monkeypatch.setattr(config, "MAX_STRAIGHT_CM", 100)
    capped = straights(long_straight_world())
    assert max(uncapped) == 140, "the 140 cm baseline this file is built on has moved"
    assert sum(capped) == sum(uncapped)
    assert capped == [70, 70]


def test_the_cap_is_read_at_call_time(monkeypatch):
    """
    Same call-time config rule as `TurnInstruction.radius` and `PivotInstruction.strokes`: the
    STM owner's number is theirs to change at runtime, so nothing may bind it at import.
    """
    world = long_straight_world()
    monkeypatch.setattr(config, "MAX_STRAIGHT_CM", 50)
    assert max(straights(world)) <= 50
    monkeypatch.setattr(config, "MAX_STRAIGHT_CM", 100)
    assert max(straights(world)) == 70


def test_the_path_and_cost_are_untouched_by_the_cap(monkeypatch):
    """Chunking the command stream is not re-planning: same cells, same cost, same seconds."""
    world = long_straight_world()
    monkeypatch.setattr(config, "MAX_STRAIGHT_CM", 200)
    uncapped = search(world, generate_objectives(world))
    monkeypatch.setattr(config, "MAX_STRAIGHT_CM", 100)
    capped = search(world, generate_objectives(world))
    assert [s.cost for s in capped.segments] == [s.cost for s in uncapped.segments]
    assert [s.vectors for s in capped.segments] == [s.vectors for s in uncapped.segments]
    assert [s.seconds for s in capped.segments] == pytest.approx([s.seconds for s in uncapped.segments])
