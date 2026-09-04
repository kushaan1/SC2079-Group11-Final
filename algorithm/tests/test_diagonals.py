"""
The experimental eight-heading planner: `config.DIAGONAL_HEADINGS`.

Everything else in the suite pins the four-heading planner (see `conftest.py`); these are the
only tests that switch the diagonals on. They cover what the extra headings add, not the
planner as a whole.
"""
import math
import os

import pytest

import config
from pathfinding import cost
from pathfinding.search.instructions import Move, Straight, Turn, TurnInstruction
from pathfinding.search.search import search
from pathfinding.search.tour import plan_optimal
from pathfinding.search.turn import turn
from pathfinding.world.objective import generate_objectives
from pathfinding.world.primitives import Direction, Point, Vector
from pathfinding.world.world import Robot, World
from simulator.arena import load
from simulator.playback import Playback
from simulator.routes import Route

pytestmark = pytest.mark.diagonals

TESTDATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testdata")


def empty_world():
    robot = Robot.planned(Direction.NORTH, Point(0, 0), Point(30, 30))
    return World(config.GRID_SIZE, robot, [])


def test_every_heading_and_turn_size_produces_an_eight_connected_arc():
    world = empty_world()
    for direction in Direction:
        for instruction in TurnInstruction:
            path = turn(world, Vector(direction, 100, 100), instruction)
            assert path is not None, (direction, instruction)
            arc = path[:-1]
            for before, after in zip(arc, arc[1:]):
                assert max(abs(after.x - before.x), abs(after.y - before.y)) == 1, (direction, instruction)


def test_a_turn_swings_the_heading_by_its_own_size():
    world = empty_world()
    anticlockwise = ("FORWARD_LEFT", "BACKWARD_RIGHT")
    for direction in Direction:
        for instruction in TurnInstruction:
            path = turn(world, Vector(direction, 100, 100), instruction)
            swing = -instruction.degrees if instruction.lock in anticlockwise else instruction.degrees
            assert path[-1].direction == Direction.of_degrees(direction.degrees + swing), (direction, instruction)


@pytest.mark.parametrize("lock", ("FORWARD_LEFT", "FORWARD_RIGHT", "BACKWARD_LEFT", "BACKWARD_RIGHT"))
def test_two_45_degree_turns_land_where_one_90_does(lock):
    """
    The claim the whole experiment rests on: a 45 is the same steering lock held for half as
    long. If that is true then driving two of them must put the robot where one quarter turn
    would have, and this is the test that would fail if the 45 traced the wrong radius, curved
    the wrong way, or stopped at the wrong point along its arc - none of which the connectivity
    and heading tests above can see.

    One cell of tolerance because both sides are rasterised onto the integer grid.
    """
    world = empty_world()
    for direction in Direction:
        whole = turn(world, Vector(direction, 100, 100), TurnInstruction(lock))[-1]
        first = turn(world, Vector(direction, 100, 100), TurnInstruction(lock + "_45"))[-1]
        second = turn(world, first, TurnInstruction(lock + "_45"))[-1]

        assert second.direction == whole.direction, (direction, lock)
        assert max(abs(second.x - whole.x), abs(second.y - whole.y)) <= 1, (direction, lock)


def test_a_45_degree_turn_costs_half_a_90():
    """Half the swing, half the seconds - the time model's half of the same claim."""
    assert (cost.TIME_SECONDS.turn(TurnInstruction.FORWARD_LEFT_45)
            == pytest.approx(cost.TIME_SECONDS.turn(TurnInstruction.FORWARD_LEFT) / 2))


def test_a_diagonal_cell_costs_root_two():
    cells = [Vector(Direction.NORTHEAST, i, i) for i in range(1, 6)]
    diagonal = cost.move_cost(Move(Straight.FORWARD, cells), cost.DISTANCE_CELLS, 1)
    straight = cost.move_cost(
        Move(Straight.FORWARD, [Vector(Direction.NORTH, 0, i) for i in range(1, 6)]),
        cost.DISTANCE_CELLS, 1,
    )
    assert diagonal == pytest.approx(straight * math.sqrt(2))


@pytest.mark.parametrize("name", ("02-four-obstacles.json", "04-five-obstacles.json"))
def test_the_diagonals_earn_their_keep(name, monkeypatch):
    """The point of the experiment: eight headings must not lose to four, and here they win."""
    world = load(os.path.join(TESTDATA, name)).world()

    monkeypatch.setattr(config, "DIAGONAL_HEADINGS", False)
    four = plan_optimal(world, generate_objectives(world))

    monkeypatch.setattr(config, "DIAGONAL_HEADINGS", True)
    eight = plan_optimal(world, generate_objectives(world))

    assert len(eight.segments) == len(four.segments)
    assert sum(s.seconds for s in eight.segments) < sum(s.seconds for s in four.segments)


def test_playback_rotates_through_a_45_degree_turn():
    world = load(os.path.join(TESTDATA, "04-five-obstacles.json")).world()
    result = plan_optimal(world, generate_objectives(world))
    route = Route(result.segments, result.unreachable, "test", 0.0, world.robot, world.cell_size)
    playback = Playback(route)

    assert any(isinstance(m, Turn) and m.turn.degrees == 45 for s in result.segments for m in s.moves)
    # A frame actually facing a diagonal. The set of headings mod 45 was the earlier assertion
    # and proved nothing: any non-empty frame list satisfies it.
    assert any(round(frame.pose.heading_deg) % 90 != 0 for frame in playback.frames), \
        "no frame faces a diagonal, so nothing drove through the 45 degree turn"
