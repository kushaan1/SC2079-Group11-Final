import os

from pathfinding.search.search import search
from pathfinding.world.objective import generate_objectives
from simulator.arena import load
from simulator.routes import SOURCES, GreedyRouteSource

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
