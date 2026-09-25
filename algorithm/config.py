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
# SOURCE: STM | placeholder | NOT MEASURED. 25 is the working figure the algo owner set on
#   2026-09-25 (was 30). Update together with TURN_DISPLACEMENT_CM, which must be measured at the
#   same speed.
ROBOT_SPEED_CM_S = 25

# ---------------------------------------------------------------------------------------
# Goal-pose generation (world/objective.py)
#
# A goal pose is not a single point: it is a band of standoff distances crossed with a
# lateral tolerance. These three numbers decide how forgiving the planner is, and the
# coverage tool sweeps them. Change them at runtime, never by editing a planner module.
# ---------------------------------------------------------------------------------------

# Closest the robot's leading face may sit to the obstacle face it is photographing, in cm.
# "Leading face" is the edge of the 31 cm PLANNING footprint, 15 cm ahead of the robot's centre,
# so CENTRE-to-face = 15 + this. The camera sits at the front of the chassis, ~11.5 cm ahead of
# the centre (ROBOT_BODY_CM is 23 long, lens assumed at the plate's edge), so
# CAMERA-to-face = this + 3.5. The band 12..36 puts the camera 15.5-39.5 cm from the face, which
# is the 15-40 cm the algo owner asked for on 2026-09-25. If the lens is not at the edge, move
# both bounds by the difference. Lowering this also lowers the clear space a face needs in front
# of it - see the arena rule in docs/protocols/algorithm-service.md, which must be re-measured
# when this moves.
# SOURCE: CV | assumed | camera 15-40 cm from the object, algo owner 2026-09-25. Lens offset from
#   the centre mark NOT measured; 11.5 assumed.
STANDOFF_MIN_CM = 12

# Furthest the robot's leading face may sit from that obstacle face, in cm. INCLUSIVE: the band
# is the closed interval [STANDOFF_MIN_CM, STANDOFF_MAX_CM] (PROVENANCE.md, design decisions).
# SOURCE: CV | assumed | See STANDOFF_MIN_CM.
STANDOFF_MAX_CM = 36

# How far the goal pose may slide sideways along the obstacle face, in cm, in each direction.
# Widening this buys reachability at the cost of off-centre images.
# SOURCE: ALGO | assumed | 5 cm, algo owner 2026-09-25 (was 10, the reference value). Should grow
#   as the robot/obstacle size ratio grows.
LATERAL_TOLERANCE_CM = 5

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

# The robot centre's displacement after ONE turn command, in centimetres, straight off the tape:
# (across, along). `along` is measured along the heading the car set off on, positive forward,
# so every backward command is negative; `across` is perpendicular to it, positive toward the
# side the wheels were turned (left for *_LEFT, right for *_RIGHT), which is the side the car
# moved for all eight. Keyed by TurnInstruction's string values, so both
# config.TURN_DISPLACEMENT_CM["FORWARD_LEFT_45"] and config.TURN_DISPLACEMENT_CM[TurnInstruction.
# FORWARD_LEFT_45] resolve. Strings rather than the enum so this module stays free of project
# imports.
#
# Two numbers per command because the model behind a turn has two parameters and one number
# cannot pin both. The car rotates about a point on the LINE of its rear axle (the instantaneous
# centre of rotation); the rear axle's midpoint, the rear pivot, rides a circle of radius R about
# it, and the centre sits L (the lead) ahead of the rear pivot. So after a 90 the centre has moved
# R + L across and R - L along (forward commands) or R - L across and R + L along (backward ones).
# TurnInstruction.fit solves each pair for its own (R, L), and the planner's arc, end pose, arc
# length and costs all derive from that: nothing here is a radius, a 45 is not half a 90, and
# nothing downstream may assume either. The earlier tables held a single centre-to-centre chord
# per command and were read as R, which put every planned 90 about 20-27 cm past the real car -
# see PROVENANCE.md, "The turn model is fitted per command".
# SOURCE: STM | measured | 2026-09-25 by the algo owner, on our chassis at the competition speed
#   setting, centre of the car marked on the floor before and after one command, final heading
#   checked at 90 / 45, one run each. The earlier session's chords (TR90 60, TL90 40.5, BR90 56,
#   BL90 39.6, TR45 32, TL45 21, BR45 34, BL45 24) agree with these pairs within 2 cm on five
#   commands and 5-7 cm on three (TR90, BL90, TL45): that is the car's run-to-run scatter, and
#   the floor on how exact any plan can be. Re-measure all eight together if the speed changes.
TURN_DISPLACEMENT_CM = {
    "FORWARD_LEFT":      (37.0,  15.5),
    "FORWARD_RIGHT":     (47.0,  28.0),
    "BACKWARD_LEFT":     (21.5, -41.0),
    "BACKWARD_RIGHT":    (33.0, -47.0),
    "FORWARD_LEFT_45":   (18.5,  18.0),
    "FORWARD_RIGHT_45":  (21.0,  22.0),
    "BACKWARD_LEFT_45":  ( 4.5, -25.0),
    "BACKWARD_RIGHT_45": ( 6.5, -31.8),
}

# How far apart, in centimetres, consecutive points of a segment's `centre_path` may be along a
# turn. A wire-format number for the tablet's route drawing, not a planning one: the search
# never reads it.
# SOURCE: RPI | assumed | 5 cm, from the RPi owner's handover of 2026-09-25.
CENTRE_PATH_SPACING_CM = 5

# The straight-line move lengths, IN GRID CELLS, the search may take in one step. Each entry
# becomes one candidate neighbour, so more entries means a finer but slower search.
# SOURCE: ALGO | assumed | Reference offered exactly one chunk length, 5 cells.
STRAIGHT_CHUNK_CELLS = (5,)

# The longest single FORWARD/BACKWARD command, in centimetres, that may be put on the wire. The
# search merges consecutive same-direction chunks with no upper bound, so a clear run across the
# arena arrives as one large command: measured 2026-09-17, a lone obstacle at (100,80) facing
# NORTH gives a 140 cm FORWARD, and 300 random 4-8 obstacle arenas produced one of 160 cm against
# a hard ceiling of 170 (the robot centre is confined to a 171 cm band, driven in 5 cm chunks).
# Both 2026-09-17 figures predate the eight headings (on since 2026-09-18) and the 2026-09-25 turn
# fit, and long straights are still sent after both. Re-measured 2026-09-25 on the (100,80) arena,
# uncapped: as shipped (shortest-time, eight headings) the route opens with a 65 cm FORWARD, and
# shortest-time with four headings drives 115 cm. The 10 cm that tests/test_straight_cap.py pins
# is nearest-first under the test suite's four-heading pin, not what the service sends. On random
# 4-8 obstacle arenas with the shipped config, straights still reach 155 cm nearest-first (6 of
# 673 over 100 cm) and 120 cm shortest-time (3 of 168 over 100 cm), so this cap still binds.
#
# The 170 cm ceiling above is for a straight along an axis. With the eight headings a diagonal
# cell is sqrt(2) cm on the wire, so a diagonal straight could in principle reach 240 cm (170
# cells), and the cap matters there too: the longest diagonal observed, with eight headings on
# 2026-09-25, is 141 cm (a lone obstacle at (180,100) facing NORTH, nearest-first). Anything at
# or above 240 therefore disables the cap - 170 does only along an axis - and 0 disables it
# explicitly.
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
# SOURCE: STM | placeholder | NOT MEASURED. 3.0 is a guess: at the 2026-09-25 fit a FORWARD_RIGHT
#   rear arc is 59 cm, about 2.4 s at 25 cm/s, plus steering. Measure together with
#   TURN_DISPLACEMENT_CM and ROBOT_SPEED_CM_S.
TURN_TIME_S = 3.0

# Whether the search may drive and turn through the four diagonal headings, using the 45
# degree turns as well as the quarter turns. False is the four-heading planner exactly as it
# was. EXPERIMENTAL: the STM has to be able to execute and stop a 45 degree turn for any plan
# made with this on to survive contact with the robot.
# SOURCE: ALGO | assumed | Measured 2026-09-04 on branch kejun-experimental-algo: the
#   shortest-time planner saves 22% on testdata 02 and 34% on 04. Switched ON 2026-09-18 once the
#   STM owner had driven and measured 45 degree turns in all four directions; those are the
#   *_45 rows of TURN_DISPLACEMENT_CM, calibrated separately from the quarter turns. The RPi must
#   decode the four *_45 tokens.
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
# More strokes is not better. Measured 2026-09-25 at the fitted radii, one 45 degree pivot
# drifts 3.2 cm at 2 strokes, 5.3 cm at 4 and 6.1 cm at 6 turning right (5.5, 6.8 and 7.3 cm
# turning left), while the swept box it needs barely moves (50 x 57 cm at 2 strokes against
# 52 x 49 cm at 6 turning right, 50 x 59 against 49 x 54 turning left). The box is the centre
# path's extent plus the circumscribed disc of the rotating 31 cm square, the rule that
# reproduces the 2026-09-11 figures. Part of that drift is INHERENT: the two strokes of a pair
# turn about circles that are not concentric, so the pair does not close even when the radii
# match. At the fitted radii the forward/backward mismatch is a large share of it all the same:
# if both strokes ran at the pair's larger radius, that would remove about 48% of the right
# pivot's drift and 87% of the left's (measured 2026-09-25 at the fitted radii, where the right
# pair is 37.5 and 31.25 cm and the left 26.25 and 40). It is systematic rather than noise: it
# accumulates with every extra stroke instead of averaging out, which is also why the planner
# can model it.
# SOURCE: ALGO | assumed | 2 is the algo-side choice that minimises drift. Chosen 2026-09-11 at
#   the PLACEHOLDER radii and re-derived 2026-09-25 at the fitted ones, where 2 strokes still
#   drifts least for both pivots. Confirm the firmware drives the count the planner assumed.
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
