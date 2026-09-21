"""POST /pathfinding/ on the algorithm service -> Plan (spec §3.3, §5.6)."""

import logging
from typing import Optional

import requests

from rpi.arena import planner_vector_to_pose
from rpi.model import ARC_KINDS, Arc, Capture, Instruction, Plan, Segment, Straight

LOG = logging.getLogger(__name__)


class PlannerError(Exception):
    """What the tablet is told after 'Planner error: '."""


def parse_instruction(raw: object) -> Instruction:
    if isinstance(raw, dict):
        move = raw["move"]
        if move not in ("FORWARD", "BACKWARD"):
            raise ValueError("unknown move %r" % (move,))
        return Straight(move, int(raw["amount"]))
    if raw == "CAPTURE_IMAGE":
        return Capture()
    if isinstance(raw, str):
        kind, degrees = (raw[:-3], 45) if raw.endswith("_45") else (raw, 90)
        if kind in ARC_KINDS:
            return Arc(kind, degrees)
    raise ValueError("unknown instruction %r" % (raw,))


def _obstacle_number(item: dict) -> int:
    """The planner echoes the caller's obstacle number as `obstacle_id` (since
    algorithm commit 974c60f); its openapi fixtures still say `image_id`."""
    return int(item["obstacle_id"] if "obstacle_id" in item else item["image_id"])


def _end_pose(raw: dict):
    """`end` is the capture pose and is reported even when verbose is false;
    older responses only had it as the last `path` vector."""
    end = raw.get("end")
    if end:
        return planner_vector_to_pose(end)
    path = raw.get("path") or []
    if not path:
        raise ValueError("segment %s has no end pose (was verbose false?)" % _obstacle_number(raw))
    return planner_vector_to_pose(path[-1])


def parse_plan(body: dict) -> Plan:
    segments = []
    for raw in body["segments"]:
        segments.append(Segment(
            image_id=_obstacle_number(raw),
            instructions=tuple(parse_instruction(item) for item in raw["instructions"]),
            end_pose=_end_pose(raw),
            seconds=float(raw.get("seconds") or 0.0),
        ))
    unreachable = tuple(
        (_obstacle_number(item), str(item.get("reason", ""))) for item in body.get("unreachable", [])
    )
    return Plan(tuple(segments), unreachable)


def _describe_error(response: object) -> str:
    """The server's own words when it has any, else the HTTP status."""
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, list):
        messages = [str(item.get("msg", item)) for item in body if isinstance(item, dict)]
        if messages:
            return "; ".join(messages)
    if isinstance(body, dict):
        for key in ("message", "detail", "error"):
            if key in body:
                return str(body[key])
    return "HTTP %s" % response.status_code


class PlannerClient:
    def __init__(self, base_url: str, timeout_s: float, session: Optional[object] = None,
                 allow_stub: bool = False) -> None:
        self._base = base_url.rstrip("/")
        self._url = self._base + "/pathfinding/"
        self._timeout_s = timeout_s
        self._session = session or requests.Session()
        self._allow_stub = allow_stub

    @property
    def configured(self) -> bool:
        return bool(self._base)

    def plan(self, request_body: dict) -> Plan:
        if not self.configured:
            raise PlannerError("Planner URL not configured")
        LOG.info("planner request: %s", request_body)
        try:
            response = self._session.post(self._url, json=request_body, timeout=self._timeout_s)
        except requests.RequestException as error:
            raise PlannerError("planner unreachable: %s" % error)
        if response.status_code != 200:
            raise PlannerError(_describe_error(response))
        if response.headers.get("X-MDP-Stub") and not self._allow_stub:
            raise PlannerError("planner is in stub mode; refusing to drive on canned output")
        try:
            body = response.json()
        except ValueError:
            raise PlannerError("planner returned invalid JSON")
        try:
            plan = parse_plan(body)
        except (KeyError, TypeError, ValueError) as error:
            raise PlannerError("planner response not understood: %s" % error)
        LOG.info("planner: %d segment(s), %d unreachable", len(plan.segments), len(plan.unreachable))
        return plan
