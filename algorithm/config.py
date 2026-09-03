# Derived from Pante/SC2079 (AY2023 S2, Group 14). See algorithm/PROVENANCE.md
"""
Every tuneable number the planner uses lives here and nowhere else.

Two rules govern this module:

1. **No project imports.** ``config`` is a leaf. Nothing here may import ``pathfinding.*``,
   so that tools and tests can import ``config`` on its own and mutate it before importing
   anything that reads it.
2. **Consumers read these values at CALL TIME, not at import time.** Never write
   ``from config import STANDOFF_MIN_CM`` in a planner module; write ``import config`` and
   read ``config.STANDOFF_MIN_CM`` inside the function body. Anything that sweeps these
   values depends on it — a coverage tool varies the standoff band by assigning to these
   names at runtime and re-invoking the real ``objective`` module, which import-time binding
   would silently freeze at the first value it saw. See PROVENANCE.md, "Design decisions".

Provenance format on every constant::

    # SOURCE: <team> | <measured|assumed|placeholder> | <note>

``placeholder`` means *nobody has measured this for our car/camera yet* — those are the
numbers the cross-team meeting exists to settle. ``assumed`` means it is a deliberate
algorithm-side choice we own. ``measured`` means it is fixed by the competition rules or by
a measurement already taken.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------------------
# Arena
# ---------------------------------------------------------------------------------------

# The physical edge length of the arena, in centimetres. The arena is square.
# SOURCE: RULES | measured | 200 x 200 cm with virtual (non-physical) boundaries. AGENTS.md 3.2.
ARENA_SIZE_CM = 200

# The number of grid cells along one edge of the search grid.
# ARENA_SIZE_CM // GRID_SIZE is the cell size in cm; at 200/200 one cell is exactly 1 cm.
# The reference service hardcoded World(200, ...) in its controller, so this reproduces it.
# SOURCE: ALGO | assumed | 1 cm cells: slow but exact. The prior-year team's simulator rendered a
#   40x40 grid (5 cm cells) against this 200x200 planner and the two were never reconciled. Our own
#   simulator must render whatever GRID_SIZE says, not a second hardcoded resolution.
GRID_SIZE = 200

# Edge length of the square start zone at the arena's origin, in centimetres. Display only:
# the planner does not keep the robot out of it.
# SOURCE: RULES | measured | 40 x 40 cm bottom-left. MDP briefing p.16, algo deck p.3.
START_ZONE_CM = 40

# Edge length of one obstacle, in centimetres. Also the tablet's grid cell: the Android app
# sends an obstacle as one cell (cx, cy) in 0..19, which the simulator converts to corners.
# SOURCE: RULES | measured | 10 x 10 cm blocks. MDP briefing p.15.
OBSTACLE_SIZE_CM = 10

# ---------------------------------------------------------------------------------------
# Robot
# ---------------------------------------------------------------------------------------

# The square footprint the planner reserves for the robot, in centimetres.
#
# THIS IS THE FOOTPRINT THE PLANNER ACTUALLY USES. It must stay ODD - see the parity rule below.
# The algorithms deck's stated planning footprint is 30 cm, but 30 cannot be planned: the turning
# geometry needs the robot's centre cell to be genuinely central, which holds only when the corner
# extents (north_east - south_west) are even, i.e. when the footprint in cells is odd. The
# reference controller silently bumps an even footprint by +1, so a robot declared as 30 cm has
# always been planned as 31 cm. Declaring 31 makes the constant honest and changes nothing:
# 30 and 31 both plan as 31. Anything that LABELS a footprint with this number - a coverage table
# published to the other teams, above all - now matches what the planner actually did.
# SOURCE: ALGO | assumed | Chassis measures ~18.6-18.8 cm x 23 cm and the algorithms deck is
#   20 x 21 cm; the deck's 30 x 30 is a deliberate safety margin, and 31 is that margin rounded up
#   to the nearest plannable (odd) size. AGENTS.md 3.1.
ROBOT_FOOTPRINT_CM = 31


def planned_footprint_cm(footprint_cm: int) -> int:
    """
    The footprint the planner will actually use for a requested footprint, in centimetres.

    A square robot is only symmetric about its centre cell when its size in cells is odd, so an
    even request is rounded up by one. Callers that LABEL a footprint - the coverage tool above
    all - must label it with this, not with what was asked for, or they report a number the
    planner never used. ``Robot.planned`` is the corner-wise form of the same rule and is what
    everything that builds a Robot goes through.

        >>> planned_footprint_cm(30), planned_footprint_cm(31)
        (31, 31)
    """
    return footprint_cm if footprint_cm % 2 else footprint_cm + 1


# The default starting pose: direction plus the south-west and north-east corners, in cm.
# Corners are INCLUSIVE, so a 31 cm robot spans 0..30 - an extent of 30, which is even, so
# Robot.planned's odd-extent bump does not fire and this pose is planned exactly as written.
# SOURCE: RULES | measured | Start zone is 40 x 40 cm in the bottom-left corner at origin (0, 0),
#   robot facing north. AGENTS.md 3.1.
START_POSE = {
    "direction": "NORTH",
    "south_west": (0, 0),
    "north_east": (ROBOT_FOOTPRINT_CM - 1, ROBOT_FOOTPRINT_CM - 1),
}

# The physical chassis, (width across, length along heading) in centimetres. Drawn by the
# simulator inside the planning footprint; the planner never uses it.
# SOURCE: STM | assumed | 18.6-18.8 cm wide, 23 cm plate, from the briefing photo (p.9).
#   Re-measure with the camera mount fitted.
ROBOT_BODY_CM = (19, 23)

# Straight-line speed at competition speed, in centimetres per second. Used ONLY by the
# simulator to turn a path length into an estimated duration; the planner costs in cm.
# SOURCE: STM | placeholder | NOT MEASURED. 30 is a guess. Update together with
#   TURN_RADIUS_CM, which must be measured at the same speed.
ROBOT_SPEED_CM_S = 30

# ---------------------------------------------------------------------------------------
# Goal-pose generation (world/objective.py)
#
# A goal pose is not a single point: it is a band of standoff distances crossed with a
# lateral tolerance. These three numbers decide how forgiving the planner is, and the
# coverage tool sweeps them. Change them at runtime, never by editing a planner module.
# ---------------------------------------------------------------------------------------

# Closest the robot's leading face may sit to the obstacle face it is photographing, in cm.
# SOURCE: CV | placeholder | The reference used a 25-30 cm band. AGENTS.md states the standoff three
#   mutually inconsistent ways (~20 cm camera optimum vs. a 25-30 cm goal band vs. two different
#   representations in 7.2). CV must pick one against the real lens. AGENTS.md 3.1.
STANDOFF_MIN_CM = 25

# Furthest the robot's leading face may sit from that obstacle face, in cm. Exclusive bound.
# SOURCE: CV | placeholder | Upper end of the same unreconciled 25-30 cm band. Needs CV sign-off.
STANDOFF_MAX_CM = 30

# How far the goal pose may slide sideways along the obstacle face, in cm, in each direction.
# Widening this buys reachability at the cost of off-centre images.
# SOURCE: ALGO | assumed | Reference value. Should grow as the robot/obstacle size ratio grows.
LATERAL_TOLERANCE_CM = 10

# Extra lateral slack, IN GRID CELLS, granted only to an obstacle that touches the arena boundary.
# Such an obstacle has less free space around it, so the planner accepts more off-centre poses.
# UNITS: cells, not centimetres - the reference added this after the cm-to-cell conversion and the
#   behaviour is preserved verbatim. At the default 1 cm cell size the two are identical.
# SOURCE: ALGO | assumed | Reference value, applied once per obstacle (see Fix 3).
BOUNDARY_LATERAL_BONUS_CELLS = 2

# ---------------------------------------------------------------------------------------
# Grid inflation (world/world.py)
#
# Obstacles and the arena boundary are inflated by the robot's half-extent plus these
# margins, so the search can treat the robot as a single point.
# ---------------------------------------------------------------------------------------

# Extra margin added around every obstacle beyond the robot half-extent, in centimetres.
# SOURCE: ALGO | assumed | Reference value. The rules require 30 cm straight-line clearance between
#   obstacles; this 6 cm sits on top of the 15 cm robot half-extent. AGENTS.md 3.2.
OBSTACLE_CLEARANCE_CM = 6

# Adjustment applied to the boundary keep-out band, in centimetres. NEGATIVE: it *relaxes* the
# boundary by 1 cm, because the arena boundary is virtual and costs nothing to clip.
# SOURCE: ALGO | assumed | Reference value. Floor division keeps it at -1 for any cell size.
BOUNDARY_CLEARANCE_ADJUST_CM = -1

# ---------------------------------------------------------------------------------------
# Motion primitives (search/turn.py, search/instructions.py, search/segment.py)
# ---------------------------------------------------------------------------------------

# Turning radius per turn instruction, in centimetres. Keyed by TurnInstruction's string values,
# so both config.TURN_RADIUS_CM["FORWARD_LEFT"] and config.TURN_RADIUS_CM[TurnInstruction.
# FORWARD_LEFT] resolve (TurnInstruction is a str enum whose values equal its names). The dict is
# keyed by string rather than by the enum so that this module stays free of project imports.
# SOURCE: STM | placeholder | 39/40/37/39 are the PRIOR-YEAR team's measurements on THEIR car. The
#   asymmetry is real and large, and radius grows with speed. Re-measure all four at competition
#   speed on our chassis before trusting any plan. Do NOT fall back to the "~25 cm nominal" figure.
#   AGENTS.md 3.1.
TURN_RADIUS_CM = {
    "FORWARD_LEFT": 39,
    "FORWARD_RIGHT": 40,
    "BACKWARD_LEFT": 37,
    "BACKWARD_RIGHT": 39,
}

# Offset applied to the pivot point of a turn, in centimetres, to compensate for the fact that the
# turning geometry treats the robot as a point at its centre.
# SOURCE: ALGO | assumed | Reference value, undocumented there. Effectively a fudge factor; it
#   should disappear once turning is rebuilt on proper Dubins curves.
TURN_PIVOT_OFFSET_CM = 3

# The straight-line move lengths, IN GRID CELLS, the search may take in one step. Each entry
# becomes one candidate neighbour, so more entries means a finer but slower search.
# SOURCE: ALGO | assumed | Reference offered exactly one chunk length, 5 cells.
STRAIGHT_CHUNK_CELLS = (5,)

# ---------------------------------------------------------------------------------------
# Image recognition
# ---------------------------------------------------------------------------------------

# Lowest accepted obstacle identifier. Inclusive.
# SOURCE: RULES | measured | In Task 1 the image on an obstacle is unknown until CV reads it, so
#   this field identifies the OBSTACLE, not the image. The tablet numbers obstacles 1-8
#   (checklist C.6, C.9 "TARGET, <Obstacle Number>, <Target ID>"; android branch Encoder.kt
#   sends "ADD,B<id>,..."). The planner never uses the value beyond echoing it. 1-40 accepts
#   both obstacle numbers and, for hand-written arenas, real image ids 11-40.
IMAGE_ID_MIN = 1

# Highest accepted obstacle identifier. Inclusive.
# SOURCE: RULES | measured | See IMAGE_ID_MIN. 36-40 are the arrows and stop marker.
IMAGE_ID_MAX = 40

# Seconds the robot stands still at each obstacle for capture and inference. Simulator clock only.
# SOURCE: CV | placeholder | NOT MEASURED. 2 s is a guess.
CAPTURE_DWELL_S = 2.0

# ---------------------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------------------

# Task 1 time limit, in seconds. The simulator shows its estimate against this.
# SOURCE: RULES | measured | 6 minutes for Task 1 (3 for Task 2). MDP briefing p.17.
TASK_1_TIME_LIMIT_S = 360

# ---------------------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------------------

# Interface the pathfinding service binds to.
# SOURCE: RPI | assumed | The reference hardcoded their lab machine's IP, 192.168.14.13, which is
#   meaningless off their network. Binding all interfaces is the portable equivalent; the RPi
#   reaches us by whatever address our host actually has.
SERVER_HOST = "0.0.0.0"

# Port the pathfinding service listens on.
# SOURCE: RPI | placeholder | The reference disagreed with itself: app.py bound 5001 while its own
#   README, and the simulator client's hardcoded http://localhost:5000, both said 5000. 5000 is
#   what every client actually calls. Confirm with RPi before demo day.
SERVER_PORT = 5000

# Directory the service writes each incoming request to, one timestamped JSON file per request.
# Relative paths resolve against the process's working directory, so where the artefacts land
# depends on where the server was started from. Both diagnostics are best-effort: a failure to
# write one is logged and never fails the request.
# SOURCE: ALGO | assumed | The reference hardcoded '.replay' in the controller. Named here so a
#   deployment can redirect it off the repo, and so tests can point it at a temporary directory.
REPLAY_DIR = ".replay"

# File the service writes the ASCII grid picture of the latest plan to. Overwritten every request.
# SOURCE: ALGO | assumed | The reference hardcoded 'dump.txt' in the controller.
DUMP_PATH = "dump.txt"
