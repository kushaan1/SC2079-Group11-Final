"""The tablet's wire format, both directions. Mirrors docs/protocol.md exactly.

Pure functions. `parse` never raises: a line it does not understand is `Unknown`.
"""

import json
import re
from dataclasses import dataclass
from typing import Optional, Tuple, Union

from rpi.model import FACES, Obstacle, Pose


@dataclass(frozen=True)
class Manual:
    token: str


@dataclass(frozen=True)
class Add:
    obstacle_id: int
    x: int
    y: int


@dataclass(frozen=True)
class Sub:
    obstacle_id: int


@dataclass(frozen=True)
class Face:
    obstacle_id: int
    x: int
    y: int
    face: Optional[str]


@dataclass(frozen=True)
class MoveRobot:
    pose: Pose


@dataclass(frozen=True)
class SendArena:
    obstacles: Tuple[Obstacle, ...]


@dataclass(frozen=True)
class ImageRec:
    algorithm: str
    robot: Optional[Pose]
    obstacles: Tuple[Obstacle, ...]


@dataclass(frozen=True)
class FaceSearch:
    robot: Optional[Pose]
    obstacles: Tuple[Obstacle, ...]


@dataclass(frozen=True)
class BeginFastest:
    """Task 2 start. Forwarded to the STM; nothing else in v1."""


@dataclass(frozen=True)
class Unknown:
    line: str


Inbound = Union[Manual, Add, Sub, Face, MoveRobot, SendArena, ImageRec, FaceSearch, BeginFastest, Unknown]

MANUAL_TOKENS = ("f", "b", "tl", "tr", "sl", "sr", "s")

_ADD = re.compile(r"^ADD,B(\d+),\((\d+),(\d+)\)$")
_SUB = re.compile(r"^SUB,B(\d+)$")
_FACE = re.compile(r"^FACE,B(\d+),\((\d+),(\d+)\),(N|E|S|W|NONE)$")
_MOVE = re.compile(r"^MOVEROBOT,(-?[0-9.]+),(-?[0-9.]+),(-?[0-9.]+)$")


def parse(line: str) -> Inbound:
    raw = line.strip()
    if not raw:
        return Unknown(line)
    if raw.startswith("{"):
        return _parse_json(raw, line)
    if raw in MANUAL_TOKENS:
        return Manual(raw)
    if raw == "beginFastest":
        return BeginFastest()

    m = _ADD.match(raw)
    if m:
        return Add(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _SUB.match(raw)
    if m:
        return Sub(int(m.group(1)))
    m = _FACE.match(raw)
    if m:
        face = None if m.group(4) == "NONE" else m.group(4)
        return Face(int(m.group(1)), int(m.group(2)), int(m.group(3)), face)
    m = _MOVE.match(raw)
    if m:
        try:
            return MoveRobot(Pose(float(m.group(1)), float(m.group(2)), float(m.group(3)) % 360.0))
        except ValueError:
            return Unknown(line)
    return Unknown(line)


def _parse_json(raw: str, line: str) -> Inbound:
    try:
        body = json.loads(raw)
    except ValueError:
        return Unknown(line)
    if not isinstance(body, dict):
        return Unknown(line)
    try:
        obstacles = tuple(_obstacle(item) for item in body.get("obstacles", []))
        robot = _pose(body.get("robot"))
    except (KeyError, TypeError, ValueError, AttributeError):
        return Unknown(line)

    command = body.get("command")
    if command is None:
        return SendArena(obstacles)
    if command == "imageRec":
        return ImageRec(str(body.get("algorithm", "greedy")), robot, obstacles)
    if command == "faceSearch":
        return FaceSearch(robot, obstacles)
    return Unknown(line)


def _obstacle(item: dict) -> Obstacle:
    face = item.get("face")
    if face is not None and face not in FACES:
        raise ValueError("bad face %r" % (face,))
    return Obstacle(int(item["id"]), int(item["x"]), int(item["y"]), face)


def _pose(item: Optional[dict]) -> Optional[Pose]:
    if item is None:
        return None
    return Pose(float(item["x"]), float(item["y"]), float(item["heading"]) % 360.0)


# --- outbound -------------------------------------------------------------------

def msg(text: str) -> str:
    """MSG,<text>. The payload may contain commas; it may never contain a newline."""
    return "MSG," + " ".join(str(text).splitlines())


def target(obstacle_id: int, competition_id: int) -> str:
    return "TARGET,B%d,%d" % (obstacle_id, competition_id)


def robot(pose: Pose) -> str:
    heading = int(round(pose.heading)) % 360
    return "ROBOT,%.2f,%.2f,%d" % (pose.x, pose.y, heading)
