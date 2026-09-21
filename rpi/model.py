"""Value types shared by every module. No logic, no imports from the package."""

from dataclasses import dataclass
from typing import Optional, Tuple, Union

FACES = ("N", "E", "S", "W")
DIRECTIONS = ("NORTH", "EAST", "SOUTH", "WEST")
ARC_KINDS = ("FORWARD_LEFT", "FORWARD_RIGHT", "BACKWARD_LEFT", "BACKWARD_RIGHT")


@dataclass(frozen=True)
class Obstacle:
    obstacle_id: int          # 1-8, the tablet's block number
    x: int                    # arena cell 0-19
    y: int
    face: Optional[str]       # one of FACES, or None when not set


@dataclass(frozen=True)
class Pose:
    x: float                  # cell index of the footprint centre; decimals allowed
    y: float
    heading: float            # degrees clockwise from north, [0, 360)


START_POSE = Pose(1.0, 1.0, 0.0)


@dataclass(frozen=True)
class Straight:
    move: str                 # "FORWARD" | "BACKWARD"
    cm: int


@dataclass(frozen=True)
class Arc:
    kind: str                 # one of ARC_KINDS
    degrees: int              # 90, or 45 in the planner's diagonal mode


@dataclass(frozen=True)
class Capture:
    """Stop and photograph. Ends every planner segment."""


Instruction = Union[Straight, Arc, Capture]


@dataclass(frozen=True)
class Segment:
    image_id: int
    instructions: Tuple[Instruction, ...]
    end_pose: Pose            # the robot's centre at the capture point, from path[-1]
    seconds: float            # the planner's estimate; 0.0 if it did not say


@dataclass(frozen=True)
class Plan:
    segments: Tuple[Segment, ...]
    unreachable: Tuple[Tuple[int, str], ...]   # (image_id, reason)


@dataclass(frozen=True)
class Verdict:
    status: str               # "target" | "bullseye" | "no_detection" | "error"
    competition_id: Optional[int] = None
    confidence: Optional[float] = None
