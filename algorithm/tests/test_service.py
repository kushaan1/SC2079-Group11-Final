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

import pytest

from app import create_app
from pathfinding.search.instructions import PivotInstruction
from pathfinding_controller import PathfindingResponse

TESTDATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testdata")

# The published schema, as committed. `docs/protocols/algorithm-service.md` says it is generated
# from the running server and never hand-edited, so the tests below read it rather than a copy.
OPENAPI = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "docs", "protocols", "openapi.json",
)

PIVOT_TOKENS = [instruction.value for instruction in PivotInstruction]


def body(name, **extra):
    with open(os.path.join(TESTDATA, name)) as f:
        data = json.load(f)
    data.update(extra)
    return data


def test_default_strategy_is_optimal_and_greedy_is_selectable():
    client = create_app().test_client()
    greedy = client.post("/pathfinding/", json=body("02-four-obstacles.json", strategy="greedy", verbose=True)).json
    optimal = client.post("/pathfinding/", json=body("02-four-obstacles.json", verbose=True)).json
    assert [s["obstacle_id"] for s in greedy["segments"]] == [12, 11, 14, 13]
    assert sorted(s["obstacle_id"] for s in optimal["segments"]) == [11, 12, 13, 14]
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
    assert sorted(s["obstacle_id"] for s in greedy["segments"]) == [11, 12, 13, 14]
    assert sorted(s["obstacle_id"] for s in optimal["segments"]) == [11, 12, 13, 14]
    greedy_order = [s["obstacle_id"] for s in greedy["segments"]]
    optimal_order = [s["obstacle_id"] for s in optimal["segments"]]
    assert optimal_order != greedy_order, "the arena exists to make the two strategies disagree"
    assert sum(s["seconds"] for s in optimal["segments"]) < sum(s["seconds"] for s in greedy["segments"])


def test_seconds_is_zero_when_not_verbose_and_bad_strategy_is_422():
    client = create_app().test_client()
    quiet = client.post("/pathfinding/", json=body("01-single-obstacle.json")).json
    assert quiet["segments"][0]["seconds"] == 0
    assert client.post("/pathfinding/", json=body("01-single-obstacle.json", strategy="fastest")).status_code == 422


def tokens(payload):
    """Every instruction in the response that is a bare enum token rather than a MoveInstruction."""
    return [
        instruction
        for segment in payload["segments"]
        for instruction in segment["instructions"]
        if isinstance(instruction, str)
    ]


@pytest.mark.pivots
def test_a_pivot_reaches_the_wire_and_round_trips():
    """
    With ``PIVOT_TURNS`` on, a planned pivot must survive the response model.

    This is the whole of the wire change, and the failure it fixes was a 500 rather than a bad
    route: ``PathfindingResponseSegment.instructions`` named a union of three types, the search
    handed it a fourth, and pydantic refused the segment before the response was ever built. On
    this arena the planner pivots on two of the four legs, so the flag could not be switched on
    at all until the union was widened.

    Round-tripping, rather than only reading the JSON, is what pins the contract: it asserts the
    emitted document re-parses into the declared union and the token comes back as a
    :class:`PivotInstruction` member, which is the property a client generated from
    ``openapi.json`` will hold the service to. Reading the string alone would also pass if the
    field were loosened to a bare ``str``.
    """
    client = create_app().test_client()
    response = client.post("/pathfinding/", json=body("02-four-obstacles.json", verbose=True))
    assert response.status_code == 200, response.data

    payload = response.json
    assert [token for token in tokens(payload) if token in PIVOT_TOKENS], (
        "this arena is here because the planner pivots on it; if it no longer does, the test is "
        "vacuous and needs a new arena rather than deleting"
    )

    parsed = PathfindingResponse.model_validate(payload)
    assert parsed.model_dump(mode="json") == payload
    pivots = [
        instruction
        for segment in parsed.segments
        for instruction in segment.instructions
        if isinstance(instruction, PivotInstruction)
    ]
    assert pivots, "a PIVOT_* token must parse back as a PivotInstruction, not as some other member"


def test_the_published_schema_declares_the_pivot_tokens():
    """
    ``openapi.json`` is what the RPi's client is generated from, so a token the planner can emit
    and the schema does not name is a client that rejects a legal response.

    Checked against the live app AND the committed file: the file is generated (see
    ``docs/protocols/algorithm-service.md``), and the only way to know it is not stale is to ask
    the app what it would serve now.

    Deliberately narrow - the pivot tokens and the one union that carries them - rather than a
    whole-document comparison. ``requirements.txt`` sets lower bounds rather than pins, so the
    exact rendering of the rest of the schema moves with whichever flask-openapi3 a teammate
    installed, and a byte comparison would fail on their machine for no contract reason.

    Unmarked on purpose: the schema is static, so the tokens are published whether or not
    ``PIVOT_TURNS`` is on. Publishing them early is the point - the RPi owner can object to the
    names before the flag is switched on rather than after.
    """
    served = create_app().test_client().get("/openapi/openapi.json").json
    with open(OPENAPI) as file:
        committed = json.load(file)

    for schema in (served, committed):
        assert schema["components"]["schemas"]["PivotInstruction"]["enum"] == PIVOT_TOKENS
        instructions = schema["components"]["schemas"]["PathfindingResponseSegment"]["properties"]["instructions"]
        assert {"$ref": "#/components/schemas/PivotInstruction"} in instructions["items"]["anyOf"]

    # Responses widened, requests did not: a caller still cannot ask for a pivot, and the four
    # cardinals are still the only headings a request may name.
    for model in ("PathfindingRequestRobot", "PathfindingRequestObstacle"):
        direction = committed["components"]["schemas"][model]["properties"]["direction"]
        assert direction["enum"] == ["NORTH", "EAST", "SOUTH", "WEST"]
