"""
The HTTP surface of the two strategies.

Slow on purpose: each ``strategy: "optimal"`` request runs the full leg matrix plus the
re-planned candidates, so this file takes tens of seconds. It is here because the wire
contract is the thing the RPi actually consumes - ``strategy`` optional and defaulting to
optimal, ``seconds`` additive and zero when not verbose - and none of that is visible from
a test of :mod:`pathfinding.search.tour` alone.
"""
import json
import os

from app import create_app

TESTDATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testdata")


def body(name, **extra):
    with open(os.path.join(TESTDATA, name)) as f:
        data = json.load(f)
    data.update(extra)
    return data


def test_default_strategy_is_optimal_and_greedy_is_selectable():
    client = create_app().test_client()
    greedy = client.post("/pathfinding/", json=body("02-four-obstacles.json", strategy="greedy", verbose=True)).json
    optimal = client.post("/pathfinding/", json=body("02-four-obstacles.json", verbose=True)).json
    assert [s["image_id"] for s in greedy["segments"]] == [12, 11, 14, 13]
    assert sorted(s["image_id"] for s in optimal["segments"]) == [11, 12, 13, 14]
    assert sum(s["seconds"] for s in optimal["segments"]) <= sum(s["seconds"] for s in greedy["segments"]) + 1e-9
    assert all(isinstance(s["cost"], int) for s in optimal["segments"])


def test_optimal_is_strictly_faster_than_greedy_on_the_arena_built_for_it():
    """
    The arena where the optimiser earns its keep: greedy loses 14% here.

    ``testdata/02`` cannot show this: greedy's order is already the optimal one there, so
    "optimal <= greedy" holds by equality and would still hold if the strategy did nothing
    at all. Here greedy takes obstacle 14 first because it is nearest and then doubles back
    across the arena, and the recorded numbers are 35.17 s greedy against 30.33 s optimal
    (13.8% quicker, and 678 cm of path against 763).

    Asserted as an inequality rather than against those numbers: the point is the ordering
    of the two strategies, which is a property of the code, while either total moves with
    ``config.ROBOT_SPEED_CM_S``, ``config.TURN_TIME_S`` and the turn geometry - all
    placeholders.
    """
    client = create_app().test_client()
    greedy = client.post("/pathfinding/", json=body("05-greedy-loses.json", strategy="greedy", verbose=True)).json
    optimal = client.post("/pathfinding/", json=body("05-greedy-loses.json", verbose=True)).json
    assert greedy["unreachable"] == optimal["unreachable"] == []
    assert sorted(s["image_id"] for s in greedy["segments"]) == [11, 12, 13, 14]
    assert sorted(s["image_id"] for s in optimal["segments"]) == [11, 12, 13, 14]
    greedy_order = [s["image_id"] for s in greedy["segments"]]
    optimal_order = [s["image_id"] for s in optimal["segments"]]
    assert optimal_order != greedy_order, "the arena exists to make the two strategies disagree"
    assert sum(s["seconds"] for s in optimal["segments"]) < sum(s["seconds"] for s in greedy["segments"])


def test_seconds_is_zero_when_not_verbose_and_bad_strategy_is_422():
    client = create_app().test_client()
    quiet = client.post("/pathfinding/", json=body("01-single-obstacle.json")).json
    assert quiet["segments"][0]["seconds"] == 0
    assert client.post("/pathfinding/", json=body("01-single-obstacle.json", strategy="fastest")).status_code == 422
