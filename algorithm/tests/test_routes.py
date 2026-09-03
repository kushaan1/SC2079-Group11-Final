import os

import pytest

from pathfinding.search.search import search
from pathfinding.world.objective import generate_objectives
from simulator.arena import load
from simulator.routes import SOURCES, GreedyRouteSource, OptimalRouteSource

TESTDATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testdata")


def test_greedy_source_is_the_planner_verbatim():
    world = load(os.path.join(TESTDATA, "02-four-obstacles.json")).world()
    route = GreedyRouteSource().plan(world)
    direct = search(world, generate_objectives(world))
    assert [s.image_id for s in route.segments] == [s.image_id for s in direct.segments]
    assert [s.cost for s in route.segments] == [s.cost for s in direct.segments]
    assert [s.instructions for s in route.segments] == [s.instructions for s in direct.segments]
    assert route.unreachable == direct.unreachable
    assert route.total_cost == sum(s.cost for s in direct.segments)
    assert route.plan_ms > 0
    assert route.source_name == "Greedy, nearest first"
    assert route.robot is world.robot and route.cell_size == world.cell_size


def test_unreachable_is_carried():
    world = load(os.path.join(TESTDATA, "03-unreachable.json")).world()
    route = GreedyRouteSource().plan(world)
    assert [u.image_id for u in route.unreachable] == [13]


def test_registry_has_greedy_first():
    assert SOURCES[0].name == "Greedy, nearest first"


def test_route_seconds_is_the_sum_of_its_segments():
    route = GreedyRouteSource().plan(load(os.path.join(TESTDATA, "02-four-obstacles.json")).world())
    assert route.seconds == pytest.approx(sum(s.seconds for s in route.segments))


def test_optimal_source_is_registered_second_and_is_no_slower():
    world = load(os.path.join(TESTDATA, "02-four-obstacles.json")).world()
    assert [s.name for s in SOURCES] == ["Greedy, nearest first", "Shortest time"]
    greedy = GreedyRouteSource().plan(world)
    optimal = OptimalRouteSource().plan(world)
    assert optimal.source_name == "Shortest time"
    assert optimal.plan_ms > 0
    assert optimal.robot is world.robot and optimal.cell_size == world.cell_size
    # The optimiser's own ranking: obstacles photographed first, seconds only as a tie-break.
    # A route that abandons an obstacle to save time would not be an improvement.
    assert len(optimal.segments) >= len(greedy.segments)
    if len(optimal.segments) == len(greedy.segments):
        assert optimal.seconds <= greedy.seconds + 1e-9
