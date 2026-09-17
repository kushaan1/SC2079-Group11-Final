"""
The Android payload shape, which reaches this service unmodified.

Android talks to the RPi over Bluetooth and the RPi relays the bytes without translating
them, so what the tablet emits *is* the request body. It is a different shape from the
prior-year one: ``id`` rather than ``image_id``, one point rather than two corners, single
letter faces, no robot block, and coordinates in 10 cm GRID CELLS rather than centimetres.

The cells are the dangerous part. Read as centimetres, ``{"x": 10, "y": 6}`` puts an
obstacle at 10..19 x 6..15 - inside the robot's own 0..30 start box - so the mistake is not
merely a wrong route but a physically impossible arena, and nothing in the old schema would
have rejected it. Hence :func:`test_cells_are_multiplied_into_centimetres`, which pins the
factor of ten against a hand-computed arena rather than against the converter's own output.

The canonical shape is still accepted: ``testdata/*.json``, every fixture in the other test
modules and the simulator all speak it, and the simulator is three graded checklist items.
"""
import json
import os

import pytest

from app import create_app

TESTDATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testdata")


@pytest.fixture(name="client")
def _client():
    return create_app().test_client()


def android(**extra):
    """The two-obstacle arena from the Android owner's own sample, verbatim."""
    body = {
        "command": "imageRec",
        "algorithm": "greedy",
        "obstacles": [
            {"id": 1, "x": 10, "y": 6, "face": "N"},
            {"id": 2, "x": 14, "y": 15, "face": "E"},
        ],
    }
    body.update(extra)
    return body


def canonical(**extra):
    """
    The same arena hand-written in the canonical shape.

    Computed by hand, NOT by running the converter: cell 10 -> 100..109 cm, cell 6 ->
    60..69 cm, and the robot in the south-west corner facing north. If the converter and
    this literal ever disagree, the converter is what changed.
    """
    body = {
        "strategy": "greedy",
        "robot": {
            "direction": "NORTH",
            "south_west": {"x": 0, "y": 0},
            "north_east": {"x": 30, "y": 30},
        },
        "obstacles": [
            {
                "image_id": 1,
                "direction": "NORTH",
                "south_west": {"x": 100, "y": 60},
                "north_east": {"x": 109, "y": 69},
            },
            {
                "image_id": 2,
                "direction": "EAST",
                "south_west": {"x": 140, "y": 150},
                "north_east": {"x": 149, "y": 159},
            },
        ],
    }
    body.update(extra)
    return body


def test_android_payload_is_planned(client):
    response = client.post("/pathfinding/", json=android())
    assert response.status_code == 200
    accounted = [s["obstacle_id"] for s in response.json["segments"]]
    accounted += [u["obstacle_id"] for u in response.json["unreachable"]]
    assert sorted(accounted) == [1, 2], "every obstacle sent must come back in exactly one list"


def test_cells_are_multiplied_into_centimetres(client):
    """
    The factor of ten, pinned against a hand-computed arena.

    This is the assertion that would catch the units bug: if the converter passed cells
    through as centimetres, both obstacles would land inside the robot's start box and the
    two responses could not match.
    """
    from_android = client.post("/pathfinding/", json=android()).json
    from_canonical = client.post("/pathfinding/", json=canonical()).json
    assert from_android == from_canonical


def test_each_face_letter_maps_to_its_cardinal(client):
    """
    All four letters, against an obstacle standing in open arena.

    The position matters. Against a wall two of the four faces come back unreachable, and a
    letter mapped to the wrong cardinal would then match the wrong canonical request by
    accident - both being the same empty plan. At cell (10, 10) every face is photographable
    and the four routes genuinely differ, which is what the last assertion pins.
    """
    plans = {}
    for letter, cardinal in (("N", "NORTH"), ("E", "EAST"), ("S", "SOUTH"), ("W", "WEST")):
        from_android = client.post("/pathfinding/", json=android(
            obstacles=[{"id": 1, "x": 10, "y": 10, "face": letter}])).json
        from_canonical = client.post("/pathfinding/", json=canonical(obstacles=[{
            "image_id": 1,
            "direction": cardinal,
            "south_west": {"x": 100, "y": 100},
            "north_east": {"x": 109, "y": 109},
        }])).json
        assert from_android == from_canonical, f"face {letter!r} must plan as {cardinal}"
        assert from_android["segments"], f"face {letter!r} should be photographable at (10, 10)"
        plans[letter] = json.dumps(from_android, sort_keys=True)

    assert len(set(plans.values())) == 4, "four different faces must give four different routes"


def test_robot_starts_in_the_south_west_corner_facing_north(client):
    """
    Android sends no robot block, so the start pose is a convention rather than an input.

    Pinned by driving the first leg: a route planned from the south-west corner must begin
    somewhere inside that corner, which a differently-placed robot would not.
    """
    response = client.post("/pathfinding/", json=android()).json
    first = response["segments"][0]["path"][0]
    assert first["direction"] == "NORTH"
    assert first["x"] <= 30 and first["y"] <= 30


def test_algorithm_field_selects_the_strategy(client):
    greedy = client.post("/pathfinding/", json=android(algorithm="greedy")).json
    optimal = client.post("/pathfinding/", json=android(algorithm="optimal")).json
    assert [s["obstacle_id"] for s in greedy["segments"]]
    assert sum(s["seconds"] for s in optimal["segments"]) <= sum(s["seconds"] for s in greedy["segments"]) + 1e-9


def test_turn_in_place_is_refused_rather_than_silently_downgraded(client):
    """
    ``turnInPlace`` is deferred, and deferring it quietly would be the expensive mistake.

    Planning greedy for it would hand back a route that looks fine and ignores the setting,
    and the first evidence would be the robot driving arcs on competition day. A 422 naming
    the value costs one failed request in testing instead.
    """
    response = client.post("/pathfinding/", json=android(algorithm="turnInPlace"))
    assert response.status_code == 422
    assert "turnInPlace" in json.dumps(response.json)


def test_unknown_command_is_refused(client):
    response = client.post("/pathfinding/", json=android(command="fastestCar"))
    assert response.status_code == 422
    assert "fastestCar" in json.dumps(response.json)


def test_cell_outside_the_grid_is_refused(client):
    """Cell 20 is off a 20x20 grid; as centimetres it would have been a legal coordinate."""
    response = client.post("/pathfinding/", json=android(
        obstacles=[{"id": 1, "x": 20, "y": 6, "face": "N"}]))
    assert response.status_code == 422


def test_duplicate_ids_are_refused(client):
    response = client.post("/pathfinding/", json=android(obstacles=[
        {"id": 1, "x": 10, "y": 6, "face": "N"},
        {"id": 1, "x": 14, "y": 15, "face": "E"},
    ]))
    assert response.status_code == 422


def test_empty_obstacle_list_is_refused(client):
    assert client.post("/pathfinding/", json=android(obstacles=[])).status_code == 422


def test_canonical_requests_still_work(client):
    """
    The old shape is not retired: the simulator and every testdata fixture speak it, and the
    simulator carries checklist items B.1 through B.3.
    """
    with open(os.path.join(TESTDATA, "01-single-obstacle.json")) as f:
        body = json.load(f)
    response = client.post("/pathfinding/", json=body)
    assert response.status_code == 200
    assert "segments" in response.json


def test_the_response_calls_it_obstacle_id(client):
    """
    The response names the field for what it actually carries.

    The value is the tablet's obstacle number, and the image on that obstacle is unknown until
    CV reads it three hops later - so ``image_id`` named a value that cannot exist at the time
    it is sent. Renamed on the way out only. The canonical request still accepts ``image_id``,
    because that is what ``openapi.json``, the testdata fixtures and the simulator speak.
    """
    response = client.post("/pathfinding/", json=android(obstacles=[
        {"id": 1, "x": 10, "y": 10, "face": "N"},   # open arena, plans
        {"id": 2, "x": 14, "y": 15, "face": "E"},   # three cells too close to the east wall
    ])).json

    assert [s["obstacle_id"] for s in response["segments"]] == [1]
    assert [u["obstacle_id"] for u in response["unreachable"]] == [2]
    assert "image_id" not in response["segments"][0], "the old name must not linger alongside"
    assert "image_id" not in response["unreachable"][0]


# ---------------------------------------------------------------------------------------
# Mid-run re-planning: an optional robot pose in, the stopping pose out. Built for checklist
# A.5 - the car is standing at a face, CV saw a bull's-eye, and the RPi needs a route to the
# next face FROM WHERE THE CAR IS. Both ends are in centimetres and both are the CAR'S CENTRE,
# so the `end` of one segment is fed back as the `robot` of the next request unchanged.
# ---------------------------------------------------------------------------------------


def test_tablet_shape_accepts_a_robot_centre(client):
    """
    ``robot`` on the tablet shape is the car's centre in cm, expanded to a 31 cm box.

    Pinned against a hand-written canonical request, not the converter: centre (105, 160)
    is corners (90, 145)-(120, 175). Sending the centre rather than corners is deliberate -
    it is exactly what `end` returns, so the RPi can hand one back as the other.
    """
    from_tablet = client.post("/pathfinding/", json=android(
        robot={"x": 105, "y": 160, "direction": "SOUTH"},
        obstacles=[{"id": 1, "x": 10, "y": 10, "face": "E"}])).json
    from_canonical = client.post("/pathfinding/", json=canonical(
        robot={"direction": "SOUTH",
               "south_west": {"x": 90, "y": 145}, "north_east": {"x": 120, "y": 175}},
        obstacles=[{"image_id": 1, "direction": "EAST",
                    "south_west": {"x": 100, "y": 100}, "north_east": {"x": 109, "y": 109}}])).json
    assert from_tablet == from_canonical
    assert from_tablet["segments"], "the arena was chosen so the face is photographable"


def test_robot_centre_too_close_to_the_wall_is_refused(client):
    """Centre x=5 puts the car's west edge at -10; a silent clamp would plan from a lie."""
    response = client.post("/pathfinding/", json=android(
        robot={"x": 5, "y": 100, "direction": "NORTH"}))
    assert response.status_code == 422
    assert "robot.x" in json.dumps(response.json), "the 422 must name the offending field"


def test_every_segment_reports_where_the_car_stops(client):
    """
    ``end`` is the capture pose - the car's centre and heading when CAPTURE_IMAGE fires.

    Present with ``verbose: false`` (the mode the tablet will actually run in), and equal to
    the last ``path`` vector when verbose is on, so the two views of the route agree.
    """
    quiet = client.post("/pathfinding/", json=android(verbose=False)).json
    loud = client.post("/pathfinding/", json=android(verbose=True)).json
    assert quiet["segments"], "sample arena plans at least one obstacle"
    for q, l in zip(quiet["segments"], loud["segments"]):
        assert set(q["end"]) == {"x", "y", "direction"}
        assert q["end"] == l["end"] == l["path"][-1]


def test_end_pose_round_trips_as_the_next_robot(client):
    """
    The A.5 loop, end to end: plan to one face, hand `end` back as `robot`, plan the next.

    No arithmetic in between - that is the property the RPi relies on.
    """
    first = client.post("/pathfinding/", json=android(verbose=False,
        obstacles=[{"id": 1, "x": 10, "y": 10, "face": "N"}])).json
    end = first["segments"][0]["end"]

    retry = client.post("/pathfinding/", json=android(verbose=False,
        robot=end,
        obstacles=[{"id": 1, "x": 10, "y": 10, "face": "E"}]))
    assert retry.status_code == 200
    assert [s["obstacle_id"] for s in retry.json["segments"]] == [1]
    # The retry genuinely starts at the capture pose: its first cell is within a step of it.
    loud = client.post("/pathfinding/", json=android(verbose=True,
        robot=end, obstacles=[{"id": 1, "x": 10, "y": 10, "face": "E"}])).json
    first_cell = loud["segments"][0]["path"][0]
    assert abs(first_cell["x"] - end["x"]) <= 15 and abs(first_cell["y"] - end["y"]) <= 15


def test_stub_mode_reports_no_end_pose(client):
    """The stub fabricates no geometry, so it must not fabricate a pose the RPi might drive from."""
    stub = create_app(stub=True).test_client()
    response = stub.post("/pathfinding/", json=android()).json
    assert all(s["end"] is None for s in response["segments"])
