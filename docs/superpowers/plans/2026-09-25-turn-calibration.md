# Turn Calibration and Per-Move Poses Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every planned turn end where the tape-measured car ends, from a per-command two-parameter fit of the measured centre displacement, and report the robot centre after every instruction plus a fine-grained centre path in verbose responses.

**Architecture:** `config.TURN_DISPLACEMENT_CM` holds the raw measured `(across, along)` pair per turn command. `TurnInstruction.fit()` solves it for the rear-pivot model's `(radius, lead)` at call time; `turn.py` builds the rear-point arc from that fit and pins the end pose to the measurement; a new `turn.centre_arc()` gives the centre's path through a turn. `Segment.compress` assembles `centre_path`; the controller emits `poses` and `centre_path` only when verbose.

**Tech Stack:** Python 3.11, numpy, pydantic 2, flask-openapi3, pytest. Run everything from `algorithm/` with `./.venv/bin/python`.

**Spec:** `docs/superpowers/specs/2026-09-25-turn-calibration-design.md` (read it first; §2 holds the measurements, §3 the model, §5 the wire fields).

## Global Constraints

- Work in place on branch `kejun-experimental-algo`. **Never run `git commit`, `git push`, `git stash` or anything that GPG-signs.** Kejun commits by hand. `git add` is fine.
- Nothing outside `algorithm/` is touched by any task. `docs/protocols/openapi.json` is generated from the controller; leave it for Kejun.
- `config.py` imports nothing from the project, and consumers read `config.X` inside function bodies at call time, never `from config import X` at module level.
- Every new config constant carries `# SOURCE: <team> | measured|assumed|placeholder | <note>`.
- The collision check keeps its form: the rear-point arc's cells are checked, the end pose is appended unchecked. Do not add or remove checked cells beyond what re-parameterising the same arc produces.
- No response field is renamed or changes meaning. With `verbose: false` the response is what it is today except `poses` becomes `[]`.
- Match the surrounding style: long docstrings that say WHY. New code does the same.
- Tests use `pytest`, run as `cd algorithm && ./.venv/bin/python -m pytest tests -q`. The autouse fixture in `tests/conftest.py` pins `DIAGONAL_HEADINGS` and `PIVOT_TURNS` off unless a test is marked `diagonals` / `pivots`.
- Before this plan the suite stood at **31 failed, 204 passed, 1 skipped** (stale pins from the 09-18 numbers). The finish line is **0 failed**; every remaining failure is named in the report.

## Review Focus

1. A turn started on a **diagonal heading** (NORTHEAST etc.) must end where the rotated tape pair says, not where a cardinal-only formula would put it — pinned in Task 1 by parametrising the calibration test over all eight headings.
2. A **runtime change to `TURN_DISPLACEMENT_CM`** (the STM owner re-measures during a session) must move the arc, the end pose, the cost and the cache — pinned in Task 1 (`test_a_45_is_calibrated_on_its_own`, `test_cache_follows_a_runtime_table_change`).
3. **`verbose: false`** must return `poses: []` and `centre_path: []` and otherwise be identical to today — pinned in Task 4.
4. A **straight split by `MAX_STRAIGHT_CM`** must have every piece's pose literally present in `centre_path`, or the RPi's "pose lies on the path" check fails on long straights — pinned in Task 4 with the cap forced to 20 cm.
5. **A pivot** (flag on) must still trace, cost and animate with the new fit and the shared lead, or switching the flag on later raises deep in the search — pinned in Task 3 by keeping `test_pivot.py` green under `@pytest.mark.pivots`.

---

## Task map and parallelism

```
Wave 1:  Task 1 (geometry core)  ||  Task 1b (item-1 documentation)
         -> reviewer on Task 1
Wave 2:  Task 2 (re-pin planner tests, smoke)  ||  Task 3 (pivot tests)  ||  Task 4 (poses + centre_path)
Wave 3:  controller: full suite, before/after table, sample response, final review
```

File ownership (no two concurrent tasks touch the same file):

| Task | Owns |
|---|---|
| 1 | `config.py`, `pathfinding/search/instructions.py`, `pathfinding/search/turn.py`, `pathfinding/search/pivot.py`, `pathfinding/cost.py` (docstrings only), `simulator/playback.py`, `smoke.py` (one print), `tests/test_turn_calibration.py` (new), `tests/test_turn_cache.py`, `tests/test_turn_radius_45.py` (delete), `tests/test_diagonals.py` (one test removed) |
| 1b | `README.md`, `PROVENANCE.md`, `simulator/SPEC.md` |
| 2 | `tests/baselines/segment-baseline.json`, `tests/test_cost.py`, `tests/test_tour.py`, `tests/test_service.py`, `tests/test_straight_cap.py`, `tests/test_segment_order.py`, `tests/test_playback.py`, `smoke.py` (expectations) |
| 3 | `tests/test_pivot.py` |
| 4 | `pathfinding/search/search.py`, `pathfinding_controller.py`, `tests/test_poses.py`, plus one paragraph each appended to `README.md` ("Hit it with curl") and `PROVENANCE.md` ("Design decisions") |

---

### Task 1: Geometry core — fit per command, end pose from the tape

**Files:**
- Modify: `algorithm/config.py` (the "Motion primitives" block and four other constants)
- Modify: `algorithm/pathfinding/search/instructions.py` (`TurnInstruction`)
- Modify: `algorithm/pathfinding/search/turn.py` (whole geometry section)
- Modify: `algorithm/pathfinding/search/pivot.py` (`pivot()` and `__shuffle()`)
- Modify: `algorithm/pathfinding/cost.py` (docstring mentions of `TURN_RADIUS_CM` only)
- Modify: `algorithm/simulator/playback.py` (the `lead` read)
- Modify: `algorithm/smoke.py:181-184` (the config print)
- Create: `algorithm/tests/test_turn_calibration.py`
- Rewrite: `algorithm/tests/test_turn_cache.py`
- Delete: `algorithm/tests/test_turn_radius_45.py`
- Modify: `algorithm/tests/test_diagonals.py` (remove `test_two_45_degree_turns_land_where_one_90_does`)

**Interfaces:**
- Consumes: nothing new.
- Produces (later tasks rely on these exact names):
  - `config.TURN_DISPLACEMENT_CM: dict[str, tuple[float, float]]` keyed by `TurnInstruction.value`, values `(across_cm, along_cm)`.
  - `config.CENTRE_PATH_SPACING_CM: int = 5`.
  - `TurnInstruction.forward -> bool` (property).
  - `TurnInstruction.displacement(cell_size: int) -> tuple[float, float]` in cells.
  - `TurnInstruction.fit(cell_size: int) -> tuple[float, float]` = `(radius, lead)` in cells, floats.
  - `TurnInstruction.radius(cell_size: int) -> float` (was int), `TurnInstruction.lead(cell_size: int) -> float`.
  - `turn.turn(world, start, instruction) -> list[Vector] | None` — unchanged signature and contract (rear-point arc cells in driving order, end pose last).
  - `turn.centre_arc(start: Vector, instruction: TurnInstruction, cell_size: int) -> list[tuple[float, float]]` — the centre's path through the turn from `start` (start itself excluded), in cells, consecutive points at most `config.CENTRE_PATH_SPACING_CM / cell_size` apart, last element exactly the unrounded end offset added to `start`. No legality check.

- [ ] **Step 1: Write the failing calibration test**

Create `algorithm/tests/test_turn_calibration.py`:

```python
"""
Every turn command ends where the tape says it does.

`config.TURN_DISPLACEMENT_CM` holds, per command, how far the robot centre moved across and
along its starting heading in one command, measured on the car (spec §2). The planner's turn
model has two parameters per command - the radius its rear pivot rides and how far ahead of
that pivot the centre sits - and `TurnInstruction.fit` solves both from that pair, so the
planned end pose matches the measurement by construction. This file is what fails if either
the fit or the geometry that consumes it drifts: an end pose more than a cell from the tape,
from any of the eight headings.

Before this model the two tables held a centre-to-centre chord per command and read it as a
radius, which put every planned 90 about 20-27 cm past the real car. The first assertion below
is the one that failed then.
"""
import math

import pytest

import config
from pathfinding.search.instructions import TurnInstruction
from pathfinding.search.turn import centre_arc, turn
from pathfinding.world.primitives import Direction, Point, Vector
from pathfinding.world.world import Robot, World

_LEFT_LOCK = ("FORWARD_LEFT", "BACKWARD_LEFT")
_ANTICLOCKWISE = ("FORWARD_LEFT", "BACKWARD_RIGHT")


def empty_world() -> World:
    return World(config.GRID_SIZE, Robot.planned(Direction.NORTH, Point(0, 0), Point(30, 30)), [])


def expected_end(start: Vector, instruction: TurnInstruction) -> tuple[float, float]:
    """The tape's answer rotated into `start`'s heading: across toward the steering side, along the heading."""
    across, along = config.TURN_DISPLACEMENT_CM[instruction.value]
    ux, uy = start.direction.unit
    sx, sy = (-uy, ux) if instruction.lock in _LEFT_LOCK else (uy, -ux)
    return start.x + across * sx + along * ux, start.y + across * sy + along * uy


@pytest.mark.parametrize("direction", list(Direction), ids=lambda d: d.value)
@pytest.mark.parametrize("instruction", list(TurnInstruction), ids=lambda t: t.value)
def test_every_turn_ends_where_the_tape_says(direction, instruction):
    start = Vector(direction, 100, 100)
    path = turn(empty_world(), start, instruction)
    assert path is not None, "mid-arena, every turn must fit"
    end = path[-1]
    ex, ey = expected_end(start, instruction)
    assert abs(end.x - ex) <= 1.0 and abs(end.y - ey) <= 1.0, \
        f"{instruction.value} from {direction.value}: planned ({end.x - 100}, {end.y - 100}), tape ({ex - 100:.1f}, {ey - 100:.1f})"
    turned = -instruction.degrees if instruction.lock in _ANTICLOCKWISE else instruction.degrees
    assert end.direction == Direction.of_degrees(direction.degrees + turned)


def test_the_fit_is_the_hand_derivation_for_a_quarter_turn():
    """
    For a 90 the two equations collapse to sums and differences, which is how the numbers were
    checked by hand before any code existed: forward R = (across + along) / 2 and
    lead = (across - along) / 2; backward swaps the roles because the centre trails the pivot.
    """
    for t in TurnInstruction:
        if t.degrees != 90:
            continue
        across, along = config.TURN_DISPLACEMENT_CM[t.value]
        radius, lead = t.fit(1)
        if t.forward:
            assert radius == pytest.approx((across + along) / 2), t
            assert lead == pytest.approx((across - along) / 2), t
        else:
            assert radius == pytest.approx((across - along) / 2), t
            assert lead == pytest.approx((-along - across) / 2), t


def test_the_fit_reproduces_its_own_measurement():
    """Putting (R, L) back through the model must give the pair it was solved from - for the 45s too."""
    for t in TurnInstruction:
        across, along = t.displacement(1)
        radius, lead = t.fit(1)
        theta = math.radians(t.degrees)
        s, c = math.sin(theta), 1 - math.cos(theta)
        if t.forward:
            assert radius * c + lead * s == pytest.approx(across), t
            assert radius * s - lead * c == pytest.approx(along), t
        else:
            assert radius * c - lead * s == pytest.approx(across), t
            assert -(radius * s + lead * c) == pytest.approx(along), t


def test_a_45_is_calibrated_on_its_own(monkeypatch):
    """
    A 45 is not half a 90 and a 90 is not two 45s: each command has its own tape pair. Changing
    the 45's entry moves the 45 and leaves the 90 alone - which also proves the table is read at
    call time and that the arc cache keys on the pair.
    """
    world = empty_world()
    start = Vector(Direction.NORTH, 100, 100)
    before_45 = turn(world, start, TurnInstruction.FORWARD_LEFT_45)[-1]
    before_90 = turn(world, start, TurnInstruction.FORWARD_LEFT)[-1]

    table = dict(config.TURN_DISPLACEMENT_CM)
    table["FORWARD_LEFT_45"] = (30.0, 30.0)
    monkeypatch.setattr(config, "TURN_DISPLACEMENT_CM", table)

    assert turn(world, start, TurnInstruction.FORWARD_LEFT_45)[-1] != before_45
    assert turn(world, start, TurnInstruction.FORWARD_LEFT)[-1] == before_90


def test_the_shipped_table_covers_all_eight_commands():
    """Config is the STM owner's to edit; a missing or nonsensical entry must fail here, not on a live request."""
    assert set(config.TURN_DISPLACEMENT_CM) == {t.value for t in TurnInstruction}
    for t in TurnInstruction:
        across, along = config.TURN_DISPLACEMENT_CM[t.value]
        assert across > 0, f"{t.value}: every command moved toward its steering side"
        assert (along > 0) == t.forward, f"{t.value}: forward commands go forward, backward ones back"
        radius, lead = t.fit(1)
        assert radius > 0 and 0 < lead < 20, f"{t.value}: fit ({radius:.1f}, {lead:.1f}) is not a rear pivot behind the centre"


def test_the_arc_does_not_depend_on_the_planning_footprint():
    """The pivot point is measured, so a 21 cm and a 31 cm planning box trace the same arc."""
    start = Vector(Direction.EAST, 100, 100)
    big = World(config.GRID_SIZE, Robot.planned(Direction.NORTH, Point(0, 0), Point(30, 30)), [])
    small = World(config.GRID_SIZE, Robot.planned(Direction.NORTH, Point(0, 0), Point(20, 20)), [])
    assert turn(big, start, TurnInstruction.BACKWARD_RIGHT) == turn(small, start, TurnInstruction.BACKWARD_RIGHT)


@pytest.mark.parametrize("direction", list(Direction), ids=lambda d: d.value)
@pytest.mark.parametrize("instruction", list(TurnInstruction), ids=lambda t: t.value)
def test_the_centre_arc_is_finely_sampled_and_ends_on_the_end_pose(direction, instruction):
    start = Vector(direction, 100, 100)
    points = centre_arc(start, instruction, 1)
    spacing = config.CENTRE_PATH_SPACING_CM
    assert points, "a turn moves the centre, so there is always at least the end point"
    previous = (start.x, start.y)
    for point in points:
        assert math.dist(previous, point) <= spacing + 1e-9, (instruction, direction, previous, point)
        previous = point
    ex, ey = expected_end(start, instruction)
    assert points[-1] == pytest.approx((ex, ey), abs=1e-6)
    # And the planner's rounded end pose is that last point, rounded.
    end = turn(empty_world(), start, instruction)[-1]
    assert abs(end.x - points[-1][0]) <= 0.5 + 1e-9 and abs(end.y - points[-1][1]) <= 0.5 + 1e-9
```

- [ ] **Step 2: Add the config table so the test can fail on geometry, not on a missing name**

In `algorithm/config.py`, replace the block that begins with the comment `# Turning radius per turn instruction, in centimetres.` and ends with `TURN_PIVOT_OFFSET_CM = 3` (three constants: `TURN_RADIUS_CM`, `TURN_45_DISPLACEMENT_CM`, `TURN_PIVOT_OFFSET_CM`) with:

```python
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
# cannot pin both. The car pivots about a point on its rear axle: that point rides a circle of
# radius R while the centre sits L ahead of it, so after a 90 the centre has moved R + L across
# and R - L along (forward commands) or R - L across and R + L along (backward ones).
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
```

Also in `config.py`, without touching anything else:

- `ROBOT_SPEED_CM_S = 25`, and change its SOURCE line to `# SOURCE: STM | placeholder | NOT MEASURED. 25 is the working figure the algo owner set on 2026-09-25 (was 30). Update together with TURN_DISPLACEMENT_CM, which must be measured at the same speed.`
- `STANDOFF_MIN_CM = 12` and `STANDOFF_MAX_CM = 36`. Replace the two comment blocks above them with:

```python
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
```

- `LATERAL_TOLERANCE_CM = 5` with SOURCE `# SOURCE: ALGO | assumed | 5 cm, algo owner 2026-09-25 (was 10, the reference value). Should grow as the robot/obstacle size ratio grows.`
- In the `TURN_TIME_S` comment replace `Measure together with TURN_RADIUS_CM and ROBOT_SPEED_CM_S.` with `Measure together with TURN_DISPLACEMENT_CM and ROBOT_SPEED_CM_S.`
- In the `DIAGONAL_HEADINGS` comment replace `those are\n#   TURN_45_DISPLACEMENT_CM, separate from the quarter turns'.` with `those are the\n#   *_45 rows of TURN_DISPLACEMENT_CM, calibrated separately from the quarter turns.`
- In the `PIVOT_STROKES_PER_45` comment replace `Matching TURN_RADIUS_CM's 40 forward-right against its 37 backward-left` with `Matching the forward and backward radii (about 37 and 31 cm on the right, fitted)`.

Leave `SERVER_PORT = 5000` as it is.

- [ ] **Step 3: Run the new test and watch it fail on geometry**

Run: `cd algorithm && ./.venv/bin/python -m pytest tests/test_turn_calibration.py -q -x 2>&1 | tail -15`
Expected: an `AttributeError`/`ImportError` on `TurnInstruction.radius` reading the deleted `config.TURN_RADIUS_CM`, or on the missing `centre_arc`. That is the missing-feature failure; continue.

- [ ] **Step 4: Implement `TurnInstruction` in `instructions.py`**

Replace the `TurnInstruction` class body (keep the eight members) with:

```python
class TurnInstruction(str, Enum):
    """
    A turn. The bare names are the quarter turns; the ``_45`` variants are the same steering
    lock commanded for 45 degrees. Every one of the eight is calibrated on its own from
    ``config.TURN_DISPLACEMENT_CM``: a 45 is NOT half a 90, and neither is derived from the
    other in either direction, because the car was measured doing each one.
    """

    FORWARD_LEFT = 'FORWARD_LEFT'
    FORWARD_RIGHT = 'FORWARD_RIGHT'
    BACKWARD_LEFT = 'BACKWARD_LEFT'
    BACKWARD_RIGHT = 'BACKWARD_RIGHT'
    FORWARD_LEFT_45 = 'FORWARD_LEFT_45'
    FORWARD_RIGHT_45 = 'FORWARD_RIGHT_45'
    BACKWARD_LEFT_45 = 'BACKWARD_LEFT_45'
    BACKWARD_RIGHT_45 = 'BACKWARD_RIGHT_45'

    @property
    def degrees(self) -> int:
        """How far this turn swings the robot."""
        return 45 if self.value.endswith('_45') else 90

    @property
    def lock(self) -> str:
        """The steering lock, which decides which side the turning circle sits on."""
        return self.value.removesuffix('_45')

    @property
    def forward(self) -> bool:
        """Whether the wheels drive forward through this turn. Decides which way the centre trails the pivot."""
        return self.value.startswith('FORWARD')

    def displacement(self, cell_size: int) -> tuple[float, float]:
        """
        ``(across, along)``: how far the robot centre moves in one of these, in grid cells.

        Call-time config rule: read from ``config.TURN_DISPLACEMENT_CM`` on every call, so the
        STM owner can drop in a fresh tape measurement at runtime. Across is toward the steering
        side, along is along the starting heading and negative for a backward command - see the
        table's own comment for the convention.
        """
        across, along = config.TURN_DISPLACEMENT_CM[self.value]
        return across / cell_size, along / cell_size

    def fit(self, cell_size: int) -> tuple[float, float]:
        """
        The rear-pivot model's two parameters for this command, ``(radius, lead)`` in cells.

        The car rotates about a point on its rear axle. That point rides a circle of ``radius``
        while the centre sits ``lead`` ahead of it, so after a turn through ``theta`` the centre
        has moved, with ``s = sin(theta)`` and ``c = 1 - cos(theta)``::

            forward:   across = R*c + L*s      along  = R*s - L*c
            backward:  across = R*c - L*s      -along = R*s + L*c

        Two equations, two unknowns, solved here and nowhere else. The pair comes from the tape,
        so the end pose the geometry builds from this fit reproduces the measurement by
        construction; a chord alone could not have separated R from L, which is why the old
        one-number tables were wrong by the whole lead. Each command is fitted on its own - the
        eight leads come out 7-14 cm, one chassis property seen through tape noise and the
        steering transient - and keeping them separate is what makes every end pose exact.
        """
        across, along = self.displacement(cell_size)
        theta = radians(self.degrees)
        s, c = sin(theta), 1 - cos(theta)
        det = s * s + c * c
        if self.forward:
            radius = (across * c + along * s) / det
            lead = (across * s - along * c) / det
        else:
            back = -along
            radius = (across * c + back * s) / det
            lead = (back * c - across * s) / det
        return radius, lead

    def radius(self, cell_size: int) -> float:
        """The turning radius of the rear pivot, in grid cells, from :meth:`fit`. Every consumer of a
        turn's radius - the traced arc, ``arc_length``, both cost models, the pivot shuffle - reads this."""
        return self.fit(cell_size)[0]

    def lead(self, cell_size: int) -> float:
        """How far ahead of the rear pivot the robot centre sits, in grid cells, from :meth:`fit`."""
        return self.fit(cell_size)[1]

    def arc_length(self, cell_size: int) -> int:
        """The ground the rear pivot covers, in cells: what the distance model charges for a turn."""
        return round(self.radius(cell_size) * radians(self.degrees))
```

Keep the existing imports (`radians`, `sin` are already imported; add `cos`).

- [ ] **Step 5: Rewrite the geometry in `turn.py`**

Replace everything in `algorithm/pathfinding/search/turn.py` from the `_Arc` dataclass to the end of the file with the following. Keep the module header comment and the imports, adding `floor`, `hypot` to the `math` import and removing `ceil` only if unused (it is still used).

```python
@dataclass(frozen=True, eq=False)
class _Arc:
    """
    One turn's shape, as offsets from the starting cell.

    Every coordinate :func:`__frame` produces is the starting cell plus a constant, so a turn's
    arc is the same set of offsets wherever it starts: only ``(direction, instruction, the
    measured pair)`` change its shape. That is what makes the shape cacheable and the check a
    translation. The robot's planning footprint is NOT in the key any more: the pivot point is
    measured, not derived from the box, so a 21 cm and a 31 cm robot trace the same arc.

    :param direction: The post-turn facing, shared by every cell of the arc and the end pose.
    :param cells: The rear point's arc in driving order, consecutive duplicates dropped.
        Collision-checked.
    :param xs: ``cells``' x offsets, for the vectorised check.
    :param ys: ``cells``' y offsets.
    :param box: ``cells``' ``(min x, max x, min y, max y)``. Most turns the search tries are
        rejected, and this rejects the ones that leave the arena for four integer comparisons.
    :param end: The end pose's offset: the tape's displacement, rounded. Appended to the path
        but NOT collision-checked, as it never was.
    """

    # eq=False so this compares and hashes by identity: a generated __eq__ over the numpy
    # fields would raise "truth value of an array is ambiguous".
    direction: Direction
    cells: tuple[tuple[int, int], ...]
    xs: np.ndarray
    ys: np.ndarray
    box: tuple[int, int, int, int]
    end: tuple[int, int]


# Keyed by everything a turn's shape depends on, so a runtime change to the measured pair lands
# on a fresh key instead of reusing a stale arc. Bounded by 8 directions x 8 instructions x
# however many pairs one process plans with.
_ARCS: dict[tuple, _Arc] = {}

# Which side of the robot the turning circle sits on. The steering lock decides it, not the
# direction of travel, so forward-left and backward-left share a side.
_LEFT_LOCK = ('FORWARD_LEFT', 'BACKWARD_LEFT')

# The two locks that swing the nose anticlockwise. Reversing with the wheel held left swings
# the nose right, which is why the backward pair are mirrored.
_ANTICLOCKWISE = ('FORWARD_LEFT', 'BACKWARD_RIGHT')


def __turned(instruction: TurnInstruction) -> int:
    """How far this turn swings the compass heading, signed clockwise."""
    magnitude = instruction.degrees
    return -magnitude if instruction.lock in _ANTICLOCKWISE else magnitude


def __round(value: float) -> int:
    """Round half up. ``round()`` rounds half to even, which would put a 15.5 cm end at 16 and a
    4.5 at 4; the tape's halves deserve one rule."""
    return floor(value + 0.5)


def turn(world: World, start: Vector, instruction: TurnInstruction) -> list[Vector] | None:
    """
    Performs a turn.

    The arc's shape is computed once per ``(direction, instruction, measured pair)`` and cached
    as offsets; a call translates those offsets by ``start``, rejects the arc outright if its
    bounding box leaves the arena, and otherwise reads every cell of it in one numpy operation.

    The cells are the REAR PIVOT's path - what the planner has always collision-checked - and
    the last vector is the robot CENTRE's end pose, which comes from the tape measurement in
    ``config.TURN_DISPLACEMENT_CM`` and not from the circle (see :func:`__frame`).

    :param world: The world. Only ``cell_size`` and ``contains_all`` are read.
    :param start: The initial vector, the robot's centre.
    :param instruction: The turn instruction.
    :return: The path of the turn if it is legal, otherwise None.
    """
    cell_size = world.cell_size
    across, along = instruction.displacement(cell_size)
    key = (start.direction, instruction, across, along)

    try:
        arc = _ARCS[key]
    except KeyError:
        arc = _ARCS[key] = __arc(start.direction, instruction, cell_size)

    x, y = start.x, start.y

    # One check for the whole arc; nothing observes which cell failed.
    if not world.contains_all(arc.xs, arc.ys, arc.box, x, y):
        return None

    direction = arc.direction
    path = [Vector(direction, x + dx, y + dy) for dx, dy in arc.cells]
    end_x, end_y = x + arc.end[0], y + arc.end[1]
    # The end pose is dropped when the arc already finishes on that cell, as before.
    if not path or (path[-1].x, path[-1].y) != (end_x, end_y):
        path.append(Vector(direction, end_x, end_y))
    return path


def centre_arc(start: Vector, instruction: TurnInstruction, cell_size: int) -> list[tuple[float, float]]:
    """
    The robot CENTRE's path through this turn, in cells, in driving order.

    ``start`` itself is excluded; the last point is exactly the unrounded end offset added to
    ``start``, the same displacement :func:`turn` rounds into the end pose. The centre rides a
    circle of radius ``hypot(radius, lead)`` about the same instantaneous centre of rotation the
    rear pivot rides, and the points are spaced so that consecutive ones are at most
    ``config.CENTRE_PATH_SPACING_CM`` apart (read at call time). Geometry only: nothing here
    asks whether the turn is legal, so the caller checks that with :func:`turn` first.

    This is what the response's ``centre_path`` is built from. The rear-point ``path`` cells are
    the wrong thing to draw a route from: they sit ``lead`` behind the car.
    """
    frame = __frame(start.direction, instruction, cell_size)
    icr_x, icr_y, swept, end_x, end_y = frame.icr_x, frame.icr_y, frame.swept, frame.end_x, frame.end_y

    radius = hypot(icr_x, icr_y)
    starts = degrees(atan2(-icr_y, -icr_x))
    # Aim under the limit: the caller rounds both ends of every gap to whole cells, which can
    # stretch a gap by up to sqrt(2) cells, so 0.7 of the spacing keeps the ROUNDED points
    # inside it (3.5 + 1.41 < 5 at the default).
    spacing = 0.7 * config.CENTRE_PATH_SPACING_CM / cell_size
    steps = max(1, ceil(radius * abs(radians(swept)) / spacing))

    points = [
        (start.x + icr_x + radius * cos(radians(starts + swept * k / steps)),
         start.y + icr_y + radius * sin(radians(starts + swept * k / steps)))
        for k in range(1, steps)
    ]
    points.append((start.x + end_x, start.y + end_y))
    return points


@dataclass(frozen=True)
class _Frame:
    """The turn's geometry at the origin: where the rear pivot starts, where it circles, how far, and where the centre ends."""

    radius: float
    lead: float
    rear_x: float
    rear_y: float
    icr_x: float
    icr_y: float
    swept: float          # degrees, maths sense (anticlockwise positive)
    end_x: float          # the CENTRE's end offset, unrounded, straight from the tape
    end_y: float
    end_direction: Direction


def __frame(direction: Direction, instruction: TurnInstruction, cell_size: int) -> _Frame:
    """
    One statement of the manoeuvre, serving eight headings and eight commands.

    * the robot pivots about a point ``lead`` cells BEHIND its centre, on the rear axle;
    * the turning circle's centre - the instantaneous centre of rotation, ICR - sits ``radius``
      to the left or right of that point, chosen by the steering lock, which is why
      forward-left and backward-left share a side;
    * the rear point rides that circle through the angle the robot turns through;
    * the centre ENDS where the tape says it does: ``across`` toward the steering side and
      ``along`` along the start heading. :meth:`TurnInstruction.fit` chose ``radius`` and
      ``lead`` precisely so that the circle lands the centre there too, so the arc and the end
      pose agree analytically, and pinning the pose to the measurement rather than to the
      circle means no rounding inside the arc can move where the car is planned to stop.

    Angles are maths angles, anticlockwise from the x axis, which is why the compass delta is
    negated. Every coordinate is the start plus a constant, which is why :func:`__arc` can
    evaluate this at the origin once and translate the result.
    """
    radius, lead = instruction.fit(cell_size)
    across, along = instruction.displacement(cell_size)
    ux, uy = direction.unit

    # Left of the heading is (-uy, ux); right is its negation.
    side_x, side_y = (-uy, ux) if instruction.lock in _LEFT_LOCK else (uy, -ux)

    rear_x, rear_y = -lead * ux, -lead * uy
    icr_x, icr_y = rear_x + radius * side_x, rear_y + radius * side_y

    turned = __turned(instruction)
    return _Frame(
        radius, lead, rear_x, rear_y, icr_x, icr_y, -turned,
        across * side_x + along * ux, across * side_y + along * uy,
        Direction.of_degrees(direction.degrees + turned),
    )


def __arc(direction: Direction, instruction: TurnInstruction, cell_size: int) -> _Arc:
    """Builds one cache entry: the rear point's arc as offsets from the starting cell."""
    frame = __frame(direction, instruction, cell_size)

    starts = degrees(atan2(frame.rear_y - frame.icr_y, frame.rear_x - frame.icr_x))
    cells = __sampled(frame.icr_x, frame.icr_y, frame.radius, starts, frame.swept)

    xs = [cell[0] for cell in cells]
    ys = [cell[1] for cell in cells]

    return _Arc(
        frame.end_direction,
        cells,
        np.array(xs),
        np.array(ys),
        (min(xs), max(xs), min(ys), max(ys)),
        (__round(frame.end_x), __round(frame.end_y)),
    )


def __sampled(
    centre_x: float, centre_y: float, turning_radius: float, starts: float, swept: float
) -> tuple[tuple[int, int], ...]:
    """
    An arc walked in driving order at half-cell steps, rounded to cells, duplicates dropped.

    Half a cell rather than one: two points at most half a cell apart round to cells at most one
    apart on each axis, so the result is always 8-connected, which the per-cell grid read
    relies on to cover the circle without gaps. (Points a whole cell apart can round two cells
    apart when both sit on a half.) The midpoint-circle walk this replaces only knew
    axis-aligned quarter circles; this serves every heading and both turn sizes alike.
    """
    steps = max(1, ceil(2 * abs(radians(swept)) * turning_radius))
    cells: list[tuple[int, int]] = []
    for step in range(steps + 1):
        angle = radians(starts + swept * step / steps)
        cell = (__round(centre_x + turning_radius * cos(angle)),
                __round(centre_y + turning_radius * sin(angle)))
        if not cells or cell != cells[-1]:
            cells.append(cell)
    return tuple(cells)
```

Notes for the implementer: the old `__geometry`, `__quadrant`, `__offsets` and `__in_driving_order` are deleted entirely (the midpoint-circle raster is gone). Module-level `config` import stays: `centre_arc` reads `config.CENTRE_PATH_SPACING_CM` at call time. `world.robot` is no longer read; `segment._FreeWorld` may keep its `robot` attribute.

- [ ] **Step 6: Run the calibration test again**

Run: `cd algorithm && ./.venv/bin/python -m pytest tests/test_turn_calibration.py -q 2>&1 | tail -15`
Expected: PASS, all parametrisations. If `test_every_turn_ends_where_the_tape_says` fails for a backward command by a sign, the side vector or the `back = -along` branch is wrong; fix the code, not the tolerance.

- [ ] **Step 7: Update `pivot.py` to the fit**

In `pivot()` replace the block that reads the radii and offset:

```python
    # Call-time config rule: the fits and the stroke count are read from config on every call, so
    # freshly measured values can be dropped in at runtime. All are part of the cache key, so
    # doing so invalidates the cached shape by itself.
    cell_size = world.cell_size
    locks = _LOCKS[instruction.clockwise]
    radii = tuple(lock.radius(cell_size) for lock in locks)
    # One lead for the whole shuffle: the centre is one physical point on one axle, and the two
    # locks' fitted leads differ only by tape noise, so the mean is the honest single figure.
    lead = sum(lock.lead(cell_size) for lock in locks) / len(locks)
    strokes = instruction.strokes()

    key = (start.direction, instruction, radii, lead, strokes)
```

and call `__shuffle(start.direction, instruction, locks, radii, lead, strokes)`. Remove the `robot`/`offset` lines and the robot extents from the key. Change `__shuffle`'s signature to `(direction, instruction, locks, radii, lead, strokes)` and delete its first line `lead = robot.south_length - offset`; everything else in it stays. Update `_Shuffle`'s docstring ("both radii, offset, stroke count, robot extents" becomes "both radii, the lead, the stroke count") and the module docstring's "at the placeholder 40/37" sentence to "at the fitted radii" without inventing numbers. `_LOCKS` is unchanged.

- [ ] **Step 8: Update `cost.py` docstrings and `playback.py`'s lead**

`cost.py`: in `_Distance.pivot`'s docstring replace `reads ``config.TURN_RADIUS_CM`` at call time and\n        floors it into cells exactly as `pivot.py` floors it` with `fits ``config.TURN_DISPLACEMENT_CM`` at call time exactly as `pivot.py` reads it`. No code change.

`simulator/playback.py`: delete the two lines computing `lead` from `config.TURN_PIVOT_OFFSET_CM` in `Playback.__init__` (and the comment above them), and inside the `if isinstance(move, Turn):` branch, right after `*arc, end = move.vectors`, add:

```python
                    # The arc cells are the REAR PIVOT's path; the car's centre sits this far
                    # ahead of it, per command, from the same fit the planner drew the arc with.
                    lead = move.turn.lead(cell_size)
```

Update the module docstring's item 2 from "a point ``lead`` cm BEHIND the robot centre" to "a point ``lead`` cm BEHIND the robot centre (``TurnInstruction.lead``, fitted per command)". The `import config` stays if anything else in the file reads it; otherwise remove it.

`smoke.py:181-184`: replace `f"turn radii {config.TURN_RADIUS_CM}"` with `f"turn displacements {config.TURN_DISPLACEMENT_CM}"`.

- [ ] **Step 9: Rewrite `tests/test_turn_cache.py` against a per-cell oracle**

Replace the whole file with:

```python
"""
The cached, translated turn arcs must answer exactly what a per-cell check of the same cells would.

``slow_turn`` below is the oracle: it takes the arc's shape as ``turn()`` traces it on an
all-free arena, translates every cell to the start by hand, and asks ``World.contains`` about
each one - the way the pre-cache implementation did. Every test asserts that the fast path (one
bounding-box test, one vectorised grid read) agrees with it cell for cell and is None in exactly
the same cases. The SHAPE itself is pinned by ``tests/test_turn_calibration.py``; this file is
about the translation and the check.
"""
from __future__ import annotations

import numpy as np
import pytest

import config
from pathfinding.search.instructions import TurnInstruction
from pathfinding.search.turn import turn
from pathfinding.world.primitives import Direction, Point, Vector
from pathfinding.world.world import Obstacle, Robot, World

CASES = [(direction, instruction) for direction in Direction for instruction in TurnInstruction]


def arena(footprint_cm: int = 31, obstacles: tuple[Obstacle, ...] = ()) -> World:
    robot = Robot.planned(Direction.NORTH, Point(0, 0), Point(footprint_cm - 1, footprint_cm - 1))
    return World(config.GRID_SIZE, robot, list(obstacles))


def shape(direction: Direction, instruction: TurnInstruction):
    """The arc's cells and end pose as offsets from the start, traced where nothing can clip it."""
    world = arena()
    world.grid[:, :] = True
    *cells, end = turn(world, Vector(direction, 100, 100), instruction)
    return [(v.x - 100, v.y - 100) for v in cells], (end.x - 100, end.y - 100), end.direction


def slow_turn(world: World, start: Vector, instruction: TurnInstruction) -> list[Vector] | None:
    cells, (ex, ey), facing = shape(start.direction, instruction)
    if not all(world.contains(Point(start.x + dx, start.y + dy)) for dx, dy in cells):
        return None
    path = [Vector(facing, start.x + dx, start.y + dy) for dx, dy in cells]
    if not path or (path[-1].x, path[-1].y) != (start.x + ex, start.y + ey):
        path.append(Vector(facing, start.x + ex, start.y + ey))
    return path


@pytest.mark.parametrize("direction,instruction", CASES, ids=lambda v: v.value)
def test_every_case_matches_the_oracle_on_an_empty_arena(direction, instruction):
    world = arena()
    start = Vector(direction, 100, 100)
    expected = slow_turn(world, start, instruction)
    assert expected is not None, "the oracle itself must find this turn legal mid-arena"
    assert turn(world, start, instruction) == expected


def test_a_turn_that_clips_an_obstacle_is_none():
    world = arena(obstacles=(Obstacle(Direction.SOUTH, Point(90, 90), Point(99, 99), 11),))
    blocked = 0
    for direction, instruction in CASES:
        for x in range(60, 141, 10):
            for y in range(60, 141, 10):
                start = Vector(direction, x, y)
                expected = slow_turn(world, start, instruction)
                assert turn(world, start, instruction) == expected, (direction, instruction, x, y)
                blocked += expected is None
    assert blocked > 0, "this arena was supposed to block some turns"


def test_arcs_that_run_off_the_grid_are_none_not_wrapped():
    """
    A negative arc cell is out of bounds, not a wrap-around index into the far edge. Every cell
    of the grid is made free, so the ONLY thing that can reject a turn here is the bounds check.
    """
    world = arena()
    world.grid[:, :] = True
    off_grid = 0
    for direction, instruction in CASES:
        for x, y in ((0, 0), (5, 5), (14, 14), (14, 185), (185, 14), (185, 185), (199, 199)):
            start = Vector(direction, x, y)
            expected = slow_turn(world, start, instruction)
            assert turn(world, start, instruction) == expected, (direction, instruction, x, y)
            off_grid += expected is None
    assert off_grid > 0


def test_matches_the_oracle_across_a_populated_arena():
    world = arena(obstacles=(
        Obstacle(Direction.SOUTH, Point(50, 90), Point(59, 99), 11),
        Obstacle(Direction.WEST, Point(120, 60), Point(129, 69), 12),
        Obstacle(Direction.EAST, Point(60, 150), Point(69, 159), 14),
    ))
    legal = 0
    for direction, instruction in CASES:
        for x in range(0, 200, 13):
            for y in range(0, 200, 13):
                start = Vector(direction, x, y)
                expected = slow_turn(world, start, instruction)
                assert turn(world, start, instruction) == expected, (direction, instruction, x, y)
                legal += expected is not None
    assert legal > 0


def test_cache_follows_a_runtime_table_change(monkeypatch):
    """The key holds the measured pair read from config at call time, so a change invalidates it."""
    world = arena()
    start = Vector(Direction.NORTH, 100, 100)
    first = turn(world, start, TurnInstruction.FORWARD_LEFT)
    table = dict(config.TURN_DISPLACEMENT_CM)
    across, along = table["FORWARD_LEFT"]
    table["FORWARD_LEFT"] = (across - 10, along)
    monkeypatch.setattr(config, "TURN_DISPLACEMENT_CM", table)
    second = turn(world, start, TurnInstruction.FORWARD_LEFT)
    assert second == slow_turn(world, start, TurnInstruction.FORWARD_LEFT)
    assert second != first


def test_each_call_returns_its_own_vectors():
    """The cache holds offsets, not the returned objects: Vector is mutable and shared."""
    world = arena()
    start = Vector(Direction.NORTH, 100, 100)
    first = turn(world, start, TurnInstruction.FORWARD_LEFT)
    second = turn(world, start, TurnInstruction.FORWARD_LEFT)
    assert first == second
    assert first is not second
    assert all(a is not b for a, b in zip(first, second))


def test_contains_all_bounds_checks_before_indexing():
    world = arena()
    xs, ys = np.array([0, 1, 2]), np.array([0, 1, 2])
    box = (0, 2, 0, 2)
    assert world.contains_all(xs, ys, box, 100, 100) is True
    world.grid[world.size - 1, 100] = True
    world.grid[100, world.size - 1] = True
    assert world.contains_all(np.array([-1]), np.array([0]), (-1, -1, 0, 0), 0, 100) is False
    assert world.contains_all(np.array([0]), np.array([-1]), (0, 0, -1, -1), 100, 0) is False
    assert world.contains_all(np.array([0]), np.array([0]), (0, 0, 0, 0), world.size, 100) is False
    assert world.contains_all(np.array([0]), np.array([0]), (0, 0, 0, 0), 100, world.size) is False
    world.grid[101, 101] = False
    assert world.contains_all(xs, ys, box, 100, 100) is False
```

Delete `tests/test_turn_radius_45.py` (`git rm` is fine; it is a staged deletion, not a commit). In `tests/test_diagonals.py` delete `test_two_45_degree_turns_land_where_one_90_does` and add to the module docstring: `The 45s are calibrated on their own from the tape, so two of them do not land where one 90 does; their end poses are pinned in test_turn_calibration.py.`

- [ ] **Step 10: Run the geometry-facing tests**

Run: `cd algorithm && ./.venv/bin/python -m pytest tests/test_turn_calibration.py tests/test_turn_cache.py tests/test_diagonals.py -q 2>&1 | tail -20`
Expected: calibration and cache PASS. In `test_diagonals.py`, `test_every_heading_and_turn_size_produces_an_eight_connected_arc`, `test_a_turn_swings_the_heading_by_its_own_size`, `test_a_45_degree_turn_costs_half_a_90`, `test_a_diagonal_cell_costs_root_two` PASS. `test_the_diagonals_earn_their_keep` and `test_playback_rotates_through_a_45_degree_turn` may pass or fail depending on the arenas: **if one fails, do not edit it** - report the numbers and leave it to Task 2's owner, who re-pins the planner-level tests.

- [ ] **Step 11: Run the whole suite and record the failure list**

Run: `cd algorithm && ./.venv/bin/python -m pytest tests -q 2>&1 | grep -E 'FAILED|ERROR|passed|failed'`
Expected: nothing ERRORs (an ERROR means a name this task removed is still imported somewhere - fix it). Failures confined to these files are expected and are Tasks 2-4's: `test_segment_fast.py`, `test_cost.py`, `test_tour.py`, `test_service.py`, `test_straight_cap.py`, `test_segment_order.py`, `test_playback.py`, `test_pivot.py`, `test_poses.py`, `test_diagonals.py` (the two arena tests). Paste the list into your report. A failure anywhere else is yours.

- [ ] **Step 12: Stage**

```bash
cd algorithm && git add config.py pathfinding/search/instructions.py pathfinding/search/turn.py pathfinding/search/pivot.py pathfinding/cost.py simulator/playback.py smoke.py tests/test_turn_calibration.py tests/test_turn_cache.py tests/test_diagonals.py && git rm -q --cached tests/test_turn_radius_45.py 2>/dev/null; git rm -q tests/test_turn_radius_45.py 2>/dev/null; git status --short
```

No commit.

---

### Task 1b: Documentation of the turn model (runs in parallel with Task 1)

**Files:**
- Modify: `algorithm/README.md` ("Known limitations" items 2 and 3; the "Layout" tree is unchanged)
- Modify: `algorithm/PROVENANCE.md` ("Design decisions": one new entry; "Known gaps": items 2 and 3)
- Modify: `algorithm/simulator/SPEC.md:156-157` (the sentence naming `robot.south_length - TURN_PIVOT_OFFSET_CM`)

**Interfaces:**
- Consumes: the spec's §1-§4 (numbers and rationale). Do not read Task 1's code; it is being written concurrently. Refer to names exactly as Task 1's "Produces" block spells them.
- Produces: prose only.

- [ ] **Step 1: README limitation 2**

Replace the whole of item 2 ("**Turning radii are not ours.** ...") with:

```markdown
2. **The turn model is fitted to our car, one run per command.** `config.TURN_DISPLACEMENT_CM`
   holds, for each of the eight turn commands, how far the robot centre moved across and along
   its start heading in one command, tape-measured on 2026-09-25 at the competition speed
   setting. `TurnInstruction.fit` solves each pair for the rear-pivot model's radius and lead,
   so the planned end pose of every turn matches the tape to the centimetre
   (`tests/test_turn_calibration.py`). What the tape cannot give is repeatability: two 90s
   moved 5-7 cm between two sessions, so a plan is exact to the measurement and the car is
   exact to about a hand's width. Before this the tables held a centre-to-centre chord read as
   a radius, and every planned 90 ended 20-27 cm past the real car.
```

- [ ] **Step 2: README limitation 3**

Replace item 3 ("**Standoff is a placeholder.** ...") with:

```markdown
3. **Standoff is set for a camera 15-40 cm from the face.** `STANDOFF_MIN_CM`/`MAX_CM` are
   12..36 from the planning box's leading edge, which puts the lens 15.5-39.5 cm from the face
   if it sits 11.5 cm ahead of the centre mark (the plate's edge; not measured). One number to
   move if the lens is elsewhere. Lateral tolerance is +-5 cm.
```

- [ ] **Step 3: PROVENANCE design decision**

Append to the "Design decisions" section, before "## Known gaps":

```markdown
**The turn model is fitted per command from two-axis tape measurements.** A car at fixed
steering lock rotates about a point on its rear axle: that point rides a circle of radius R and
the centre sits L ahead of it. After a 90 the centre has moved `R + L` across and `R - L` along
(forward commands; backward ones swap the two). The reference's single lead of
`south_length - 3 = 12` cm and its one radius per lock were inherited unchanged, and on
2026-09-18 and 09-25 the four radii were "measured" as the straight-line distance between the
centre marks - a chord, `2 * sqrt(R^2 + L^2) * sin(theta/2)`, read as R. Every planned 90 then
ended 20-27 cm past the real car and every 45 about 4 cm past.

On 2026-09-25 each of the eight commands was measured as an (across, along) pair of the centre
(`config.TURN_DISPLACEMENT_CM`), and `TurnInstruction.fit` solves each pair for its own (R, L):

| command | R | L |
|---|---|---|
| FORWARD_LEFT | 26.3 | 10.8 |
| FORWARD_RIGHT | 37.5 | 9.5 |
| BACKWARD_LEFT | 31.3 | 9.8 |
| BACKWARD_RIGHT | 40.0 | 7.0 |
| FORWARD_LEFT_45 | 31.0 | 13.3 |
| FORWARD_RIGHT_45 | 37.1 | 14.3 |
| BACKWARD_LEFT_45 | 32.4 | 7.1 |
| BACKWARD_RIGHT_45 | 41.6 | 8.1 |

L is one chassis property and comes out 7-14 cm on all eight, which is the evidence the
rear-pivot circle is the right idealisation; the spread is tape noise, amplified on the 45s,
plus the steering transient at the start of each arc. Three choices follow. *Each command keeps
its own (R, L)* rather than sharing a mean L, because that is what makes every end pose exact
and it absorbs whatever the transient is; a 45 is not derived from a 90 or vice versa. *The end
pose comes from the tape, not the circle*: the fit makes the two agree analytically, and
pinning the pose to the measurement means no rounding inside the arc can move where the car is
planned to stop. *The collision check keeps its form* - the rear pivot's arc is checked and the
end pose appended unchecked - re-parameterised but not made stricter or looser, by the algo
owner's decision. `TURN_PIVOT_OFFSET_CM`, `TURN_RADIUS_CM` and `TURN_45_DISPLACEMENT_CM` are
gone; the arc no longer depends on the planning footprint, because the pivot point is measured.
What no fit removes is the car's own scatter: 5-7 cm between sessions on two of the 90s.
```

- [ ] **Step 4: PROVENANCE known gaps 2 and 3**

Replace gap 2 with:

```markdown
2. **The turn model is measured, one run per command, on 2026-09-25.** See the design decision
   above. Not yet measured: repeatability (two sessions differ by 5-7 cm on two 90s), the
   steering transient's length, and the straight speed and turn time the time model needs.
```

Replace gap 3 with:

```markdown
3. **Standoff is 12..36 cm from the planning box's leading edge**, chosen for a camera 15-40 cm
   from the face on the assumption that the lens sits 11.5 cm ahead of the centre mark. The
   lens offset has not been measured.
```

- [ ] **Step 5: simulator SPEC**

Replace `the arc is the path of a point \`lead\` cm behind the robot centre (\`robot.south_length -\nTURN_PIVOT_OFFSET_CM\`, 12 cm for the 31 cm robot)` with `the arc is the path of the rear pivot, \`TurnInstruction.lead\` cm behind the robot centre (7-14 cm, fitted per command from the tape)`.

- [ ] **Step 6: Stage**

```bash
cd algorithm && git add README.md PROVENANCE.md simulator/SPEC.md && git status --short
```

---

### Task 2: Re-pin the planner-level tests and smoke.py to the new geometry

**Files:**
- Regenerate: `algorithm/tests/baselines/segment-baseline.json`
- Modify: `algorithm/tests/test_cost.py:46`, `algorithm/tests/test_tour.py:209-241`, `algorithm/tests/test_service.py:38-46`, `algorithm/tests/test_straight_cap.py`, `algorithm/tests/test_segment_order.py`, `algorithm/tests/test_playback.py:147-190`, `algorithm/smoke.py` (the five arenas' expectations and comments)

**Interfaces:**
- Consumes: Task 1's geometry as landed (`TurnInstruction.lead(cell_size)`), and `config` as Task 1 left it.
- Produces: green tests. No production code changes; if a test can only pass by changing production code, stop and report.

Rules for this task: a pinned number is re-recorded only after you have looked at the new value and it is explicable by the new geometry (smaller turns, wider standoff band, narrower lateral tolerance). Each re-pinned value gets its capture date in the comment. An inequality that used to hold and no longer does (optimal strictly faster than greedy on `05`, eight headings beat four) is NOT forced: report it with both numbers, and weaken the assertion only to the property that is a code guarantee (optimal `<=` greedy at equal count).

- [ ] **Step 1: Regenerate the segment baseline**

Run: `cd algorithm && ./.venv/bin/python tests/test_segment_fast.py && git diff --stat tests/baselines/segment-baseline.json`
Then: `./.venv/bin/python -m pytest tests/test_segment_fast.py -q`
Expected: PASS. In your report, quote the new `unreachable` list per arena (from the JSON): `02` must plan all four obstacles with the diagonals off; if it does not, say so - it is a finding for Kejun, not something to hide by editing the arena.

- [ ] **Step 2: Re-pin `test_cost.py`**

Run `cd algorithm && ./.venv/bin/python -c "import os,sys; sys.path.insert(0,'.'); import config; config.DIAGONAL_HEADINGS=False; from simulator.arena import load; from pathfinding.search.search import search; from pathfinding.world.objective import generate_objectives; w=load('testdata/02-four-obstacles.json').world(); print([s.cost for s in search(w, generate_objectives(w)).segments])"` and put the printed list into line 46 with a comment `# re-recorded 2026-09-25 after the per-command turn fit`.

- [ ] **Step 3: Re-pin `test_tour.py`**

For `test_plan_optimal_on_testdata_02_costs_what_it_has_always_cost`: run the same arena through `plan_optimal` and `search` (diagonals off) and record the new order and totals in place of `[12, 11, 14, 13]` and `41.50`; rename nothing; update the comment's date. For `test_plan_optimal_is_not_slower_than_greedy_on_the_five_obstacle_arena`: delete the `< 66.83` line (the bound was a figure from the old geometry) and its comment sentence; the `assert_no_worse_than_greedy` line is the property. For `test_plan_optimal_warns_that_a_capped_search_is_not_a_proven_optimum`: keep as is; if it fails because the capped search now reports a proven optimum on `04`, lower `MAX_REPLANS` to 0 in the monkeypatch and say so in the comment.

- [ ] **Step 4: Re-pin `test_service.py`**

`test_default_strategy_is_optimal_and_greedy_is_selectable`: replace `[12, 11, 14, 13]` with the greedy order the service now returns for `02` (run the test, read the assertion diff). `test_optimal_is_strictly_faster_than_greedy_on_the_arena_built_for_it`: run it; if it passes, done; if optimal now equals greedy on `05`, change the last two assertions to `assert sum(optimal) <= sum(greedy) + 1e-9` and drop the `optimal_order != greedy_order` line, and rewrite the docstring's first line to say the arena no longer separates the strategies under the measured turns - and report that.

- [ ] **Step 5: Re-pin `test_straight_cap.py`**

Run the file. `long_straight_world` produces a different longest straight now. Print `straights(long_straight_world())` under `MAX_STRAIGHT_CM = 200`, and update: the `140` in `test_capping_splits_the_command_without_changing_the_distance` and the docstring of `long_straight_world`, the `[70, 70]` to `split_straight(<new longest>, 100)`'s value, and the `== 70` in `test_the_cap_is_read_at_call_time` to `max(split_straight(<new longest>, 100))`. If the new longest straight is at or below 100 cm the two tests can no longer exercise a split with this arena: lower the caps in those two tests to `MAX_STRAIGHT_CM = 50` and adjust the expected pieces, keeping the property (sum preserved, even split).

- [ ] **Step 6: `test_segment_order.py`**

In `test_arc_is_the_rear_point_path_and_end_is_the_centre` replace the `lead = ...config.TURN_PIVOT_OFFSET_CM...` line with, inside the turn branch, `lead = move.turn.lead(world.cell_size)`. In `test_moves_flatten_to_vectors_and_cover_all_four_turns`, keep the flatten assertion; change the last line to `assert seen and seen <= {t for t in TurnInstruction if t.degrees == 90}` and rename the test `test_moves_flatten_to_vectors_and_turns_are_quarter_turns` with a one-line comment that which of the four appear is a property of the arena, not a contract.

- [ ] **Step 7: `test_playback.py`**

Change `_turns` to yield `(move, frames)`:

```python
def _turns(playback):
    """(move, frames) for every turn in the route, in order."""
    from pathfinding.search.instructions import Turn
    out = []
    i = 0
    for segment in playback.route.segments:
        for move in segment.moves:
            n = len(move.vectors)
            if isinstance(move, Turn):
                out.append((move, playback.frames[i:i + n]))
            i += n
        i += CAPTURE_DWELL_FRAMES
    return out
```

Update both callers. In `test_arc_frames_lie_on_a_circle_of_the_turn_radius` delete the module-level `lead = ...` line, add `lead = move.turn.lead(p.route.cell_size)` at the top of the loop body, and change `assert 30 <= r <= 45` to `assert 20 <= r <= 45`, with the comment `# the fitted rear radii are 26-40 cm (spec §3)`. Keep the `abs_tol=0.6` circle check; if it fails by a small margin because the lifted circle now comes from a sampled arc, raise it to `1.0` and say why in a comment.

- [ ] **Step 8: `smoke.py`**

Run `cd algorithm && ./.venv/bin/python smoke.py`; for each arena whose stated expectation no longer holds, update the expectation AND the comment above it to explain the new outcome in terms of the new standoff band (12..36 from the leading edge) or the new turns. In particular the "pathological arena" comment derives obstacle 14's poses from the old band; recompute it. Then the run must exit 0.

- [ ] **Step 9: Run the files you own together, then stage**

Run: `cd algorithm && ./.venv/bin/python -m pytest tests/test_segment_fast.py tests/test_cost.py tests/test_tour.py tests/test_service.py tests/test_straight_cap.py tests/test_segment_order.py tests/test_playback.py tests/test_diagonals.py -q 2>&1 | tail -15 && ./.venv/bin/python smoke.py | tail -3`
Expected: all PASS, smoke `5/5`. Then `git add tests/baselines/segment-baseline.json tests/test_cost.py tests/test_tour.py tests/test_service.py tests/test_straight_cap.py tests/test_segment_order.py tests/test_playback.py smoke.py`. No commit.

---

### Task 3: `tests/test_pivot.py` under the new fit

**Files:**
- Modify: `algorithm/tests/test_pivot.py` only

**Interfaces:**
- Consumes: `config.TURN_DISPLACEMENT_CM`, `TurnInstruction.fit/radius/lead`, `pivot()` with the shared-mean lead (Task 1). Read `pathfinding/search/pivot.py` as landed before editing.
- Produces: the file green under `./.venv/bin/python -m pytest tests/test_pivot.py -q`. No production code changes; if a pivot test can only pass by changing `pivot.py` or `segment.py`, stop and report with the failing assertion and your diagnosis.

Facts to write tests against: a forward 90 with pair `(across, along)` has `R = (across + along) / 2`, `L = (across - along) / 2`; a backward 90 with `(across, along)` has `R = (across - along) / 2`, `L = (-along - across) / 2`. So a pair with `L = 0` is `(R, R)` forward and `(R, -R)` backward, and moving a forward pair from `(a, b)` to `(a + 2, b - 2)` keeps R and raises L by 2.

- [ ] **Step 1: Replace every read of the removed constants**

- `test_a_pivot_barely_moves_the_robot`: replace the `(52, 28)` pin with the new `FORWARD_RIGHT` end from north, `(47, 28)`, and the docstring's "(52, 28)" mentions with "(47, 28)". Keep `drift < 15`.
- `test_the_shape_follows_the_config_it_was_derived_from`: replace the `changed` dict with entries on `TURN_DISPLACEMENT_CM`: "the forward radii" -> `FORWARD_LEFT=(25.0, 25.0), FORWARD_RIGHT=(25.0, 25.0)`; "the backward radii" -> `BACKWARD_LEFT=(25.0, -25.0), BACKWARD_RIGHT=(25.0, -25.0)`; "the lead" -> every 90 entry moved to raise L by 2 with R fixed (forward `(a + 2, b - 2)`, backward `(a - 2, b - 2)`); "the stroke count" unchanged. Build each as `dict(config.TURN_DISPLACEMENT_CM, **{...})`.
- `test_a_pivot_is_charged_the_ground_its_wheels_cover`: `config.TURN_RADIUS_CM[forward]` becomes `TurnInstruction(forward).radius(1)` (import `TurnInstruction` if not already).
- `test_a_pivot_is_priced_against_the_two_locks_it_actually_alternates` (the test that holds the 40/40/30/10 monkeypatch; `test_a_90_degree_pivot_is_charged_twice_a_45` needs no change): monkeypatch `TURN_DISPLACEMENT_CM` to `dict(config.TURN_DISPLACEMENT_CM, FORWARD_RIGHT=(40.0, 40.0), BACKWARD_LEFT=(40.0, -40.0), FORWARD_LEFT=(30.0, 30.0), BACKWARD_RIGHT=(10.0, -10.0))` and update the comment to say these pairs are L = 0 with those radii.
- `test_a_pivots_distance_stays_in_cells_at_any_cell_size`: expected uses `TurnInstruction(forward).radius(5)`; the docstring paragraph about floor division is replaced by one sentence saying a radius in cells is the centimetre fit divided by the cell size.

- [ ] **Step 2: Run the file and triage what remains**

Run: `cd algorithm && ./.venv/bin/python -m pytest tests/test_pivot.py -q 2>&1 | grep -E 'FAILED|passed|failed'`
For each remaining failure, read the test's docstring and the assertion, decide whether the property it states still holds under the new fit, and either re-pin the arena/number (with a dated comment) or, if the property is a genuine contract that the new code breaks, stop and report. Known suspects from the pre-plan run: `test_a_pivot_that_does_not_fit_is_refused`, `test_the_rotation_clearance_is_a_disc_and_not_a_box`, `test_an_obstacle_out_of_reach_without_pivots_is_reachable_with_them`, `test_a_traced_pivot_comes_back_as_a_pivot_move`, `test_compress_carries_a_pivot_into_the_segment`, `test_both_ends_of_a_pivots_path_are_checked_for_rotation_clearance`, `test_the_virtual_boundary_is_not_eroded_but_is_still_a_wall`, `test_playback_rotates_through_a_pivot`. These place obstacles relative to the OLD shuffle shape; the shuffle now has different radii and a lead of about 10, so an obstacle one cell too far away no longer blocks, or a route no longer needs a pivot. Move the obstacle or pick a start cell so the docstring's scenario is true again, and say in the comment what you moved and why.

- [ ] **Step 3: Stage**

`cd algorithm && ./.venv/bin/python -m pytest tests/test_pivot.py -q | tail -3 && git add tests/test_pivot.py`. No commit.

---

### Task 4: `poses` gated to verbose, new `centre_path`

**Files:**
- Modify: `algorithm/pathfinding/search/search.py` (`Segment` and `Segment.compress`)
- Modify: `algorithm/pathfinding_controller.py` (module docstring items 8-9, `PathfindingResponseSegment`, `from_segment`, `stub` docstring)
- Modify: `algorithm/tests/test_poses.py`
- Modify: `algorithm/README.md` (one paragraph after "One segment per obstacle in visit order..." under "Hit it with curl") and `algorithm/PROVENANCE.md` (one design-decision entry, appended at the end of "Design decisions")

**Interfaces:**
- Consumes: `turn.centre_arc(start: Vector, instruction: TurnInstruction, cell_size: int) -> list[tuple[float, float]]` (Task 1), `config.CENTRE_PATH_SPACING_CM`.
- Produces: `Segment.centre_path: list[Point]`; response field `centre_path: list[PathfindingPoint]`; `poses` empty unless verbose.

- [ ] **Step 1: Write the failing tests**

Replace `algorithm/tests/test_poses.py` with:

```python
"""
`segments[].poses` and `segments[].centre_path`: the car's centre after EVERY instruction, and its
path through the whole segment, so the RPi never dead-reckons.

The tablet's ROBOT marker was drawn from the RPi's own motion model between captures - one that
carried last year's radii and a wrong 45 degree formula - and it drifted 15-38 cm from the
planner's car within a segment before snapping to `end`. With one pose per instruction the RPi
looks the position up instead, and its copy of the turning radii can go. `centre_path` is what
it draws the route from: the CENTRE through the turns too, where `path` is the rear pivot's
cells. Both are verbose-only (the RPi always asks verbose) and both are empty in stub mode.
"""
import json
import math
import os

import pytest

import config
from app import create_app

TESTDATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testdata")
CARDINAL = {"NORTH": (0, 1), "EAST": (1, 0), "SOUTH": (0, -1), "WEST": (-1, 0)}
FOUR = {"command": "imageRec", "algorithm": "optimal", "verbose": True, "obstacles": [
    {"id": 1, "x": 10, "y": 6, "face": "N"}, {"id": 2, "x": 4, "y": 12, "face": "S"},
    {"id": 3, "x": 12, "y": 3, "face": "W"}, {"id": 4, "x": 6, "y": 10, "face": "E"}]}
START = {"x": 15, "y": 15, "direction": "NORTH"}


@pytest.fixture(name="client")
def _client():
    return create_app().test_client()


def _walk(plan):
    """(previous pose, instruction, pose after) for every instruction, across the whole run."""
    prev = START
    for s in plan["segments"]:
        for instr, pose in zip(s["instructions"], s["poses"]):
            yield prev, instr, pose
            prev = pose


def test_one_pose_per_instruction_and_the_last_is_end(client):
    plan = client.post("/pathfinding/", json=FOUR).json
    assert plan["segments"]
    for s in plan["segments"]:
        assert len(s["poses"]) == len(s["instructions"])
        assert s["poses"][-1] == s["end"]
        assert all(set(p) == {"x", "y", "direction"} for p in s["poses"])


def test_a_cardinal_straight_moves_the_pose_by_exactly_its_amount(client, monkeypatch):
    monkeypatch.setattr(config, "MAX_STRAIGHT_CM", 20)
    checked = 0
    for prev, instr, pose in _walk(client.post("/pathfinding/", json=FOUR).json):
        if isinstance(instr, dict) and prev["direction"] in CARDINAL:
            dx, dy = CARDINAL[prev["direction"]]
            sign = 1 if instr["move"] == "FORWARD" else -1
            assert (pose["x"] - prev["x"], pose["y"] - prev["y"]) == (dx * instr["amount"] * sign, dy * instr["amount"] * sign), (prev, instr, pose)
            assert pose["direction"] == prev["direction"]
            checked += 1
    assert checked >= 6


def test_a_turn_changes_the_heading_and_capture_holds_still(client):
    turns = captures = 0
    for prev, instr, pose in _walk(client.post("/pathfinding/", json=FOUR).json):
        if instr == "CAPTURE_IMAGE":
            assert pose == prev
            captures += 1
        elif isinstance(instr, str):
            assert pose["direction"] != prev["direction"]
            turns += 1
    assert turns and captures == 4


def test_no_pose_puts_the_footprint_on_an_obstacle(client):
    half = config.ROBOT_FOOTPRINT_CM // 2
    boxes = [(o["x"] * 10, o["y"] * 10, o["x"] * 10 + 9, o["y"] * 10 + 9) for o in FOUR["obstacles"]]
    for _, _, p in _walk(client.post("/pathfinding/", json=FOUR).json):
        for x0, y0, x1, y1 in boxes:
            assert not (p["x"] - half <= x1 and p["x"] + half >= x0 and p["y"] - half <= y1 and p["y"] + half >= y0), (p, (x0, y0))


def test_centre_path_starts_at_the_start_pose_and_visits_every_pose(client, monkeypatch):
    """Every pose, split-straight pieces included, is literally a point of the path: the RPi's
    'pose lies on centre_path' check is a lookup, not a nearest-point search."""
    monkeypatch.setattr(config, "MAX_STRAIGHT_CM", 20)
    plan = client.post("/pathfinding/", json=FOUR).json
    prev = START
    for s in plan["segments"]:
        path = [(p["x"], p["y"]) for p in s["centre_path"]]
        assert path[0] == (prev["x"], prev["y"]), (s["obstacle_id"], path[0], prev)
        assert all(set(p) == {"x", "y"} for p in s["centre_path"])
        for pose in s["poses"]:
            assert (pose["x"], pose["y"]) in path, (s["obstacle_id"], pose)
        assert path[-1] == (s["end"]["x"], s["end"]["y"])
        prev = s["end"]


def test_centre_path_points_are_at_most_the_spacing_apart_through_turns(client):
    plan = client.post("/pathfinding/", json=FOUR).json
    limit = config.CENTRE_PATH_SPACING_CM                # on the INTEGER output, as the RPi sees it
    turned = 0
    for s in plan["segments"]:
        path = [(p["x"], p["y"]) for p in s["centre_path"]]
        straight_ends = {(p["x"], p["y"]) for p, i in zip(s["poses"], s["instructions"]) if isinstance(i, dict)}
        for a, b in zip(path, path[1:]):
            if b in straight_ends:
                continue                                  # a straight may be just its two ends
            assert math.dist(a, b) <= limit, (s["obstacle_id"], a, b)
            turned += 1
    assert turned > 0, "the arena must contain turns for this to test anything"


def test_centre_path_never_repeats_a_point(client):
    plan = client.post("/pathfinding/", json=FOUR).json
    for s in plan["segments"]:
        path = [(p["x"], p["y"]) for p in s["centre_path"]]
        assert all(a != b for a, b in zip(path, path[1:])), s["obstacle_id"]


def test_not_verbose_omits_both_and_changes_nothing_else(client):
    quiet = client.post("/pathfinding/", json=dict(FOUR, verbose=False)).json
    loud = client.post("/pathfinding/", json=FOUR).json
    for q, l in zip(quiet["segments"], loud["segments"]):
        assert q["poses"] == [] and q["centre_path"] == []
        assert q["obstacle_id"] == l["obstacle_id"]
        assert q["instructions"] == l["instructions"]
        assert q["end"] == l["end"]
        assert q["cost"] == 0 and q["seconds"] == 0.0 and q["path"] == []
    assert quiet["unreachable"] == loud["unreachable"]


@pytest.mark.parametrize("name", sorted(f for f in os.listdir(TESTDATA) if f.endswith(".json")))
def test_every_testdata_arena_still_plans_with_the_fields(client, name):
    with open(os.path.join(TESTDATA, name)) as f:
        body = json.load(f)
    body["verbose"] = True
    response = client.post("/pathfinding/", json=body)
    assert response.status_code == 200, response.data
    plan = response.json
    assert len(plan["segments"]) + len(plan["unreachable"]) == len(body["obstacles"])
    for s in plan["segments"]:
        assert len(s["poses"]) == len(s["instructions"]) and s["centre_path"]


def test_stub_mode_reports_neither():
    plan = create_app(stub=True).test_client().post("/pathfinding/", json=FOUR).json
    assert all(s["poses"] == [] and s["centre_path"] == [] for s in plan["segments"])
```

- [ ] **Step 2: Run and watch them fail**

Run: `cd algorithm && ./.venv/bin/python -m pytest tests/test_poses.py -q 2>&1 | tail -15`
Expected: `KeyError: 'centre_path'` on the new tests and `assert [] == ...` on the not-verbose test (`poses` is still always sent). Existing tests pass.

- [ ] **Step 3: Build `centre_path` in `Segment.compress`**

In `search.py` add `from pathfinding.search.turn import centre_arc` and `from pathfinding.world.primitives import Point, Vector`. Add to `Segment`, after `poses`:

```python
    # The robot's centre through the whole segment in driving order: the start pose, then every
    # entry of `poses` with the centre's arc through each turn (at most
    # config.CENTRE_PATH_SPACING_CM between points) and the centre cells of each pivot in
    # between. This is the line the tablet draws the route from; `vectors` is the collision
    # check's rear-pivot cells and sits `lead` behind the car inside every turn.
    centre_path: list[Point] = field(default_factory=list)
```

In `compress`, record the move behind each instruction: in the first loop, next to every `instructions.append(...)`, also `sources.append(move)` (declare `sources: list[Turn | Pivot | Move] = []` beside `after`), and in the merged-straight case leave `sources` alone (the merged command keeps its first move as its source; it is only read for pivots). Then in the second loop build the path alongside `poses`:

```python
        limit = config.MAX_STRAIGHT_CM
        cell_size = world.cell_size
        split: list[TurnInstruction | PivotInstruction | MoveInstruction | MiscInstruction] = []
        poses: list[Vector] = []
        centre_path: list[Point] = [Point(start.x, start.y)]

        def visit(point: Point) -> None:
            """Append a centre point, dropping an exact repeat of the last one."""
            if centre_path[-1] != point:
                centre_path.append(point)

        previous = start
        for instruction, reached, source in zip(instructions, after, sources):
            if isinstance(instruction, MoveInstruction):
                pieces = split_straight(instruction.amount, limit)
                covered = 0
                for index, amount in enumerate(pieces):
                    covered += amount
                    if index == len(pieces) - 1:
                        pose = reached
                    else:
                        share = covered / instruction.amount
                        pose = Vector(reached.direction,
                                      round(previous.x + (reached.x - previous.x) * share),
                                      round(previous.y + (reached.y - previous.y) * share))
                    split.append(MoveInstruction(move=instruction.move, amount=amount))
                    poses.append(pose)
                    visit(Point(pose.x, pose.y))
            else:
                if isinstance(instruction, TurnInstruction):
                    # The centre's own arc, sampled finely; its last point IS the end pose the
                    # search recorded, up to the rounding both sides apply, so the exact
                    # `reached` is appended after it and the rounded duplicate dropped.
                    for x, y in centre_arc(previous, instruction, cell_size)[:-1]:
                        visit(Point(round(x), round(y)))
                elif isinstance(instruction, PivotInstruction):
                    for vector in source.vectors[:-1]:
                        visit(Point(vector.x, vector.y))
                split.append(instruction)
                poses.append(reached)
                visit(Point(reached.x, reached.y))
            previous = reached
        instructions = split

        instructions.append(MiscInstruction.CAPTURE_IMAGE)
        poses.append(previous)
```

and pass `centre_path` as the last argument of `cls(...)`. Note the `sources` list must be kept in step with `instructions` through the first loop's merge (append only when an instruction is appended).

- [ ] **Step 4: Emit the fields from the controller, verbose only**

In `pathfinding_controller.py`:

- Module docstring: item 8 becomes `8. ``PathfindingResponseSegment.poses`` - new field, the pose after every instruction, aligned with ``instructions``. Verbose only. Replaces the RPi's own dead reckoning for the tablet's ROBOT marker.` and add `9. ``PathfindingResponseSegment.centre_path`` - new field, the robot centre through the whole segment including inside turns, at most ``config.CENTRE_PATH_SPACING_CM`` apart along an arc. Verbose only. What the tablet draws the route from; ``path`` stays the rear-pivot cells it always was.` Change "exactly eight" to "exactly nine" and "all eight" to "all nine".
- `PathfindingResponseSegment.poses`: description becomes `"The car's centre pose after each instruction, aligned one-to-one with `instructions`; the last equals `end`. Only when verbose. Report these to the tablet instead of dead-reckoning."` and the comment above it says verbose-only.
- Add after `poses`:

```python
    # Additive. The robot centre through the whole segment, in driving order, INCLUDING inside
    # turns, where `path` holds the rear pivot's cells instead. Starts at the segment's start
    # pose, contains every entry of `poses`, and along an arc consecutive points are at most
    # config.CENTRE_PATH_SPACING_CM apart; a straight may be just its two ends. Verbose only,
    # like `path`; empty in stub mode for the same reason `end` is None there.
    centre_path: list[PathfindingPoint] = Field(
        default_factory=list,
        description="The robot centre through the segment in driving order, turns included, "
        "at most CENTRE_PATH_SPACING_CM (5 cm) between points along an arc. Only when verbose. "
        "Draw the route from this, not from `path`.",
    )
```

- `from_segment`: `poses=[PathfindingVector.from_vector(pose) for pose in segment.poses] if verbose else [],` and `centre_path=[PathfindingPoint.from_point(point) for point in segment.centre_path] if verbose else [],`.
- `stub` docstring: `- ``end`` is always ``None`` and ``poses`` and ``centre_path`` always empty, ...`.

- [ ] **Step 5: Run the tests**

Run: `cd algorithm && ./.venv/bin/python -m pytest tests/test_poses.py tests/test_android_request.py tests/test_service.py -q 2>&1 | tail -15`
Expected: `test_poses.py` all PASS. `test_android_request.py` PASS. In `test_service.py` only the two order/time pins Task 2 owns may fail; anything else there is yours.

- [ ] **Step 6: Documentation**

README, under "Hit it with curl", after the paragraph ending "Full field-by-field description is in the protocol doc.", add:

```markdown
With `verbose: true` each segment also carries `poses`, the robot centre after every instruction
(one entry per instruction, the last equal to `end`), and `centre_path`, the centre's line
through the whole segment with points at most 5 cm apart along the turns. The RPi reports
`poses` to the tablet as the robot marker and draws the route from `centre_path`; the older
`path` is the collision check's rear-pivot cells and sits behind the car inside every turn.
Both are empty when `verbose` is false and in stub mode.
```

PROVENANCE, appended at the end of "Design decisions":

```markdown
**The response carries the centre after every instruction and through every turn.** The RPi
drew the tablet's robot marker from its own dead reckoning between captures, with its own copy
of the turn radii and its own 45 degree formula, and it drifted 15-38 cm inside a segment. The
team's rule is that all motion calibration lives in the planner, so on 2026-09-25 (the RPi
owner's handover) two additive, verbose-only fields were added: `poses`, one centre pose per
instruction, and `centre_path`, the centre's line through the segment including the arcs, from
`turn.centre_arc` at no more than `CENTRE_PATH_SPACING_CM` between points. `path` was left
exactly as it was - it is the rear pivot's cells, useful for the collision check and the
simulator, wrong to draw a car from - and `verbose: false` responses are unchanged. With these
the RPi deletes its radii and its dead reckoning.
```

- [ ] **Step 7: Stage**

```bash
cd algorithm && git add pathfinding/search/search.py pathfinding_controller.py tests/test_poses.py README.md PROVENANCE.md && git status --short
```

No commit.

---

### Wave 3 (controller, not delegated)

1. `cd algorithm && ./.venv/bin/python -m pytest tests -q` — must be 0 failed; `./.venv/bin/python smoke.py` exit 0; `./.venv/bin/python -m simulator --selftest` if tkinter is available.
2. Before/after table for the 8 commands (the "before" is spec §1; the "after" is the planned end from `turn()` against the tape).
3. Sample: start `app.py` is not needed; use the Flask test client to POST `testdata/02-four-obstacles.json` with `verbose: true` and write the response to `algorithm/testdata/responses/02-four-obstacles.verbose.json`.
4. Final whole-branch review by a fresh reviewer against the spec.
5. Hand Kejun the staged tree and the commit command. Report to Shuen Wei per spec §7, noting that `docs/protocols/openapi.json` and `algorithm-service.md` are his to regenerate/update.
