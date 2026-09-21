"""Dead reckoning for the tablet's ROBOT marker (spec §5.10).

Straights move along the heading; an arc of radius R through angle t moves the
car R*sin(t) along its heading and R*(1 - cos(t)) to the side it turns toward,
and turns the heading by t (the chord of the arc: R and R at 90 degrees, 0.71R
and 0.29R at 45). The run snaps to the planner's exact pose at the end of every
segment, so an error here never outlives one segment.
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

    r = radii[instr.kind] / CELL_CM
    t = math.radians(instr.degrees)
    along = r * math.sin(t)            # how far along the heading the chord reaches
    across = r * (1.0 - math.cos(t))   # how far it drifts toward the turning side
    fwd = 1.0 if instr.kind.startswith("FORWARD") else -1.0
    lft = 1.0 if instr.kind.endswith("LEFT") else -1.0
    # Forward-left and backward-right rotate anticlockwise (heading decreases);
    # the other two rotate clockwise.
    turn = -instr.degrees if fwd * lft > 0 else instr.degrees
    return Pose(
        pose.x + forward[0] * along * fwd + left[0] * across * lft,
        pose.y + forward[1] * along * fwd + left[1] * across * lft,
        normalise_heading(pose.heading + turn),
    )
