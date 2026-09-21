"""Cells <-> centimetres, faces <-> directions, planner request bodies. Stateless.

The only place these formulas live (spec §5.4). A run start carries its own
obstacles and pose, so nothing here remembers anything.
"""

import logging
from typing import Dict, Iterable, List

from rpi.model import DIRECTIONS, Obstacle, Pose

LOG = logging.getLogger(__name__)

CELL_CM = 10
ROBOT_HALF_CM = 15
ARENA_CM = 200
CENTRE_MIN_CM = ROBOT_HALF_CM                  # 15: a corner may not go below 0
CENTRE_MAX_CM = ARENA_CM - 1 - ROBOT_HALF_CM   # 184: a corner may not reach 200

FACE_TO_DIRECTION = {"N": "NORTH", "E": "EAST", "S": "SOUTH", "W": "WEST"}   # type: Dict[str, str]
DIRECTION_TO_HEADING = {                                                      # type: Dict[str, float]
    "NORTH": 0.0, "NORTHEAST": 45.0, "EAST": 90.0, "SOUTHEAST": 135.0,
    "SOUTH": 180.0, "SOUTHWEST": 225.0, "WEST": 270.0, "NORTHWEST": 315.0,
}


def cells_to_cm(cells: float) -> float:
    """Centre of a cell: cell 0 is 5 cm, cell 1 is 15 cm (protocol.md §3)."""
    return cells * CELL_CM + CELL_CM / 2.0


def cm_to_cells(cm: float) -> float:
    return (cm - CELL_CM / 2.0) / CELL_CM


def normalise_heading(deg: float) -> float:
    return deg % 360.0


def heading_to_direction(heading: float) -> str:
    """Nearest cardinal. The planner only accepts the four in a request."""
    quarter = int(round(normalise_heading(heading) / 90.0)) % 4
    return DIRECTIONS[quarter]


def obstacle_to_planner(o: Obstacle) -> dict:
    if o.face not in FACE_TO_DIRECTION:
        raise ValueError("B%d has no face" % o.obstacle_id)
    sx, sy = o.x * CELL_CM, o.y * CELL_CM
    return {
        "image_id": o.obstacle_id,
        "direction": FACE_TO_DIRECTION[o.face],
        "south_west": {"x": sx, "y": sy},
        "north_east": {"x": sx + CELL_CM - 1, "y": sy + CELL_CM - 1},
    }


def _clamp_centre(cm: float, axis: str) -> int:
    clamped = min(max(cm, CENTRE_MIN_CM), CENTRE_MAX_CM)
    if clamped != cm:
        LOG.info("robot %s centre %.1f cm clamped to %d cm for the planner", axis, cm, clamped)
    return int(round(clamped))


def pose_to_planner_robot(p: Pose) -> dict:
    cx = _clamp_centre(cells_to_cm(p.x), "x")
    cy = _clamp_centre(cells_to_cm(p.y), "y")
    return {
        "direction": heading_to_direction(p.heading),
        "south_west": {"x": cx - ROBOT_HALF_CM, "y": cy - ROBOT_HALF_CM},
        "north_east": {"x": cx + ROBOT_HALF_CM, "y": cy + ROBOT_HALF_CM},
    }


def planner_vector_to_pose(v: dict) -> Pose:
    """A `path` entry (centre in cm + direction) as a tablet pose."""
    return Pose(
        cm_to_cells(float(v["x"])),
        cm_to_cells(float(v["y"])),
        DIRECTION_TO_HEADING[str(v["direction"])],
    )


def to_planner_request(obstacles: Iterable[Obstacle], robot: Pose, strategy: str) -> dict:
    bodies = [obstacle_to_planner(o) for o in obstacles]   # type: List[dict]
    if not bodies:
        raise ValueError("no obstacles")
    return {
        "verbose": True,       # path[-1] is where end poses come from; never false
        "strategy": strategy,
        "robot": pose_to_planner_robot(robot),
        "obstacles": bodies,
    }
