"""
`segments[].poses` and `segments[].centre_path`: the car's centre after EVERY instruction, and its
path through the whole segment, so the RPi never dead-reckons.

The tablet's ROBOT marker was drawn from the RPi's own motion model between captures - one that
carried last year's radii and a wrong 45 degree formula - and it drifted 15-38 cm from the
planner's car within a segment before snapping to `end`. With one pose per instruction the RPi
looks the position up instead, and its copy of the turning radii can go. `centre_path` is what
it draws the route from: the CENTRE through the turns too, where `path` is the rear pivot's
cells. Both are verbose-only (the RPi always asks verbose) and both are empty in stub mode.

The invariants are checked in three modes because the planner that SHIPS is not the one the rest
of the suite is pinned to: `config.DIAGONAL_HEADINGS` is on in `config.py`, while conftest's
autouse fixture pins every unmarked test to four headings. `MODES` runs each invariant with four
headings, with eight, and with eight plus pivots. The fixture reads a param's marks from
`request.keywords`, and `_plan` asserts the flags it set rather than trusting that it did. FOUR
plans no pivot in any of those modes, eight plus pivots included, so
`test_the_invariants_hold_through_a_pivot` repeats them on arena 04, which does.
"""
import json
import math
import os

import pytest

import config
from app import create_app
from pathfinding.search.search import Segment
from pathfinding.world.primitives import Direction, Point, Vector
from pathfinding.world.world import Obstacle, Robot, World
from pathfinding_controller import PathfindingResponseSegment

TESTDATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testdata")
CARDINAL = {"NORTH": (0, 1), "EAST": (1, 0), "SOUTH": (0, -1), "WEST": (-1, 0)}
FOUR = {"command": "imageRec", "algorithm": "optimal", "verbose": True, "obstacles": [
    {"id": 1, "x": 10, "y": 6, "face": "N"}, {"id": 2, "x": 4, "y": 12, "face": "S"},
    {"id": 3, "x": 12, "y": 3, "face": "W"}, {"id": 4, "x": 6, "y": 10, "face": "E"}]}
START = {"x": 15, "y": 15, "direction": "NORTH"}
MODES = (
    "four",
    pytest.param("eight", marks=pytest.mark.diagonals),
    pytest.param("eight+pivots", marks=[pytest.mark.diagonals, pytest.mark.pivots]),
)


@pytest.fixture(name="client")
def _client():
    return create_app().test_client()


def _plan(client, mode):
    """FOUR, planned in `mode`, after checking the autouse fixture really switched that mode on."""
    assert config.DIAGONAL_HEADINGS == (mode != "four"), mode
    assert config.PIVOT_TURNS == (mode == "eight+pivots"), mode
    return client.post("/pathfinding/", json=FOUR).json


def _walk(plan):
    """(previous pose, instruction, pose after) for every instruction, across the whole run."""
    prev = START
    for s in plan["segments"]:
        for instr, pose in zip(s["instructions"], s["poses"]):
            yield prev, instr, pose
            prev = pose


@pytest.mark.parametrize("mode", MODES)
def test_one_pose_per_instruction_and_the_last_is_end(client, mode):
    plan = _plan(client, mode)
    assert plan["segments"]
    for s in plan["segments"]:
        assert len(s["poses"]) == len(s["instructions"])
        if s["end"] is None:
            # The car did not move. See test_a_segment_that_does_not_move_reports_where_the_car_stands.
            assert s["instructions"] == ["CAPTURE_IMAGE"]
        else:
            assert s["poses"][-1] == s["end"]
        assert all(set(p) == {"x", "y", "direction"} for p in s["poses"])


@pytest.mark.parametrize("mode", MODES)
def test_a_cardinal_straight_moves_the_pose_by_exactly_its_amount(client, monkeypatch, mode):
    monkeypatch.setattr(config, "MAX_STRAIGHT_CM", 20)
    checked = 0
    for prev, instr, pose in _walk(_plan(client, mode)):
        if isinstance(instr, dict) and prev["direction"] in CARDINAL:
            dx, dy = CARDINAL[prev["direction"]]
            sign = 1 if instr["move"] == "FORWARD" else -1
            assert (pose["x"] - prev["x"], pose["y"] - prev["y"]) == (dx * instr["amount"] * sign, dy * instr["amount"] * sign), (prev, instr, pose)
            assert pose["direction"] == prev["direction"]
            checked += 1
    assert checked >= 6


def test_a_turn_changes_the_heading_and_capture_holds_still(client):
    turns = captures = 0
    for prev, instr, pose in _walk(client.post("/pathfinding/", json=FOUR).json):
        if instr == "CAPTURE_IMAGE":
            assert pose == prev
            captures += 1
        elif isinstance(instr, str):
            assert pose["direction"] != prev["direction"]
            turns += 1
    assert turns and captures == 4


def test_no_pose_puts_the_footprint_on_an_obstacle(client):
    half = config.ROBOT_FOOTPRINT_CM // 2
    boxes = [(o["x"] * 10, o["y"] * 10, o["x"] * 10 + 9, o["y"] * 10 + 9) for o in FOUR["obstacles"]]
    for _, _, p in _walk(client.post("/pathfinding/", json=FOUR).json):
        for x0, y0, x1, y1 in boxes:
            assert not (p["x"] - half <= x1 and p["x"] + half >= x0 and p["y"] - half <= y1 and p["y"] + half >= y0), (p, (x0, y0))


@pytest.mark.parametrize("mode", MODES)
def test_centre_path_starts_at_the_start_pose_and_visits_every_pose(client, monkeypatch, mode):
    """Every pose, split-straight pieces included, is literally a point of the path, and the
    poses come in driving order: the RPi's 'pose lies on centre_path' check is a lookup, not a
    nearest-point search, and walking the poses walks the path forwards."""
    monkeypatch.setattr(config, "MAX_STRAIGHT_CM", 20)
    plan = _plan(client, mode)
    prev = START
    for s in plan["segments"]:
        path = [(p["x"], p["y"]) for p in s["centre_path"]]
        assert path[0] == (prev["x"], prev["y"]), (s["obstacle_id"], path[0], prev)
        assert all(set(p) == {"x", "y"} for p in s["centre_path"])
        at = 0
        for pose in s["poses"]:
            # Searched from the previous pose's index, never from 0, so a pose that is only
            # BEHIND the one before it fails. "At or after", because CAPTURE_IMAGE repeats the
            # last pose.
            point = (pose["x"], pose["y"])
            assert point in path[at:], (s["obstacle_id"], pose, "missing, or out of driving order")
            at = path.index(point, at)
        # `end` is None when the car did not move, and then it stands where its one pose says.
        last = s["end"] if s["end"] is not None else s["poses"][-1]
        assert path[-1] == (last["x"], last["y"])
        prev = last


@pytest.mark.parametrize("mode", MODES)
def test_centre_path_points_are_at_most_the_spacing_apart_through_turns(client, mode):
    plan = _plan(client, mode)
    limit = config.CENTRE_PATH_SPACING_CM                # on the INTEGER output, as the RPi sees it
    turned = 0
    for s in plan["segments"]:
        path = [(p["x"], p["y"]) for p in s["centre_path"]]
        straight_ends = {(p["x"], p["y"]) for p, i in zip(s["poses"], s["instructions"]) if isinstance(i, dict)}
        for a, b in zip(path, path[1:]):
            if b in straight_ends:
                continue                                  # a straight may be just its two ends
            assert math.dist(a, b) <= limit, (s["obstacle_id"], a, b)
            turned += 1
    assert turned > 0, "the arena must contain turns for this to test anything"


@pytest.mark.parametrize("mode", MODES)
def test_centre_path_never_repeats_a_point(client, mode):
    plan = _plan(client, mode)
    for s in plan["segments"]:
        path = [(p["x"], p["y"]) for p in s["centre_path"]]
        assert all(a != b for a, b in zip(path, path[1:])), s["obstacle_id"]


@pytest.mark.diagonals
@pytest.mark.pivots
def test_the_invariants_hold_through_a_pivot(client, monkeypatch):
    """
    The pivot branch of `Segment.compress`'s `centre_path` - the shuffle's own centre cells,
    taken from the Pivot move - is reached by no test above, because FOUR plans no pivot in any
    of the MODES. Arena 04 does under eight headings plus pivots (two on its first leg and one on
    its fourth, measured 2026-09-25), so the same invariants run on it here: one pose per
    instruction, the last on `end`; every pose a point of `centre_path`, in driving order; no
    repeated point; and at most `config.CENTRE_PATH_SPACING_CM` between points except along a
    straight. The cap splits the straights, as above, so their pieces' poses are checked too.
    """
    assert config.DIAGONAL_HEADINGS and config.PIVOT_TURNS
    monkeypatch.setattr(config, "MAX_STRAIGHT_CM", 20)
    with open(os.path.join(TESTDATA, "04-five-obstacles.json")) as f:
        body = json.load(f)
    body["verbose"] = True
    plan = client.post("/pathfinding/", json=body).json
    assert any(isinstance(i, str) and i.startswith("PIVOT_") for s in plan["segments"] for i in s["instructions"]), (
        "arena 04 is here because the planner pivots on it; if it no longer does, this test no "
        "longer reaches the pivot branch and needs an arena that does")

    sw, ne = body["robot"]["south_west"], body["robot"]["north_east"]
    prev = ((sw["x"] + ne["x"]) // 2, (sw["y"] + ne["y"]) // 2)
    limit = config.CENTRE_PATH_SPACING_CM
    for s in plan["segments"]:
        assert len(s["poses"]) == len(s["instructions"]), s["obstacle_id"]
        if s["end"] is None:
            assert s["instructions"] == ["CAPTURE_IMAGE"]
        else:
            assert s["poses"][-1] == s["end"]
        path = [(p["x"], p["y"]) for p in s["centre_path"]]
        assert path[0] == prev, (s["obstacle_id"], path[0], prev)
        at = 0
        for instruction, pose in zip(s["instructions"], s["poses"]):
            point = (pose["x"], pose["y"])
            assert point in path[at:], (s["obstacle_id"], pose, "missing, or out of driving order")
            reached = path.index(point, at)
            if isinstance(instruction, str) and instruction.startswith("PIVOT_"):
                # The shuffle's own cells, not a chord. A pivot barely moves the car, so the
                # spacing check below would pass one drawn straight from its start to its end.
                assert reached - at > 1, (s["obstacle_id"], instruction, "drawn as a chord")
            at = reached
        assert path[-1] == (s["poses"][-1]["x"], s["poses"][-1]["y"])
        assert all(a != b for a, b in zip(path, path[1:])), s["obstacle_id"]
        straight_ends = {(p["x"], p["y"]) for p, i in zip(s["poses"], s["instructions"]) if isinstance(i, dict)}
        for a, b in zip(path, path[1:]):
            assert b in straight_ends or math.dist(a, b) <= limit, (s["obstacle_id"], a, b)
        prev = path[-1]


def test_not_verbose_omits_both_and_changes_nothing_else(client):
    quiet = client.post("/pathfinding/", json=dict(FOUR, verbose=False)).json
    loud = client.post("/pathfinding/", json=FOUR).json
    for q, l in zip(quiet["segments"], loud["segments"]):
        assert q["poses"] == [] and q["centre_path"] == []
        assert q["obstacle_id"] == l["obstacle_id"]
        assert q["instructions"] == l["instructions"]
        assert q["end"] == l["end"]
        assert q["cost"] == 0 and q["seconds"] == 0.0 and q["path"] == []
    assert quiet["unreachable"] == loud["unreachable"]


@pytest.mark.parametrize("name", sorted(f for f in os.listdir(TESTDATA) if f.endswith(".json")))
def test_every_testdata_arena_still_plans_with_the_fields(client, name):
    with open(os.path.join(TESTDATA, name)) as f:
        body = json.load(f)
    body["verbose"] = True
    response = client.post("/pathfinding/", json=body)
    assert response.status_code == 200, response.data
    plan = response.json
    assert len(plan["segments"]) + len(plan["unreachable"]) == len(body["obstacles"])
    for s in plan["segments"]:
        assert len(s["poses"]) == len(s["instructions"]) and s["centre_path"]


def test_stub_mode_reports_neither():
    plan = create_app(stub=True).test_client().post("/pathfinding/", json=FOUR).json
    assert all(s["poses"] == [] and s["centre_path"] == [] for s in plan["segments"])


def test_a_segment_that_does_not_move_reports_where_the_car_stands():
    """
    The car can already be standing on the next obstacle's goal pose - two adjacent obstacles
    facing the same way can share one - and then its segment has no moves at all. `end` is None
    there, as it always was: it is read off the segment's vectors, and there are none. `poses`
    still has its one entry, for CAPTURE_IMAGE, and that entry is where the car stands (the
    previous segment's last pose, or the request's `robot` for the first segment);
    `centre_path` is that single point. A client reads `end: null` as
    "did not move" and takes the position from `poses`.

    Built directly rather than through a request: which arenas hand the planner a shared goal
    pose shifts with every recalibration, and what is under test is the contract of `compress`
    and `from_segment`, not the search.
    """
    world = World(config.GRID_SIZE, Robot.planned(Direction.NORTH, Point(0, 0), Point(30, 30)),
                  [Obstacle(Direction.NORTH, Point(90, 100), Point(99, 109), 2)])
    start = Vector(Direction.SOUTH, 96, 148)            # facing the obstacle's north face
    segment = Segment.compress(world, (world.obstacles[0], 0.0, [(start, None)]))
    wire = PathfindingResponseSegment.from_segment(True, segment).model_dump(mode="json")

    assert wire["end"] is None
    assert wire["instructions"] == ["CAPTURE_IMAGE"]
    assert wire["poses"] == [{"direction": "SOUTH", "x": 96, "y": 148}]
    assert wire["centre_path"] == [{"x": 96, "y": 148}]
