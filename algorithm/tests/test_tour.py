import functools
import logging
import math
import os

import pytest

import config
from pathfinding import cost
from pathfinding.report import UnreachableReason
from pathfinding.search import tour
from pathfinding.search.search import search
from pathfinding.search.segment import reach, segment
from pathfinding.world.objective import generate_objectives
from pathfinding.world.primitives import Direction, Point
from pathfinding.world.world import Obstacle, Robot, World
from simulator.arena import load

TESTDATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testdata")
INF = math.inf


@functools.lru_cache(maxsize=None)
def arena(name: str):
    """The world and its goal poses. Cached: several tests want the same arena."""
    world = load(os.path.join(TESTDATA, name)).world()
    return world, generate_objectives(world)


@functools.lru_cache(maxsize=None)
def plans(name: str):
    """Greedy and optimal plans for one arena. Cached: plan_optimal costs 20+ s per arena."""
    world, generated = arena(name)
    return search(world, generated), tour.plan_optimal(world, generated)


def assert_no_worse_than_greedy(greedy, optimal) -> None:
    """
    plan_optimal's guarantee, in the shape ``tour._score`` compares: obstacles first, then
    seconds. Fewer seconds is only an improvement at an equal obstacle count - a route that
    photographs one more obstacle wins however long it takes.
    """
    assert len(optimal.segments) >= len(greedy.segments)
    if len(optimal.segments) == len(greedy.segments):
        greedy_seconds = sum(s.seconds for s in greedy.segments)
        optimal_seconds = sum(s.seconds for s in optimal.segments)
        assert optimal_seconds <= greedy_seconds + 1e-9, (optimal_seconds, greedy_seconds)


def boxed_in() -> World:
    """
    smoke.py's boxed-in arena: 11 and 12 wall the start pose into a pocket it cannot leave.

    Both have goal poses, so they are NO_PATH rather than NO_OBJECTIVES, and neither has a
    finite entry in the start row of the leg matrix.
    """
    robot = Robot.planned(
        Direction(config.START_POSE["direction"]),
        Point(*config.START_POSE["south_west"]),
        Point(*config.START_POSE["north_east"]),
    )
    return World(config.GRID_SIZE, robot, [
        Obstacle(Direction.EAST, Point(40, 0), Point(49, 9), 11),
        Obstacle(Direction.NORTH, Point(0, 40), Point(9, 49), 12),
    ])


def test_best_order_finds_the_known_optimum():
    #      0    1    2    3
    m = [[0,   1,  10,  10],
         [0,   0,   1,  10],
         [0,  10,   0,   1],
         [0,   1,  10,   0]]
    assert tour.best_order(m) == [1, 2, 3]


def test_best_order_prefers_a_longer_first_leg_when_the_total_is_smaller():
    m = [[0,   1,   5],
         [0,   0,  10],
         [0,   1,   0]]
    assert tour.best_order(m) == [2, 1]          # 5 + 1 = 6 beats 1 + 10 = 11


def test_best_order_returns_none_without_a_complete_tour():
    m = [[0, 1, INF],
         [0, 0, INF],
         [0, 1, 0]]
    assert tour.best_order(m) is None


def test_best_order_falls_back_to_greedy_above_the_cap():
    n = tour.MAX_EXHAUSTIVE + 1
    m = [[abs(i - j) for j in range(n + 1)] for i in range(n + 1)]
    order = tour.best_order(m)
    assert sorted(order) == list(range(1, n + 1))
    assert order[0] == 1                          # greedy from node 0 picks the nearest


def test_candidate_orders_are_every_complete_order_cheapest_bound_first():
    #      0    1    2    3
    m = [[0,   1,  10,  10],
         [0,   0,   1,  10],
         [0,  10,   0,   1],
         [0,   1,  10,   0]]
    candidates = tour.candidate_orders(m)

    assert sorted(order for _, order in candidates) == [
        [1, 2, 3], [1, 3, 2], [2, 1, 3], [2, 3, 1], [3, 1, 2], [3, 2, 1],
    ]
    assert [bound for bound, _ in candidates] == sorted(bound for bound, _ in candidates)
    assert candidates[0] == (3, [1, 2, 3])           # 1 + 1 + 1, the matrix optimum
    for bound, order in candidates:
        assert bound == sum(m[a][b] for a, b in zip([0] + order, order))


def test_candidate_orders_skips_incomplete_orders_and_respects_the_limit():
    m = [[0, 1, INF],
         [0, 0, INF],
         [0, 1,   0]]
    assert tour.candidate_orders(m) == []            # nothing joins 1 to 2 either way

    m = [[0,   1,   5],
         [0,   0,  10],
         [0,   1,   0]]
    assert [order for _, order in tour.candidate_orders(m)] == [[2, 1], [1, 2]]   # 6, then 11
    assert [order for _, order in tour.candidate_orders(m, limit=7)] == [[2, 1]]
    assert tour.candidate_orders(m, limit=6) == []    # the limit is exclusive
    assert [order for _, order in tour.candidate_orders(m, over=[2])] == [[2]]


def test_largest_feasible_subset_keeps_every_node_when_a_tour_exists():
    m = [[0,   1,  10,  10],
         [0,   0,   1,  10],
         [0,  10,   0,   1],
         [0,   1,  10,   0]]
    assert tour.largest_feasible_subset(m) == ([1, 2, 3], [])


def test_largest_feasible_subset_drops_the_first_node_and_maps_the_rest():
    # Node 1 is reachable only from itself, so no complete tour includes it. Dropping it
    # leaves [2, 3] active, and the sub-matrix's own indices 1, 2 must map back to those
    # ORIGINAL node indices - the case that hides an off-by-one when the dropped node is
    # not the last one.
    m = [[0,   INF,  1,  2],
         [0,     0,  1,  1],
         [0,   INF,  0,  1],
         [0,   INF,  1,  0]]
    assert tour.largest_feasible_subset(m) == ([2, 3], [1])


def test_largest_feasible_subset_keeps_as_many_nodes_as_it_can_when_no_tour_exists():
    # Every node is reachable from 0 (2 and 3 only via 1), but nothing joins 2 to 3, so no
    # order visits all three. Two is the most any order can visit, and dropping a node with
    # few finite entries first - the design doc's heuristic - gives up all three instead.
    m = [[0,   1,  INF, INF],
         [0,   0,    1,   1],
         [0, INF,    0, INF],
         [0, INF,  INF,   0]]
    order, dropped = tour.largest_feasible_subset(m)
    assert (order, dropped) == ([1, 2], [3])
    assert m[0][order[0]] < INF and all(m[a][b] < INF for a, b in zip(order, order[1:]))


def test_largest_feasible_subset_drops_everything_when_nothing_is_reachable():
    m = [[0, INF, INF],
         [0,   0,   1],
         [0,   1,   0]]
    assert tour.largest_feasible_subset(m) == ([], [1, 2])


def test_reach_matches_single_goal_costs_from_the_start():
    world, generated = arena("02-four-obstacles.json")
    start = world.robot.vector
    reached = reach(world, {start}, generated.objectives, cost.TIME_SECONDS)
    assert set(reached) == set(generated.objectives)
    for obstacle, poses in generated.objectives.items():
        single = segment(world, start, {obstacle: poses}, weights=cost.TIME_SECONDS)
        assert single is not None
        assert reached[obstacle] == pytest.approx(single[1])


def test_reach_omits_obstacles_it_cannot_reach():
    world = boxed_in()
    generated = generate_objectives(world)
    assert len(generated.objectives) == 2
    assert reach(world, {world.robot.vector}, generated.objectives, cost.TIME_SECONDS) == {}


def test_leg_matrix_shape_and_diagonal():
    world, generated = arena("02-four-obstacles.json")
    nodes, m = tour.leg_matrix(world, generated)
    assert len(nodes) == 4 and len(m) == 5 and all(len(row) == 5 for row in m)
    assert all(m[i][i] == 0 for i in range(5))
    assert all(m[0][j] < INF for j in range(1, 5))


def test_plan_optimal_is_no_slower_than_greedy_and_partitions():
    # The property holds on every arena, not just this one, because greedy's own route is one
    # of the routes plan_optimal scores. It is a _score comparison, though, not a seconds one:
    # at least as many obstacles photographed, and no slower only when the counts are equal -
    # a route that photographs MORE obstacles is the better one even if it takes longer.
    greedy, optimal = plans("02-four-obstacles.json")
    assert sorted(s.image_id for s in optimal.segments) == [11, 12, 13, 14]
    assert optimal.unreachable == []
    assert_no_worse_than_greedy(greedy, optimal)
    assert all(s.instructions[-1].value == "CAPTURE_IMAGE" for s in optimal.segments)


def test_plan_optimal_on_testdata_02_costs_what_it_has_always_cost():
    # Baseline, captured 2026-09-03 from this planner: 4 obstacles, 41.50 s of driving. Not an
    # independent oracle - it is here so that a change to the cost model, the candidate search
    # or the leg re-planning becomes visible instead of silent.
    greedy, optimal = plans("02-four-obstacles.json")
    world, generated = arena("02-four-obstacles.json")

    assert [s.image_id for s in optimal.segments] == [12, 11, 14, 13]
    assert sum(s.seconds for s in optimal.segments) == pytest.approx(41.50, abs=0.01)
    assert sum(s.seconds for s in greedy.segments) == pytest.approx(41.50, abs=0.01)

    photographed = [s.image_id for s in optimal.segments]
    reported = [u.image_id for u in optimal.unreachable]
    assert sorted(photographed + reported) == sorted(o.image_id for o in world.obstacles)
    assert not set(photographed) & set(reported)


def test_plan_optimal_is_not_slower_than_greedy_on_the_five_obstacle_arena():
    # The arena built to break an optimiser that trusts its own lower bound: the matrix
    # prefers 12,11,14,15,13 (53.00 s bound) over greedy's 12,11,15,14,13 (54.00 s), and those
    # re-plan to 66.83 s and 62.33 s. Picking the best-bound order and stopping loses 7.2%;
    # scoring re-planned candidates against greedy's own route cannot.
    greedy, optimal = plans("04-five-obstacles.json")
    world, _ = arena("04-five-obstacles.json")

    assert_no_worse_than_greedy(greedy, optimal)
    assert sum(s.seconds for s in optimal.segments) < 66.83   # what the bare matrix bound picks

    photographed = [s.image_id for s in optimal.segments]
    reported = [u.image_id for u in optimal.unreachable]
    assert sorted(photographed + reported) == sorted(o.image_id for o in world.obstacles)
    assert optimal.unreachable == []
    assert all(s.instructions[-1].value == "CAPTURE_IMAGE" for s in optimal.segments)


def test_route_continues_past_a_leg_that_fails_from_the_arrival_pose(monkeypatch):
    # The matrix prices a leg from ANY pose in an obstacle's set; the robot stands on one of
    # them, so a leg can fail even where the matrix says it cannot. That must cost the one
    # obstacle, not the rest of the route.
    world, generated = arena("02-four-obstacles.json")
    nodes = list(generated.objectives)
    real = tour.segment
    calls = []

    def flaky(*args, **kwargs):
        calls.append(1)
        return None if len(calls) == 2 else real(*args, **kwargs)

    monkeypatch.setattr(tour, "segment", flaky)
    segments = tour._route(world, generated, nodes, [1, 2, 3, 4])

    assert [n.image_id for n in nodes] == [11, 12, 13, 14]
    assert len(calls) == 4                    # every leg attempted, in spite of the failures
    assert 12 not in {s.image_id for s in segments}         # the injected failure, lost
    assert [s.image_id for s in segments] == [11, 13]
    # 14 is missing for real, not by injection: the fourth call ran the actual search and it
    # found nothing from the pose leg 13 ended at, even though the leg matrix prices 13 -> 14
    # at 20.50 s from 13's pose SET. That is the arrival-pose gap this test exists for, and it
    # is why plan_optimal scores several orders instead of trusting one.


def test_plan_optimal_partitions_when_a_leg_fails_from_the_arrival_pose(monkeypatch):
    # Same failure, end to end. Both planners are blinded to obstacle 11's legs, so it has
    # goal poses and finite matrix entries but no drivable leg: it must come back NO_PATH, and
    # segments plus unreachable must still account for every obstacle exactly once.
    world = load(os.path.join(TESTDATA, "03-unreachable.json")).world()
    generated = generate_objectives(world)
    real = tour.segment

    def blind(w, initial, objectives, **kwargs):
        if any(o.image_id == 11 for o in objectives):
            return None
        return real(w, initial, objectives, **kwargs)

    monkeypatch.setattr(tour, "segment", blind)
    monkeypatch.setattr("pathfinding.search.search.segment", blind)
    result = tour.plan_optimal(world, generated)

    assert result.segments == []
    assert {(u.image_id, u.reason) for u in result.unreachable} == {
        (11, UnreachableReason.NO_PATH),             # goal poses and a matrix leg, no real leg
        (13, UnreachableReason.NO_OBJECTIVES),       # no goal pose at all
    }
    accounted = sorted([s.image_id for s in result.segments] + [u.image_id for u in result.unreachable])
    assert accounted == sorted(o.image_id for o in world.obstacles)


def test_plan_optimal_warns_that_a_capped_search_is_not_a_proven_optimum(monkeypatch, caplog):
    # With room for one re-plan the search cannot exhaust arena 04's 120 orders, so the answer
    # is the best of those tried. Saying so is the point: an unqualified "optimal" that is not
    # one is exactly the silent failure this planner exists to remove.
    world, generated = arena("04-five-obstacles.json")
    monkeypatch.setattr(tour, "MAX_REPLANS", 1)

    with caplog.at_level(logging.WARNING, logger="pathfinding.search.tour"):
        result = tour.plan_optimal(world, generated)

    assert len(result.segments) == 5 and result.unreachable == []
    assert any("not a proven optimum" in r.message for r in caplog.records), caplog.text

    # And with the real cap the same arena IS proven, so the warning is about the cap and not
    # about this arena.
    _, uncapped = plans("04-five-obstacles.json")
    assert sum(s.seconds for s in uncapped.segments) <= sum(s.seconds for s in result.segments) + 1e-9


def test_plan_optimal_keeps_no_objectives_and_reports_no_path():
    world = load(os.path.join(TESTDATA, "03-unreachable.json")).world()
    result = tour.plan_optimal(world, generate_objectives(world))
    assert [s.image_id for s in result.segments] == [11]
    assert {(u.image_id, u.reason) for u in result.unreachable} == {(13, UnreachableReason.NO_OBJECTIVES)}


def test_plan_optimal_reports_no_path_for_obstacles_no_tour_can_include():
    world = boxed_in()
    result = tour.plan_optimal(world, generate_objectives(world))
    assert result.segments == []
    assert {(u.image_id, u.reason) for u in result.unreachable} == {
        (11, UnreachableReason.NO_PATH),
        (12, UnreachableReason.NO_PATH),
    }


def test_plan_optimal_rejects_a_generation_for_another_world():
    # Its own world and generation, never the cached ones: this test mutates them.
    world = load(os.path.join(TESTDATA, "02-four-obstacles.json")).world()
    generated = generate_objectives(world)
    generated.objectives.pop(next(iter(generated.objectives)))
    with pytest.raises(ValueError):
        tour.plan_optimal(world, generated)
