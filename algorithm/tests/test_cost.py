import os

import pytest

import config
from pathfinding import cost
from pathfinding.search.instructions import Move, MoveInstruction, Straight, Turn, TurnInstruction
from pathfinding.search.search import search
from pathfinding.search.segment import segment
from pathfinding.world.objective import generate_objectives
from pathfinding.world.primitives import Direction, Vector
from simulator.arena import load

TESTDATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testdata")


def cells(n):
    return [Vector(Direction.NORTH, 0, i) for i in range(n)]


def test_time_weights_read_config_at_call_time(monkeypatch):
    monkeypatch.setattr(config, "ROBOT_SPEED_CM_S", 50)
    monkeypatch.setattr(config, "TURN_TIME_S", 4.0)
    assert cost.TIME_SECONDS.straight(25, 1) == pytest.approx(0.5)
    assert cost.TIME_SECONDS.turn(TurnInstruction.FORWARD_LEFT) == 4.0
    assert cost.DISTANCE_CELLS.straight(25, 1) == 25
    assert cost.DISTANCE_CELLS.turn(TurnInstruction.FORWARD_LEFT) == TurnInstruction.FORWARD_LEFT.arc_length(1)


def test_distance_weights_stay_in_cells():
    # Both halves are grid cells, so they add; callers convert to cm with cell_size. A model
    # that scaled only one half would silently prefer the other at any cell size but 1.
    assert cost.DISTANCE_CELLS.straight(25, 5) == 25
    assert cost.DISTANCE_CELLS.turn(TurnInstruction.FORWARD_LEFT, 5) == TurnInstruction.FORWARD_LEFT.arc_length(5)


def test_seconds_sums_moves():
    moves = [Move(Straight.FORWARD, cells(30)), Turn(TurnInstruction.FORWARD_RIGHT, cells(5)), Move(Straight.BACKWARD, cells(10))]
    expected = 40 / config.ROBOT_SPEED_CM_S + config.TURN_TIME_S
    assert cost.seconds(moves, 1) == pytest.approx(expected)


def test_segment_cost_is_still_cells_and_seconds_matches_model():
    world = load(os.path.join(TESTDATA, "02-four-obstacles.json")).world()
    result = search(world, generate_objectives(world))
    assert [s.cost for s in result.segments] == [88, 91, 280, 460]
    for s in result.segments:
        assert s.seconds == pytest.approx(cost.seconds(s.moves, world.cell_size))
        assert s.seconds > 0


def test_time_weighted_leg_is_no_slower_than_distance_weighted():
    world = load(os.path.join(TESTDATA, "02-four-obstacles.json")).world()
    generated = generate_objectives(world)
    start = world.robot.vector
    by_distance = segment(world, start, generated.objectives)
    by_time = segment(world, start, generated.objectives, weights=cost.TIME_SECONDS)
    assert by_distance is not None and by_time is not None
    _, d_cost, d_parts = by_distance
    _, t_cost, t_parts = by_time
    assert isinstance(t_cost, float)
    assert t_cost <= cost.seconds([m for _, m in d_parts if m is not None], world.cell_size) + 1e-9


def test_segment_accepts_a_set_of_sources():
    # Seeding several poses at cost 0 must answer "cheapest from ANY of them" exactly - not
    # merely "no worse than one of them", which a search that quietly ignored the extra seeds
    # would also satisfy.
    world = load(os.path.join(TESTDATA, "01-single-obstacle.json")).world()
    generated = generate_objectives(world)
    start = world.robot.vector
    other = Vector(Direction.NORTH, 100, 100)

    from_start = segment(world, start, generated.objectives)
    from_other = segment(world, other, generated.objectives)
    multi = segment(world, {start, other}, generated.objectives)
    assert from_start is not None and from_other is not None and multi is not None
    assert multi[1] == pytest.approx(min(from_start[1], from_other[1]))

    # And the path it returns really starts at one of the seeds, so the caller can drive it.
    first, _ = multi[2][0]
    assert first in {start, other}


def test_segment_source_shapes_agree_and_an_empty_one_finds_nothing():
    world = load(os.path.join(TESTDATA, "01-single-obstacle.json")).world()
    generated = generate_objectives(world)
    start = world.robot.vector

    bare = segment(world, start, generated.objectives)
    listed = segment(world, [start], generated.objectives)
    assert bare is not None and listed is not None
    assert listed[1] == pytest.approx(bare[1])
    assert [v for v, _ in listed[2]] == [v for v, _ in bare[2]]

    # No sources means no frontier, which is no path - not a crash and not the bare-Vector
    # branch taken by accident.
    assert segment(world, [], generated.objectives) is None


def test_segment_seconds_agree_with_the_instructions_the_robot_is_sent():
    # An independent cross-check of Segment.seconds: cost.seconds() reads the MOVES, this
    # reads the INSTRUCTIONS actually sent over the wire. They are built by different code
    # paths in Segment.compress (instructions merge consecutive straights, moves do not), so
    # agreeing is evidence rather than a tautology.
    world = load(os.path.join(TESTDATA, "02-four-obstacles.json")).world()
    result = search(world, generate_objectives(world))
    assert result.segments

    for s in result.segments:
        driven = sum(i.amount for i in s.instructions if isinstance(i, MoveInstruction))
        turns = sum(1 for i in s.instructions if isinstance(i, TurnInstruction))
        expected = driven / config.ROBOT_SPEED_CM_S + turns * config.TURN_TIME_S
        assert s.seconds == pytest.approx(expected), s.image_id
