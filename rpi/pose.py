"""Dead reckoning for the tablet's ROBOT marker (spec §5.10).

Deliberately crude: straights move along the heading, arcs displace by the
turn radius on both axes and turn the heading a quarter. The run snaps to the
planner's exact pose at the end of every segment, so an error here never
outlives one segment.
"""

import math
from typing import Dict

from rpi.arena import CELL_CM, normalise_heading
from rpi.model import Arc, Capture, Instruction, Pose, Straight


def advance(pose: Pose, instr: Instruction, radii: Dict[str, int]) -> Pose:
    if isinstance(instr, Capture):
        return pose
    h = math.radians(pose.heading)
    forward = (math.sin(h), math.cos(h))      # unit vector along the heading
    left = (-math.cos(h), math.sin(h))        # unit vector to the robot's left

    if isinstance(instr, Straight):
        d = instr.cm / CELL_CM * (1.0 if instr.move == "FORWARD" else -1.0)
        return Pose(pose.x + forward[0] * d, pose.y + forward[1] * d, pose.heading)

    r = radii[instr.kind] / CELL_CM * (instr.degrees / 90.0)
    fwd = 1.0 if instr.kind.startswith("FORWARD") else -1.0
    lft = 1.0 if instr.kind.endswith("LEFT") else -1.0
    # Forward-left and backward-right rotate anticlockwise (heading decreases);
    # the other two rotate clockwise.
    turn = -instr.degrees if fwd * lft > 0 else instr.degrees
    return Pose(
        pose.x + forward[0] * r * fwd + left[0] * r * lft,
        pose.y + forward[1] * r * fwd + left[1] * r * lft,
        normalise_heading(pose.heading + turn),
    )
