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
# SOURCE: ALGO | assumed | Derived from ROBOT_FOOTPRINT_CM, itself assumed. The zone it sits in is
#   rules: start zone is 40 x 40 cm in the bottom-left corner at origin (0, 0),
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

# Straight-line speed at competition speed, in centimetres per second. Together with TURN_TIME_S
# it sets the time model the shortest-time optimiser ranks routes by, and the simulator clock.
# The greedy planner still costs in cm and does not read it.
# SOURCE: STM | placeholder | NOT MEASURED. 30 is a guess. Update together with
#   TURN_RADIUS_CM, which must be measured at the same speed.
ROBOT_SPEED_CM_S = 30 # 

# ---------------------------------------------------------------------------------------
# Goal-pose generation (world/objective.py)
#
# A goal pose is not a single point: it is a band of standoff distances crossed with a
# lateral tolerance. These three numbers decide how forgiving the planner is, and the
# coverage tool sweeps them. Change them at runtime, never by editing a planner module.
# ---------------------------------------------------------------------------------------

# Closest the robot's leading face may sit to the obstacle face it is photographing, in cm.
# "Leading face" is the edge of the 31 cm PLANNING footprint, 15 cm ahead of the robot's centre,
# so CENTRE-to-face = 15 + this. The spec is given from the centre: 30 cm optimal. A band of
# 13..17 here puts the centre 28-32 cm from the face, centred on 30; the physical nose
# (ROBOT_BODY_CM is 23 long, so 11.5 cm ahead of centre) lands 16.5-20.5 cm from it. Lowering
# this also lowers the clear space a face needs in front of it - see the arena rule in
# docs/protocols/algorithm-service.md, which must be re-measured when this moves.
# SOURCE: CV | measured | 30 cm from the middle of the robot, 2026-09-18. Was 25-30 (reference).
STANDOFF_MIN_CM = 13

# Furthest the robot's leading face may sit from that obstacle face, in cm. Exclusive bound.
# SOURCE: CV | measured | See STANDOFF_MIN_CM: 13..17 inclusive, a 5 cm band like the original.
STANDOFF_MAX_CM = 18

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
# SOURCE: STM | measured | 2026-09-18, on our chassis, from a tape mark: centre displacement after
#   one 90 degree turn command (dx = dy = R for a clean quarter arc). Left turns are much tighter
#   than right - a 14 cm gap - and it is a property of the car, not noise. Speed setting, floor
#   surface and the straight-run figures (ROBOT_SPEED_CM_S, TURN_TIME_S) were NOT recorded with
#   these; re-measure all of it together if the speed setting changes.
#   These are the QUARTER-TURN radii. The 45 degree commands have their own table below.
TURN_RADIUS_CM = {
    "FORWARD_LEFT": 42,
    "FORWARD_RIGHT": 56,
    "BACKWARD_LEFT": 41,
    "BACKWARD_RIGHT": 55,
}

# How far the car's centre moves ALONG ITS ORIGINAL HEADING after one 45 DEGREE turn command, in
# centimetres - the tape-measure number, entered as measured. TurnInstruction.radius derives the
# 45 degree turning radius from it (R = this / sin 45 = this / 0.7071), and every consumer of a
# *_45 token's radius - the traced arc, its cost, its arc length - reads that. A 45 is therefore
# NOT modelled as the quarter-turn radius held for half the arc; it was, and the measured car did
# not agree, covering 7-19% less ground than that model predicts.
# SOURCE: STM | measured | 2026-09-18, same session and speed as TURN_RADIUS_CM. Derived radii
#   today: 34 / 52 / 38 / 45 cm (FL / FR / BL / BR). The quarter turns need no such table because
#   a 90 degree arc's displacement along the heading IS its radius.
TURN_45_DISPLACEMENT_CM = {
    "FORWARD_LEFT": 24,
    "FORWARD_RIGHT": 37,
    "BACKWARD_LEFT": 27,
    "BACKWARD_RIGHT": 32,
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

# The longest single FORWARD/BACKWARD command, in centimetres, that may be put on the wire. The
# search merges consecutive same-direction chunks with no upper bound, so a clear run across the
# arena arrives as one large command: measured 2026-09-17, a lone obstacle at (100,80) facing
# NORTH gives a 140 cm FORWARD, and 300 random 4-8 obstacle arenas produced one of 160 cm against
# a hard ceiling of 170 (the robot centre is confined to a 171 cm band, driven in 5 cm chunks).
# Anything at or above 170 therefore disables the cap; 0 disables it explicitly.
#
# This is a WIRE-FORMAT limit, not a planning one. Splitting a command does not move the robot
# differently - same cells, same cost, same seconds - it only chunks the command stream, so the
# number is the STM owner's to set from their calibration and costs nothing here to change.
# SOURCE: STM | placeholder | NOT MEASURED. 100 is the figure the STM owner proposed on
#   2026-09-17 ("we can j do 2 100 cm fw") before running their 0-200 accuracy sweep. Note that
#   93% of straights this planner emits are under 80 cm, so the sweep matters far more at the
#   short end than at this one.
MAX_STRAIGHT_CM = 100

# Seconds the robot takes for one 90 degree turn at competition speed, arc included. The time
# model charges this per turn and cells/ROBOT_SPEED_CM_S per straight cell; the optimiser and the
# simulator clock both use it.
# SOURCE: STM | placeholder | NOT MEASURED. 3.0 is a guess: a 40 cm radius arc is 63 cm, about
#   2 s at 30 cm/s, plus steering. Measure together with TURN_RADIUS_CM and ROBOT_SPEED_CM_S.
TURN_TIME_S = 3.0

# Whether the search may drive and turn through the four diagonal headings, using the 45
# degree turns as well as the quarter turns. False is the four-heading planner exactly as it
# was. EXPERIMENTAL: the STM has to be able to execute and stop a 45 degree turn for any plan
# made with this on to survive contact with the robot.
# SOURCE: ALGO | assumed | Measured 2026-09-04 on branch kejun-experimental-algo: the
#   shortest-time planner saves 22% on testdata 02 and 34% on 04. Switched ON 2026-09-18 once the
#   STM owner had driven and measured 45 degree turns in all four directions; those are
#   TURN_45_DISPLACEMENT_CM, separate from the quarter turns'. The RPi must decode the four *_45 tokens.
DIAGONAL_HEADINGS = True

# Whether the search may rotate on the spot, by shuffling: full steering lock forward, full lock
# back the other way, both strokes swinging the nose the same way. INDEPENDENT of
# DIAGONAL_HEADINGS, and composes with it - the diagonals decide which headings exist, this
# decides whether the search may reach one without travelling to it. With the diagonals off the
# only pivot that lands on a heading is a 90; with them on, 45s become reachable as well. False is
# the planner exactly as it is today, in both of those modes.
# SOURCE: ALGO | assumed | OFF until the STM owner confirms the car can execute a shuffle turn
#   and stop on its heading. The manoeuvre exists only because the chassis is Ackermann-steered and
#   has no zero-radius solution; see docs/superpowers/specs/2026-09-11-pivot-turns-design.md.
PIVOT_TURNS = False

# Seconds the robot takes for one 45 degree pivot, the whole shuffle included; a 90 costs twice
# this. The time model charges it per pivot exactly as it charges TURN_TIME_S per turn, and the
# simulator clock follows.
# SOURCE: STM | placeholder | NOT MEASURED. The STM owner offered 2.0 on 2026-09-11 as a working
#   figure so that the cost model could be written against something - it is a statement of
#   intent, not a stopwatch reading. Measure it at competition speed, alongside TURN_TIME_S and
#   with the stroke count the firmware actually drives, since PIVOT_STROKES_PER_45 moves it.
PIVOT_TIME_S = 2.0

# Strokes the car shuffles through per 45 degrees of pivot: full lock forward, full lock back,
# repeated. MUST BE EVEN - one backward stroke for every forward one - because a pivot that ends
# mid-shuffle stops a whole stroke away from where the planner placed it with its heading still
# exactly right, which is a failure nothing downstream can see.
#
# More strokes is not better. Against the radii below, one 45 degree pivot drifts 3.5 cm at 2
# strokes, 6.4 cm at 4 and 7.3 cm at 6, while the swept box it needs barely moves (51 x 58 cm
# against 53 x 51 cm). That drift is INHERENT, and in particular it is not the forward/backward
# radius asymmetry: the two strokes of a pair turn about circles that are not concentric, so the
# pair does not close. Matching TURN_RADIUS_CM's 40 forward-right against its 37 backward-left
# buys about 12% of it and no more. It is systematic rather than noise: it accumulates
# with every extra stroke instead of averaging out, which is also why the planner can model it.
# SOURCE: ALGO | assumed | 2 is the algo-side choice that minimises drift at the PLACEHOLDER
#   radii, and is therefore only as trustworthy as they are. Re-derive it once the STM owner
#   measures TURN_RADIUS_CM, and confirm the firmware drives the count the planner assumed.
PIVOT_STROKES_PER_45 = 2

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
