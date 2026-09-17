import pytest

from rpi.model import Arc, Capture, Pose, Straight
from rpi.planner_client import PlannerClient, PlannerError, parse_instruction, parse_plan

SAMPLE = {
    "segments": [
        {
            "image_id": 2,
            "cost": 88,
            "seconds": 3.83,
            "instructions": [
                {"move": "FORWARD", "amount": 15},
                "FORWARD_RIGHT",
                {"move": "BACKWARD", "amount": 10},
                "FORWARD_LEFT_45",
                "CAPTURE_IMAGE",
            ],
            "path": [{"direction": "NORTH", "x": 15, "y": 15}, {"direction": "EAST", "x": 55, "y": 65}],
        }
    ],
    "unreachable": [{"image_id": 3, "reason": "NO_OBJECTIVES"}],
}


class FakeResponse:
    def __init__(self, status_code=200, body=None, headers=None, text=""):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}
        self.text = text

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append((url, json, timeout))
        if self.error is not None:
            raise self.error
        return self.response


# --- parsing ---------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ({"move": "FORWARD", "amount": 15}, Straight("FORWARD", 15)),
    ({"move": "BACKWARD", "amount": 10}, Straight("BACKWARD", 10)),
    ("FORWARD_LEFT", Arc("FORWARD_LEFT", 90)),
    ("BACKWARD_RIGHT", Arc("BACKWARD_RIGHT", 90)),
    ("FORWARD_LEFT_45", Arc("FORWARD_LEFT", 45)),
    ("CAPTURE_IMAGE", Capture()),
])
def test_parse_instruction(raw, expected):
    assert parse_instruction(raw) == expected


@pytest.mark.parametrize("raw", ["SPIN", {"move": "SIDEWAYS", "amount": 5}, 42, {"amount": 5}])
def test_parse_instruction_rejects_unknown_tokens(raw):
    with pytest.raises((ValueError, KeyError, TypeError)):
        parse_instruction(raw)


def test_parse_plan():
    plan = parse_plan(SAMPLE)
    segment = plan.segments[0]
    assert segment.image_id == 2
    assert segment.instructions[-1] == Capture()
    assert segment.end_pose == Pose(5.0, 6.0, 90.0)     # path[-1] = (55, 65) cm facing EAST
    assert segment.seconds == 3.83
    assert plan.unreachable == ((3, "NO_OBJECTIVES"),)


def test_parse_plan_needs_a_path():
    body = {"segments": [dict(SAMPLE["segments"][0], path=[])], "unreachable": []}
    with pytest.raises(ValueError):
        parse_plan(body)


# --- client --------------------------------------------------------------------------

def test_plan_posts_to_the_endpoint_and_parses():
    session = FakeSession(FakeResponse(200, SAMPLE))
    client = PlannerClient("http://laptop:5000/", 5.0, session=session)
    assert client.configured is True
    plan = client.plan({"verbose": True})
    assert session.calls == [("http://laptop:5000/pathfinding/", {"verbose": True}, 5.0)]
    assert plan.segments[0].image_id == 2


def test_unconfigured_client_fails_without_a_request():
    session = FakeSession(FakeResponse(200, SAMPLE))
    client = PlannerClient("", 5.0, session=session)
    assert client.configured is False
    with pytest.raises(PlannerError) as info:
        client.plan({})
    assert "not configured" in str(info.value)
    assert session.calls == []


def test_connection_error_is_a_planner_error():
    import requests
    session = FakeSession(error=requests.ConnectionError("refused"))
    with pytest.raises(PlannerError) as info:
        PlannerClient("http://laptop:5000", 5.0, session=session).plan({})
    assert "unreachable" in str(info.value)


def test_422_carries_the_servers_message():
    body = [{"loc": ["obstacles", 0, "image_id"], "msg": "image_id must be 1-40", "type": "value_error"}]
    session = FakeSession(FakeResponse(422, body))
    with pytest.raises(PlannerError) as info:
        PlannerClient("http://laptop:5000", 5.0, session=session).plan({})
    assert "image_id must be 1-40" in str(info.value)


def test_500_without_json_reports_the_status():
    session = FakeSession(FakeResponse(500, None, text="Internal Server Error"))
    with pytest.raises(PlannerError) as info:
        PlannerClient("http://laptop:5000", 5.0, session=session).plan({})
    assert "500" in str(info.value)


def test_stub_planner_is_refused_unless_allowed():
    response = FakeResponse(200, SAMPLE, headers={"X-MDP-Stub": "true"})
    with pytest.raises(PlannerError) as info:
        PlannerClient("http://laptop:5000", 5.0, session=FakeSession(response)).plan({})
    assert "stub" in str(info.value)
    PlannerClient("http://laptop:5000", 5.0, session=FakeSession(response), allow_stub=True).plan({})


def test_malformed_response_is_a_planner_error():
    session = FakeSession(FakeResponse(200, {"segments": [{"image_id": 1}]}))
    with pytest.raises(PlannerError):
        PlannerClient("http://laptop:5000", 5.0, session=session).plan({})
