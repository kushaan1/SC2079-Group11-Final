# Simulator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A tkinter simulator that demonstrates checklist items B.1 and B.2 (grid map, obstacles with image faces, animated time-stepped robot, captured list, clock) and is ready to plug a shortest-time route source in for B.3.

**Architecture:** Pure modules (`geometry`, `arena`, `routes`, `playback`, `arena_view`, `snapshot`) that never import tkinter and are unit-tested, plus a thin tk layer (`fonts`, `painters.TkPainter`, `app`). Drawing goes through a `Painter` protocol so the same code paints the window and a PNG (`--snapshot`), which is how an agent without a display checks its rendering. The planner is called in-process.

**Tech Stack:** Python 3.11+, tkinter, numpy/pydantic (already there), pytest, Pillow (dev only, for snapshots).

**Spec:** `algorithm/simulator/SPEC.md`

## Global Constraints

- Work from `algorithm/`; every command below runs there with `./.venv/bin/python`. Tests: `./.venv/bin/python -m pytest tests -q`. Smoke: `./.venv/bin/python smoke.py` must keep passing 4/4.
- **Do not run `git add` or `git commit`.** The repo owner commits. Leave changes in the working tree. "Commit" steps in the task template are omitted on purpose.
- Every tuneable number lives in `config.py` with a `# SOURCE: <team> | measured|assumed|placeholder | <note>` comment, and is read at **call time** (`import config`, then `config.X` inside functions). Never `from config import X`.
- Only `simulator/app.py`, `simulator/fonts.py` and `TkPainter` in `simulator/painters.py` may import tkinter.
- Every cm-to-pixel conversion lives in `simulator/geometry.py`. No other file computes a pixel from a centimetre.
- Palette, exactly: paper `#FDFDFA`, grid minor `#D5E8DC`, grid major `#A8CDB6`, ink `#1B2A2F`, muted `#6A7A7E`, window `#F7F7F2`, panel `#FFFFFF`, rule `#E3E7E1`, start fill `#E8F1EA`, start edge `#2A9D6B`, image face `#E4572E`, camera dot `#2457A8`, planned-not-driven `#9AA5A8`, segment colours in order `#2457A8 #E4572E #2A9D6B #8E5AC8 #D99A00 #0E9AA7 #C2185B #7A5230`.
- Copy is sentence case, buttons say what they do: "Plan route", "Open arena", "Save arena", "Play", "Pause", "Step", "Reset". The clock reads `m:ss` then "est. of 6:00".
- Obstacles are labelled with their `image_id`; new ones take the lowest unused id from `config.IMAGE_ID_MIN` (which becomes 1). Positions in the panel are shown in tablet cells `(cx, cy)`, 0..19.
- Tk cannot open a window inside the agent sandbox (XPC "Connection invalid"). If a `--selftest` run fails that way, rerun that one command with the sandbox disabled. Never ask for screen-capture permission; use `--snapshot` for pictures.
- Keep files small and single-purpose. Docstrings say what and why, not how. No emoji anywhere in code or UI.

---

### Task 1: Config additions, obstacle-id widening, one parity rule

**Files:**
- Modify: `algorithm/config.py`
- Modify: `algorithm/pathfinding/world/world.py` (Robot)
- Modify: `algorithm/pathfinding_controller.py:106-133` (`to_robot`)
- Modify: `algorithm/smoke.py:34-50` (`make_robot`)
- Modify: `algorithm/README.md`, `algorithm/PROVENANCE.md`, `docs/protocols/algorithm-service.md`, `docs/rpi-test-algo-server.md`, `algorithm/testdata/README.md` (the "11-40" statements)
- Create: `algorithm/tests/conftest.py`, `algorithm/tests/test_robot_parity.py`

**Interfaces:**
- Produces: `config.START_ZONE_CM`, `config.OBSTACLE_SIZE_CM`, `config.ROBOT_BODY_CM`, `config.ROBOT_SPEED_CM_S`, `config.CAPTURE_DWELL_S`, `config.TASK_1_TIME_LIMIT_S`, `config.IMAGE_ID_MIN == 1`; `Robot.planned(direction, south_west, north_east) -> Robot`.

- [ ] **Step 1: conftest and the failing parity test**

`algorithm/tests/conftest.py`:
```python
"""Puts algorithm/ on sys.path so `import config` and `from pathfinding...` resolve under pytest."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

`algorithm/tests/test_robot_parity.py`:
```python
from pathfinding.world.primitives import Direction, Point
from pathfinding.world.world import Robot


def test_even_extent_is_kept():
    robot = Robot.planned(Direction.NORTH, Point(0, 0), Point(30, 30))
    assert robot.north_east == Point(30, 30)
    assert robot.centre == Point(15, 15)


def test_odd_extent_is_bumped_by_one():
    robot = Robot.planned(Direction.NORTH, Point(0, 0), Point(29, 29))
    assert robot.north_east == Point(30, 30)


def test_bump_applies_off_origin():
    robot = Robot.planned(Direction.EAST, Point(10, 20), Point(39, 49))
    assert robot.north_east == Point(40, 50)
    assert robot.centre == Point(25, 35)
```

- [ ] **Step 2: run it, expect `AttributeError: type object 'Robot' has no attribute 'planned'`**

Run: `./.venv/bin/python -m pytest tests/test_robot_parity.py -q`

- [ ] **Step 3: add `Robot.planned` and route the two existing copies through it**

In `pathfinding/world/world.py`, on `Robot`:
```python
@dataclass
class Robot(Entity):
    def __post_init__(self):
        super().__post_init__()

    @classmethod
    def planned(cls, direction: Direction, south_west: Point, north_east: Point) -> Robot:
        """
        Build a Robot the planner can actually turn.

        The turning geometry needs the centre cell to be genuinely central, which holds only
        when both corner extents are even (footprint in cells is odd). An odd extent is bumped
        by one, so a robot declared 0..29 (30 cm) is planned as 0..30 (31 cm). This is the one
        home of that rule; the controller, smoke test and simulator all call it.
        """
        if (north_east.x - south_west.x) % 2 != 0 and (north_east.y - south_west.y) % 2 != 0:
            north_east = Point(north_east.x + 1, north_east.y + 1)
        return cls(direction, south_west, north_east)
```
In `pathfinding_controller.py`, `PathfindingRequestRobot.to_robot` becomes:
```python
    def to_robot(self) -> Robot:
        """Build the domain Robot. The parity bump lives in Robot.planned; see it for why."""
        return Robot.planned(self.direction, self.south_west.to_point(), self.north_east.to_point())
```
(Delete the old docstring paragraphs about "three copies".) In `smoke.py`, `make_robot` becomes:
```python
def make_robot(direction: Direction, south_west: tuple[int, int], north_east: tuple[int, int]) -> Robot:
    """Build a Robot the way the service does, parity bump included (Robot.planned)."""
    return Robot.planned(direction, Point(*south_west), Point(*north_east))
```
In `config.py`, shorten the comment on `planned_footprint_cm` to point at `Robot.planned` as the corner-wise form.

- [ ] **Step 4: config additions**

Append to the **Arena** section of `config.py`:
```python
# Edge length of the square start zone at the arena's origin, in centimetres. Display only:
# the planner does not keep the robot out of it.
# SOURCE: RULES | measured | 40 x 40 cm bottom-left. MDP briefing p.16, algo deck p.3.
START_ZONE_CM = 40

# Edge length of one obstacle, in centimetres. Also the tablet's grid cell: the Android app
# sends an obstacle as one cell (cx, cy) in 0..19, which the simulator converts to corners.
# SOURCE: RULES | measured | 10 x 10 cm blocks. MDP briefing p.15.
OBSTACLE_SIZE_CM = 10
```
Append to the **Robot** section:
```python
# The physical chassis, (width across, length along heading) in centimetres. Drawn by the
# simulator inside the planning footprint; the planner never uses it.
# SOURCE: STM | measured | 18.6-18.8 cm wide, 23 cm plate, from the briefing photo (p.9).
#   Re-measure with the camera mount fitted.
ROBOT_BODY_CM = (19, 23)

# Straight-line speed at competition speed, in centimetres per second. Used ONLY by the
# simulator to turn a path length into an estimated duration; the planner costs in cm.
# SOURCE: STM | placeholder | NOT MEASURED. 30 is a guess. Update together with
#   TURN_RADIUS_CM, which must be measured at the same speed.
ROBOT_SPEED_CM_S = 30
```
Append to the **Image recognition** section:
```python
# Seconds the robot stands still at each obstacle for capture and inference. Simulator clock only.
# SOURCE: CV | placeholder | NOT MEASURED. 2 s is a guess.
CAPTURE_DWELL_S = 2.0
```
Add a new section **Rules**:
```python
# ---------------------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------------------

# Task 1 time limit, in seconds. The simulator shows its estimate against this.
# SOURCE: RULES | measured | 6 minutes for Task 1 (3 for Task 2). MDP briefing p.17.
TASK_1_TIME_LIMIT_S = 360
```
Change `IMAGE_ID_MIN` to `1` and rewrite its comment:
```python
# Lowest accepted obstacle identifier. Inclusive.
# SOURCE: RULES | measured | In Task 1 the image on an obstacle is unknown until CV reads it, so
#   this field identifies the OBSTACLE, not the image. The tablet numbers obstacles 1-8
#   (checklist C.6, C.9 "TARGET, <Obstacle Number>, <Target ID>"; android branch Encoder.kt
#   sends "ADD,B<id>,..."). The planner never uses the value beyond echoing it. 1-40 accepts
#   both obstacle numbers and, for hand-written arenas, real image ids 11-40.
IMAGE_ID_MIN = 1
```
Keep `IMAGE_ID_MAX = 40`; adjust its comment to "See IMAGE_ID_MIN. 36-40 are the arrows and stop marker."

- [ ] **Step 5: docs**

Grep `11-40`, `11–40`, `IDs 11` across `algorithm/README.md`, `algorithm/PROVENANCE.md`, `docs/protocols/algorithm-service.md`, `docs/rpi-test-algo-server.md`, `algorithm/testdata/README.md`, `pathfinding_controller.py` docstrings. Rewrite each statement to: `image_id` must be **1-40** and is the obstacle's identifier as assigned by the tablet (1-8 on a real run); the 422 message and troubleshooting rows say "outside 1-40". In `docs/protocols/algorithm-service.md` add one line under Request: "`image_id` identifies the obstacle, not the image. On a real run it is the tablet's obstacle number (1-8). It is echoed back unchanged in `segments[].image_id` and `unreachable[].image_id`." Add the change to the "Deviations from the prior-year contract" table as row 5: "image_id 1-10 accepted (was 422)". Add a matching bullet under "Design decisions" in `PROVENANCE.md` (three sentences, why the field is an obstacle id). Also record in `PROVENANCE.md` "Fix 4" that the range is now 1-40.

- [ ] **Step 6: verify**

Run: `./.venv/bin/python -m pytest tests -q` → 3 passed.
Run: `./.venv/bin/python smoke.py | tail -1` → `4/4 arenas met their stated baseline`.
Run: `./.venv/bin/python -c "import config; assert config.IMAGE_ID_MIN == 1 and config.START_ZONE_CM == 40 and config.ROBOT_BODY_CM == (19, 23)"`.
Run: `./.venv/bin/python -c "from app import create_app; c = create_app().test_client(); r = c.post('/pathfinding/', json={'robot': {'direction': 'NORTH', 'south_west': {'x': 0, 'y': 0}, 'north_east': {'x': 30, 'y': 30}}, 'obstacles': [{'image_id': 1, 'direction': 'SOUTH', 'south_west': {'x': 50, 'y': 90}, 'north_east': {'x': 59, 'y': 99}}]}); print(r.status_code, r.json['segments'][0]['image_id'])"` → `200 1`.

---

### Task 2: geometry

**Files:**
- Create: `algorithm/simulator/__init__.py` (empty), `algorithm/simulator/geometry.py`
- Test: `algorithm/tests/test_geometry.py`

**Interfaces:**
- Produces:
  - `Geometry(scale: float, arena_cm: int)` frozen dataclass with `arena_px`, `to_canvas(x_cm, y_cm) -> (px, py)`, `to_arena(px, py) -> (x_cm, y_cm)` (floats), `rect(x_cm, y_cm, w_cm, h_cm) -> (x0, y0, x1, y1)` with `y0 < y1`.
  - `fit_scale(screen_height_px: int, arena_cm: int) -> float`
  - `snap(value_cm: float, step_cm: int) -> int`
  - `cell_to_corners(cx: int, cy: int) -> tuple[Point, Point]`, `corners_to_cell(south_west: Point) -> tuple[int, int]`, `centre_to_tablet(x_cm, y_cm) -> tuple[float, float]`
  - `HEADING_DEG: dict[Direction, int]` (N 0, E 90, S 180, W 270)
  - `rotate(points, cx, cy, heading_deg) -> list[tuple[float, float]]`
  - `car_shapes(cx_cm, cy_cm, direction) -> CarShapes` with `body: list[(x,y)]` (8 points, chamfered), `wheels: list[list[(x,y)]]` (4 quads), `camera: (x, y, r)`; all in arena cm, already rotated.

- [ ] **Step 1: failing tests**

`algorithm/tests/test_geometry.py`:
```python
import math

import config
from pathfinding.world.primitives import Direction, Point
from simulator.geometry import (Geometry, car_shapes, cell_to_corners, centre_to_tablet,
                                corners_to_cell, fit_scale, rotate, snap)

G = Geometry(scale=3.0, arena_cm=200)


def test_origin_is_bottom_left():
    assert G.to_canvas(0, 0) == (0.0, 600.0)


def test_top_left_maps_to_canvas_origin():
    assert G.to_canvas(0, 200) == (0.0, 0.0)


def test_far_corner():
    assert G.to_canvas(200, 0) == (600.0, 600.0)


def test_round_trip():
    for x, y in [(0, 0), (17, 3), (100, 100), (199, 199)]:
        px, py = G.to_canvas(x, y)
        assert G.to_arena(px, py) == (x, y)


def test_rect_is_flipped_and_upright():
    x0, y0, x1, y1 = G.rect(50, 90, 10, 10)
    assert (x0, x1) == (150.0, 180.0)
    assert y0 < y1
    assert (y0, y1) == (300.0, 330.0)
    assert y1 - y0 == 10 * G.scale


def test_fit_scale_clamps():
    assert fit_scale(900, 200) == 680 / 200
    assert fit_scale(400, 200) == 480 / 200
    assert fit_scale(2000, 200) == 720 / 200


def test_snap():
    assert snap(97, 10) == 90
    assert snap(90, 10) == 90
    assert snap(0, 10) == 0
    assert snap(9.9, 10) == 0


def test_cells_match_the_tablet():
    sw, ne = cell_to_corners(5, 9)
    assert (sw, ne) == (Point(50, 90), Point(59, 99))
    assert corners_to_cell(sw) == (5, 9)
    assert centre_to_tablet(15, 15) == (1.0, 1.0)
    assert centre_to_tablet(55, 95) == (5.0, 9.0)


def test_rotate_east_sends_forward_to_plus_x():
    (x, y), = rotate([(0, 10)], 50, 50, 90)
    assert math.isclose(x, 60) and math.isclose(y, 50, abs_tol=1e-9)


def test_rotate_east_sends_right_hand_to_south():
    (x, y), = rotate([(10, 0)], 50, 50, 90)
    assert math.isclose(x, 50, abs_tol=1e-9) and math.isclose(y, 40)


def test_car_camera_is_at_the_front():
    north = car_shapes(100, 100, Direction.NORTH)
    assert len(north.body) == 8 and len(north.wheels) == 4
    cx, cy, r = north.camera
    assert cy > 100 and math.isclose(cx, 100, abs_tol=1e-9) and r > 0
    west = car_shapes(100, 100, Direction.WEST)
    wx, wy, _ = west.camera
    assert wx < 100 and math.isclose(wy, 100, abs_tol=1e-9)


def test_car_body_spans_the_configured_chassis():
    body = car_shapes(100, 100, Direction.NORTH).body
    xs = [p[0] for p in body]
    ys = [p[1] for p in body]
    w, l = config.ROBOT_BODY_CM
    assert math.isclose(max(xs) - min(xs), w) and math.isclose(max(ys) - min(ys), l)
```

- [ ] **Step 2: run, expect ImportError**

Run: `./.venv/bin/python -m pytest tests/test_geometry.py -q`

- [ ] **Step 3: implement `simulator/geometry.py`**

```python
"""
Arena centimetres <-> canvas pixels, and the small pure geometry the simulator draws with.

The arena's origin is bottom-left with y up; a canvas's origin is top-left with y down. This is
the ONLY module that converts between them. Anything that computes a pixel from a centimetre
anywhere else is a bug waiting to render the arena upside down.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import config
from pathfinding.world.primitives import Direction, Point

# Compass heading in degrees, clockwise from north. The tablet uses the same convention.
HEADING_DEG = {Direction.NORTH: 0, Direction.EAST: 90, Direction.SOUTH: 180, Direction.WEST: 270}

# Canvas size limits in pixels, and the vertical room left for the title bar and transport bar.
_MIN_ARENA_PX, _MAX_ARENA_PX, _RESERVED_PX = 480, 720, 220


@dataclass(frozen=True)
class Geometry:
    """Conversion for one canvas: `scale` pixels per centimetre over an `arena_cm` square."""

    scale: float
    arena_cm: int

    @property
    def arena_px(self) -> float:
        return self.arena_cm * self.scale

    def to_canvas(self, x_cm: float, y_cm: float) -> tuple[float, float]:
        return x_cm * self.scale, (self.arena_cm - y_cm) * self.scale

    def to_arena(self, px: float, py: float) -> tuple[float, float]:
        return px / self.scale, self.arena_cm - py / self.scale

    def rect(self, x_cm: float, y_cm: float, w_cm: float, h_cm: float) -> tuple[float, float, float, float]:
        """Canvas bbox (x0, y0, x1, y1), y0 < y1, of a box whose SOUTH-WEST corner is (x_cm, y_cm)."""
        x0, y1 = self.to_canvas(x_cm, y_cm)
        x1, y0 = self.to_canvas(x_cm + w_cm, y_cm + h_cm)
        return x0, y0, x1, y1


def fit_scale(screen_height_px: int, arena_cm: int) -> float:
    """Pixels per cm so the arena fits the screen with room for the bars, within sane bounds."""
    arena_px = max(_MIN_ARENA_PX, min(_MAX_ARENA_PX, screen_height_px - _RESERVED_PX))
    return arena_px / arena_cm


def snap(value_cm: float, step_cm: int) -> int:
    """Round down to the nearest multiple of step_cm (clicks onto the obstacle grid)."""
    return int(value_cm // step_cm) * step_cm


def cell_to_corners(cx: int, cy: int) -> tuple[Point, Point]:
    """Tablet cell -> inclusive corners of the obstacle occupying it."""
    size = config.OBSTACLE_SIZE_CM
    return Point(cx * size, cy * size), Point(cx * size + size - 1, cy * size + size - 1)


def corners_to_cell(south_west: Point) -> tuple[int, int]:
    size = config.OBSTACLE_SIZE_CM
    return south_west.x // size, south_west.y // size


def centre_to_tablet(x_cm: float, y_cm: float) -> tuple[float, float]:
    """Robot centre in cm -> the tablet's decimal cell, whose (1, 1) is the centre of the start pose."""
    size = config.OBSTACLE_SIZE_CM
    return (x_cm - size / 2) / size, (y_cm - size / 2) / size


def rotate(points: list[tuple[float, float]], cx: float, cy: float, heading_deg: float) -> list[tuple[float, float]]:
    """
    Place local points around (cx, cy). Local +y is "forward" and local +x is the robot's
    right-hand side; heading is clockwise from north, so facing EAST sends forward to +x.
    """
    t = math.radians(heading_deg)
    s, c = math.sin(t), math.cos(t)
    return [(cx + dx * c + dy * s, cy - dx * s + dy * c) for dx, dy in points]


@dataclass(frozen=True)
class CarShapes:
    body: list[tuple[float, float]]
    wheels: list[list[tuple[float, float]]]
    camera: tuple[float, float, float]


def car_shapes(cx_cm: float, cy_cm: float, direction: Direction) -> CarShapes:
    """The top-down car at a pose, in arena cm: chamfered body, four wheels, camera dot at the front."""
    w, l = config.ROBOT_BODY_CM
    hw, hl, ch = w / 2, l / 2, 2.0          # half width, half length, corner chamfer
    body = [(-hw + ch, hl), (hw - ch, hl), (hw, hl - ch), (hw, -hl + ch),
            (hw - ch, -hl), (-hw + ch, -hl), (-hw, -hl + ch), (-hw, hl - ch)]
    ww, wl = 3.0, 6.0                       # wheel width and length
    wheels = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            x, y = sx * (hw + ww / 2 - 0.5), sy * (hl - wl / 2 - 2)
            wheels.append([(x - ww / 2, y + wl / 2), (x + ww / 2, y + wl / 2),
                           (x + ww / 2, y - wl / 2), (x - ww / 2, y - wl / 2)])
    heading = HEADING_DEG[direction]
    (camx, camy), = rotate([(0, hl - 2.5)], cx_cm, cy_cm, heading)
    return CarShapes(
        body=rotate(body, cx_cm, cy_cm, heading),
        wheels=[rotate(q, cx_cm, cy_cm, heading) for q in wheels],
        camera=(camx, camy, 2.0),
    )
```

- [ ] **Step 4: run, expect 12 passed**

Run: `./.venv/bin/python -m pytest tests/test_geometry.py -q`

---

### Task 3: arena (state, edit rules, open/save)

**Files:**
- Create: `algorithm/simulator/arena.py`
- Test: `algorithm/tests/test_arena.py`

**Interfaces:**
- Consumes: `Robot.planned`, `config.START_POSE`, `config.START_ZONE_CM`, `config.IMAGE_ID_MIN/MAX`, `config.ARENA_SIZE_CM`, `config.GRID_SIZE`, `geometry.cell_to_corners`.
- Produces:
  - `class ArenaError(ValueError)`
  - `Arena(robot: Robot, obstacles: tuple[Obstacle, ...])` frozen; methods return new Arenas: `add(cx, cy, direction=Direction.SOUTH) -> Arena`, `remove(image_id) -> Arena`, `move(image_id, cx, cy) -> Arena`, `cycle_face(image_id) -> Arena`, `at(x_cm, y_cm) -> Obstacle | None`, `find(image_id) -> Obstacle | None`, `next_id() -> int`, `world() -> World`.
  - `empty() -> Arena`, `from_request(data: dict) -> Arena`, `to_request(arena) -> dict`, `load(path) -> Arena`, `save(path, arena) -> None`.

- [ ] **Step 1: failing tests**

`algorithm/tests/test_arena.py`:
```python
import json
import os

import pytest

import config
from pathfinding.world.primitives import Direction, Point
from simulator.arena import Arena, ArenaError, empty, from_request, load, save, to_request

TESTDATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testdata")


def test_empty_arena_has_the_configured_start_pose_and_no_obstacles():
    arena = empty()
    assert arena.obstacles == ()
    assert arena.robot.direction == Direction(config.START_POSE["direction"])
    assert arena.robot.south_west == Point(*config.START_POSE["south_west"])


def test_add_takes_lowest_unused_id_and_faces_south():
    arena = empty().add(5, 9).add(12, 6)
    assert [o.image_id for o in arena.obstacles] == [1, 2]
    assert arena.obstacles[0].south_west == Point(50, 90)
    assert arena.obstacles[0].north_east == Point(59, 99)
    assert arena.obstacles[0].direction == Direction.SOUTH
    assert arena.remove(1).add(3, 3 + 1).obstacles[-1].image_id == 1


def test_add_refuses_start_zone_arena_edge_and_overlap():
    arena = empty().add(5, 9)
    with pytest.raises(ArenaError, match="start zone"):
        arena.add(3, 3)
    with pytest.raises(ArenaError, match="outside"):
        arena.add(20, 0)
    with pytest.raises(ArenaError, match="overlaps obstacle 1"):
        arena.add(5, 9)


def test_add_refuses_when_ids_run_out():
    arena = empty()
    for n in range(config.IMAGE_ID_MAX - config.IMAGE_ID_MIN + 1):
        arena = arena.add(4 + n % 16, 4 + n // 16)
    with pytest.raises(ArenaError, match="no free obstacle id"):
        arena.add(19, 19)


def test_move_cycle_remove_and_lookup():
    arena = empty().add(5, 9).add(12, 6)
    arena = arena.move(2, 15, 15)
    assert arena.find(2).south_west == Point(150, 150)
    with pytest.raises(ArenaError, match="overlaps obstacle 1"):
        arena.move(2, 5, 9)
    faces = []
    for _ in range(4):
        arena = arena.cycle_face(1)
        faces.append(arena.find(1).direction)
    assert faces == [Direction.WEST, Direction.NORTH, Direction.EAST, Direction.SOUTH]
    assert arena.at(55, 95).image_id == 1
    assert arena.at(55, 80) is None
    assert arena.remove(1).find(1) is None


def test_request_round_trip_matches_testdata():
    with open(os.path.join(TESTDATA, "02-four-obstacles.json")) as f:
        data = json.load(f)
    arena = from_request(data)
    assert [o.image_id for o in arena.obstacles] == [11, 12, 13, 14]
    assert arena.find(13).direction == Direction.WEST
    assert arena.find(13).south_west == Point(150, 150)
    out = to_request(arena)
    assert out["obstacles"] == data["obstacles"]
    assert out["robot"] == data["robot"]
    assert out["verbose"] is False


def test_from_request_applies_the_parity_bump():
    data = {"robot": {"direction": "NORTH", "south_west": {"x": 0, "y": 0}, "north_east": {"x": 29, "y": 29}},
            "obstacles": []}
    assert from_request(data).robot.north_east == Point(30, 30)


def test_save_then_load(tmp_path):
    arena = empty().add(5, 9).cycle_face(1)
    path = tmp_path / "arena.json"
    save(path, arena)
    again = load(path)
    assert again == arena
    assert json.loads(path.read_text())["obstacles"][0]["direction"] == "WEST"


def test_world_builds_from_arena():
    world = empty().add(5, 9).world()
    assert world.size == config.GRID_SIZE
    assert len(world.obstacles) == 1
```

- [ ] **Step 2: run, expect ImportError**

- [ ] **Step 3: implement `simulator/arena.py`**

```python
"""
The editable arena: the robot's start pose plus obstacles, with the placement rules, and the
JSON the RPi sends (`PathfindingRequest`) as its file format.

Immutable: every edit returns a new Arena, so the window can hold "the arena before this drag"
for free and a refused edit changes nothing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

import config
from pathfinding.world.primitives import Direction, Point
from pathfinding.world.world import Obstacle, Robot, World
from simulator.geometry import cell_to_corners

FACE_ORDER = (Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST)


class ArenaError(ValueError):
    """An edit the arena refuses. The message is shown to the user as-is."""


@dataclass(frozen=True)
class Arena:
    robot: Robot
    obstacles: tuple[Obstacle, ...]

    def find(self, image_id: int) -> Obstacle | None:
        return next((o for o in self.obstacles if o.image_id == image_id), None)

    def at(self, x_cm: float, y_cm: float) -> Obstacle | None:
        """The obstacle covering an arena point, if any."""
        for o in self.obstacles:
            if o.south_west.x <= x_cm <= o.north_east.x + 1 and o.south_west.y <= y_cm <= o.north_east.y + 1:
                return o
        return None

    def next_id(self) -> int:
        used = {o.image_id for o in self.obstacles}
        for candidate in range(config.IMAGE_ID_MIN, config.IMAGE_ID_MAX + 1):
            if candidate not in used:
                return candidate
        raise ArenaError(f"no free obstacle id: all of {config.IMAGE_ID_MIN}-{config.IMAGE_ID_MAX} are used")

    def add(self, cx: int, cy: int, direction: Direction = Direction.SOUTH) -> Arena:
        image_id = self.next_id()
        south_west, north_east = cell_to_corners(cx, cy)
        self._check_placement(south_west, north_east, ignore_id=None)
        return replace(self, obstacles=self.obstacles + (Obstacle(direction, south_west, north_east, image_id),))

    def remove(self, image_id: int) -> Arena:
        return replace(self, obstacles=tuple(o for o in self.obstacles if o.image_id != image_id))

    def move(self, image_id: int, cx: int, cy: int) -> Arena:
        old = self._require(image_id)
        south_west, north_east = cell_to_corners(cx, cy)
        self._check_placement(south_west, north_east, ignore_id=image_id)
        moved = Obstacle(old.direction, south_west, north_east, image_id)
        return replace(self, obstacles=tuple(moved if o.image_id == image_id else o for o in self.obstacles))

    def cycle_face(self, image_id: int) -> Arena:
        old = self._require(image_id)
        face = FACE_ORDER[(FACE_ORDER.index(old.direction) + 1) % 4]
        turned = Obstacle(face, old.south_west, old.north_east, image_id)
        return replace(self, obstacles=tuple(turned if o.image_id == image_id else o for o in self.obstacles))

    def world(self) -> World:
        return World(config.GRID_SIZE, self.robot, list(self.obstacles))

    def _require(self, image_id: int) -> Obstacle:
        found = self.find(image_id)
        if found is None:
            raise ArenaError(f"no obstacle {image_id}")
        return found

    def _check_placement(self, south_west: Point, north_east: Point, ignore_id: int | None) -> None:
        limit = config.ARENA_SIZE_CM
        if not (0 <= south_west.x and north_east.x < limit and 0 <= south_west.y and north_east.y < limit):
            raise ArenaError("outside the arena")
        zone = config.START_ZONE_CM
        if south_west.x < zone and south_west.y < zone:
            raise ArenaError("overlaps the start zone")
        for o in self.obstacles:
            if o.image_id == ignore_id:
                continue
            if not (north_east.x < o.south_west.x or south_west.x > o.north_east.x
                    or north_east.y < o.south_west.y or south_west.y > o.north_east.y):
                raise ArenaError(f"overlaps obstacle {o.image_id}")


def empty() -> Arena:
    pose = config.START_POSE
    robot = Robot.planned(Direction(pose["direction"]), Point(*pose["south_west"]), Point(*pose["north_east"]))
    return Arena(robot, ())


def _point(d: dict) -> Point:
    return Point(int(d["x"]), int(d["y"]))


def from_request(data: dict) -> Arena:
    """Parse a PathfindingRequest body. `verbose` is ignored."""
    r = data["robot"]
    robot = Robot.planned(Direction(r["direction"]), _point(r["south_west"]), _point(r["north_east"]))
    obstacles = tuple(
        Obstacle(Direction(o["direction"]), _point(o["south_west"]), _point(o["north_east"]), int(o["image_id"]))
        for o in data.get("obstacles", [])
    )
    return Arena(robot, obstacles)


def to_request(arena: Arena) -> dict:
    """The exact body the RPi would POST for this arena. Not verbose: it is for replay, not drawing."""
    def corners(e):
        return {"south_west": {"x": e.south_west.x, "y": e.south_west.y},
                "north_east": {"x": e.north_east.x, "y": e.north_east.y}}
    return {
        "verbose": False,
        "robot": {"direction": arena.robot.direction.value, **corners(arena.robot)},
        "obstacles": [{"image_id": o.image_id, "direction": o.direction.value, **corners(o)} for o in arena.obstacles],
    }


def load(path: str | Path) -> Arena:
    with open(path) as f:
        return from_request(json.load(f))


def save(path: str | Path, arena: Arena) -> None:
    with open(path, "w") as f:
        json.dump(to_request(arena), f, indent=2)
        f.write("\n")
```

Note on `to_request`: the testdata files write the robot's corners as `{"x": 0, "y": 0}`, `{"x": 30, "y": 30}` and obstacles with `south_west` before `north_east`; dict equality in the test does not care about key order, only that the key sets and values match. `verbose` is emitted first for readability of saved files.

- [ ] **Step 4: run, expect 9 passed; then the whole suite and smoke**

---

### Task 4: routes and playback

> **Superseded in part by the fix round:** `.superpowers/sdd/2026-09-03-simulator/task-4-fix-brief.md` (arc ordering in `Segment.compress`, `geometry.Pose`, continuous-pose frames, precomputed properties). The code below is the original brief; the fix brief wins where they differ, and `SPEC.md` "Playback" describes the result.

**Files:**
- Create: `algorithm/simulator/routes.py`, `algorithm/simulator/playback.py`
- Test: `algorithm/tests/test_routes.py`, `algorithm/tests/test_playback.py`

**Interfaces:**
- Consumes: `pathfinding.search.search.search/Segment/SearchResult`, `pathfinding.world.objective.generate_objectives`, `pathfinding.report.UnreachableObstacle`, `simulator.arena`.
- Produces:
  - `routes.Route(segments, unreachable, source_name, plan_ms)` frozen, `total_cost` property; `routes.RouteSource` Protocol (`name: str`, `plan(world) -> Route`); `routes.GreedyRouteSource` with `name = "Greedy, nearest first"`; `routes.SOURCES: tuple[RouteSource, ...]`.
  - `playback.CAPTURE_DWELL_FRAMES = 10`; `playback.Frame(vector, segment_index, captured_id, dwell)`; `playback.Playback(route)` with `frames`, `index`, `current`, `finished`, `step() -> Frame | None`, `reset()`, `seek(i)`, `distance_cm`, `seconds_at(i) -> float`, `estimated_seconds -> float`, `captured -> list[tuple[int, float]]`, `trail -> list[tuple[Vector, int]]`, `remaining -> list[tuple[Vector, int]]`, `next_id -> int | None`.

- [ ] **Step 1: failing tests**

`algorithm/tests/test_routes.py`:
```python
import os

from pathfinding.search.search import search
from pathfinding.world.objective import generate_objectives
from simulator.arena import load
from simulator.routes import SOURCES, GreedyRouteSource

TESTDATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testdata")


def test_greedy_source_is_the_planner_verbatim():
    world = load(os.path.join(TESTDATA, "02-four-obstacles.json")).world()
    route = GreedyRouteSource().plan(world)
    direct = search(world, generate_objectives(world))
    assert [s.image_id for s in route.segments] == [s.image_id for s in direct.segments]
    assert [s.cost for s in route.segments] == [s.cost for s in direct.segments]
    assert [s.instructions for s in route.segments] == [s.instructions for s in direct.segments]
    assert route.unreachable == direct.unreachable
    assert route.total_cost == sum(s.cost for s in direct.segments)
    assert route.plan_ms > 0
    assert route.source_name == "Greedy, nearest first"


def test_unreachable_is_carried():
    world = load(os.path.join(TESTDATA, "03-unreachable.json")).world()
    route = GreedyRouteSource().plan(world)
    assert [u.image_id for u in route.unreachable] == [13]


def test_registry_has_greedy_first():
    assert SOURCES[0].name == "Greedy, nearest first"
```

`algorithm/tests/test_playback.py`:
```python
import os

import config
from simulator.arena import load
from simulator.playback import CAPTURE_DWELL_FRAMES, Playback
from simulator.routes import GreedyRouteSource, Route

TESTDATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testdata")


def route_for(name):
    return GreedyRouteSource().plan(load(os.path.join(TESTDATA, name)).world())


def test_frames_are_cells_plus_dwell():
    route = route_for("02-four-obstacles.json")
    p = Playback(route)
    cells = sum(len(s.vectors) for s in route.segments)
    assert len(p.frames) == cells + CAPTURE_DWELL_FRAMES * len(route.segments)
    assert p.index == 0 and p.current is p.frames[0] and not p.finished


def test_capture_sits_on_each_segments_last_cell_then_dwells():
    route = route_for("02-four-obstacles.json")
    p = Playback(route)
    captures = [(i, f) for i, f in enumerate(p.frames) if f.captured_id is not None and not f.dwell]
    assert [f.captured_id for _, f in captures] == [s.image_id for s in route.segments]
    for i, f in captures:
        dwell = p.frames[i + 1:i + 1 + CAPTURE_DWELL_FRAMES]
        assert all(d.dwell and d.vector == f.vector and d.captured_id == f.captured_id for d in dwell)
    assert p.frames[captures[0][0] - 1].segment_index == 0


def test_distance_excludes_dwell_and_clock_adds_capture_time():
    route = route_for("02-four-obstacles.json")
    p = Playback(route)
    first_capture = next(i for i, f in enumerate(p.frames) if f.captured_id is not None)
    p.seek(first_capture + CAPTURE_DWELL_FRAMES)
    assert p.distance_cm == first_capture + 1
    assert p.estimated_seconds == (first_capture + 1) / config.ROBOT_SPEED_CM_S + config.CAPTURE_DWELL_S
    assert p.captured == [(route.segments[0].image_id, p.seconds_at(first_capture))]
    assert p.next_id == route.segments[1].image_id


def test_step_to_the_end_then_noop():
    p = Playback(route_for("01-single-obstacle.json"))
    n = 0
    while p.step() is not None:
        n += 1
    assert n == len(p.frames) - 1 and p.finished and p.step() is None
    assert [i for i, _ in p.captured] == [11]
    assert p.remaining == [] and len(p.trail) == p.distance_cm
    assert p.next_id is None


def test_reset_and_seek_clamp():
    p = Playback(route_for("01-single-obstacle.json"))
    p.seek(10 ** 6)
    assert p.finished
    p.seek(-5)
    assert p.index == 0
    p.step(); p.step()
    p.reset()
    assert p.index == 0 and p.captured == [] and p.distance_cm == 1


def test_trail_and_remaining_partition_the_cells():
    p = Playback(route_for("02-four-obstacles.json"))
    p.seek(300)
    cells = sum(len(s.vectors) for s in p.route.segments)
    assert len(p.trail) + len(p.remaining) == cells
    assert p.trail[-1][0] == p.current.vector


def test_empty_route():
    p = Playback(Route(segments=[], unreachable=[], source_name="none", plan_ms=0.0))
    assert p.frames == [] and p.current is None and p.finished and p.step() is None
    assert p.distance_cm == 0 and p.estimated_seconds == 0.0 and p.captured == [] and p.next_id is None
```

- [ ] **Step 2: run, expect ImportError**

- [ ] **Step 3: implement `simulator/routes.py`**

```python
"""
Where a route comes from. One protocol, so the shortest-time optimiser (checklist B.3) plugs in
as a second RouteSource and the window lists both without changing.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from pathfinding.report import UnreachableObstacle
from pathfinding.search.search import Segment, search
from pathfinding.world.objective import generate_objectives
from pathfinding.world.world import World


@dataclass(frozen=True)
class Route:
    segments: list[Segment]
    unreachable: list[UnreachableObstacle]
    source_name: str
    plan_ms: float

    @property
    def total_cost(self) -> int:
        return sum(s.cost for s in self.segments)


class RouteSource(Protocol):
    name: str

    def plan(self, world: World) -> Route: ...


class GreedyRouteSource:
    """The planner as it is: goal poses, then one greedy nearest-first search. Nothing altered."""

    name = "Greedy, nearest first"

    def plan(self, world: World) -> Route:
        started = time.perf_counter()
        result = search(world, generate_objectives(world))
        elapsed_ms = (time.perf_counter() - started) * 1000
        return Route(result.segments, result.unreachable, self.name, elapsed_ms)


SOURCES: tuple[RouteSource, ...] = (GreedyRouteSource(),)
```

- [ ] **Step 4: implement `simulator/playback.py`**

```python
"""
The animation timeline: the planner's cell-by-cell vectors flattened into frames, with a pause
at every capture, plus the numbers the window shows (distance, estimated clock, captured list).

Pure logic. Nothing here knows about tkinter or drawing.
"""
from __future__ import annotations

from dataclasses import dataclass

import config
from pathfinding.world.primitives import Vector
from simulator.routes import Route

# Frames the robot holds still at each obstacle so the capture moment is visible. Display
# pacing, not a physical constant, so it lives here rather than in config.
CAPTURE_DWELL_FRAMES = 10


@dataclass(frozen=True)
class Frame:
    vector: Vector
    segment_index: int
    captured_id: int | None      # set on a segment's last cell and its dwell frames
    dwell: bool                  # True for the repeated frames; they are not travel


class Playback:
    def __init__(self, route: Route) -> None:
        self.route = route
        self.frames: list[Frame] = []
        for index, segment in enumerate(route.segments):
            last = len(segment.vectors) - 1
            for i, vector in enumerate(segment.vectors):
                captured = segment.image_id if i == last else None
                self.frames.append(Frame(vector, index, captured, False))
            if segment.vectors:
                for _ in range(CAPTURE_DWELL_FRAMES):
                    self.frames.append(Frame(segment.vectors[last], index, segment.image_id, True))
        self.index = 0

    @property
    def current(self) -> Frame | None:
        return self.frames[self.index] if self.frames else None

    @property
    def finished(self) -> bool:
        return self.index >= len(self.frames) - 1

    def step(self) -> Frame | None:
        if self.finished:
            return None
        self.index += 1
        return self.current

    def reset(self) -> None:
        self.index = 0

    def seek(self, index: int) -> None:
        self.index = max(0, min(index, len(self.frames) - 1)) if self.frames else 0

    def _travel(self, upto: int) -> int:
        return sum(1 for f in self.frames[:upto + 1] if not f.dwell)

    def _captures_upto(self, upto: int) -> int:
        return sum(1 for f in self.frames[:upto + 1] if f.captured_id is not None and not f.dwell)

    @property
    def distance_cm(self) -> int:
        """Cells driven so far. One cell is one centimetre; dwell frames do not move."""
        return self._travel(self.index) if self.frames else 0

    def seconds_at(self, index: int) -> float:
        """Estimated elapsed time when frame `index` is reached, driving plus captures so far."""
        return (self._travel(index) / config.ROBOT_SPEED_CM_S
                + self._captures_upto(index) * config.CAPTURE_DWELL_S)

    @property
    def estimated_seconds(self) -> float:
        return self.seconds_at(self.index) if self.frames else 0.0

    @property
    def captured(self) -> list[tuple[int, float]]:
        """(image_id, estimated seconds) for every capture reached, in visit order."""
        return [(f.captured_id, self.seconds_at(i))
                for i, f in enumerate(self.frames[:self.index + 1])
                if f.captured_id is not None and not f.dwell]

    @property
    def next_id(self) -> int | None:
        """The obstacle the robot is heading for, or None once every capture is done."""
        done = {image_id for image_id, _ in self.captured}
        return next((s.image_id for s in self.route.segments if s.image_id not in done), None)

    @property
    def trail(self) -> list[tuple[Vector, int]]:
        return [(f.vector, f.segment_index) for f in self.frames[:self.index + 1] if not f.dwell]

    @property
    def remaining(self) -> list[tuple[Vector, int]]:
        return [(f.vector, f.segment_index) for f in self.frames[self.index + 1:] if not f.dwell]
```

- [ ] **Step 5: run, expect all green; suite and smoke still green**

---

### Task 5: arena_view (Scene, Palette, drawing through a Painter)

**Files:**
- Create: `algorithm/simulator/painters.py` (protocol and `RecordingPainter` only in this task), `algorithm/simulator/arena_view.py`
- Test: `algorithm/tests/test_arena_view.py`

**Interfaces:**
- Consumes: `geometry.Geometry`, `geometry.car_shapes`, `geometry.HEADING_DEG`, `arena.Arena`, `Obstacle`, `Robot`, `Vector`.
- Produces:
  - `painters.Painter` Protocol: `rect(x0, y0, x1, y1, *, fill=None, outline=None, width=1.0, dash=None)`, `line(points, *, fill, width=1.0, dash=None)`, `polygon(points, *, fill=None, outline=None, width=1.0)`, `oval(x0, y0, x1, y1, *, fill=None, outline=None, width=1.0)`, `text(x, y, text, *, fill, size, bold=False, mono=False, anchor="center")`. Colours are `#rrggbb` strings or None; `dash` is a tuple like `(6, 4)` or None; `anchor` is a tk anchor (`center`, `n`, `s`, `e`, `w`, `ne`, `nw`, `se`, `sw`).
  - `painters.RecordingPainter`: appends `(op, args, kwargs)` tuples to `.calls`.
  - `arena_view.Palette` constants (the Global Constraints palette, as module-level names: `PAPER, GRID_MINOR, GRID_MAJOR, INK, MUTED, WINDOW, PANEL, RULE, START_FILL, START_EDGE, FACE, CAMERA, PLANNED, SEGMENT_COLOURS`) and `segment_colour(index) -> str` (cycles).
  - `arena_view.Scene(arena: Arena, colour_of: dict[int, str], unreachable: dict[int, str], captured: frozenset[int], next_id: int | None, pose: Pose | None, trail: tuple[tuple[Pose, int], ...], remaining: tuple[tuple[Pose, int], ...])` frozen dataclass with defaults so `Scene(arena)` is valid. `Pose` is `geometry.Pose(x, y, heading_deg)` (added in Task 4's fix round); positions are robot-centre cm, already continuous, so NO `+ 0.5` cell-centre offset is applied to poses or trails.
  - `arena_view.draw_static(painter, geometry, scene)` and `arena_view.draw_dynamic(painter, geometry, scene)`.
  - `arena_view.AXIS_MARGIN_PX = 26` (canvas is `arena_px + AXIS_MARGIN_PX` tall and wide; the arena is drawn at offset (0, 0) and the axis labels sit below and to the right... see step 3).

- [ ] **Step 1: failing tests**

`algorithm/tests/test_arena_view.py`:
```python
import os

import config
from pathfinding.world.primitives import Direction
from simulator import arena_view as av
from simulator.arena import empty, load
from simulator.geometry import Geometry, Pose
from simulator.painters import RecordingPainter

TESTDATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testdata")
G = Geometry(scale=3.0, arena_cm=200)


def calls(painter, op):
    return [(args, kwargs) for name, args, kwargs in painter.calls if name == op]


def test_start_zone_is_bottom_left_and_grid_covers_arena():
    p = RecordingPainter()
    av.draw_static(p, G, av.Scene(empty()))
    rects = calls(p, "rect")
    start = [r for r in rects if r[1].get("fill") == av.START_FILL]
    assert len(start) == 1
    x0, y0, x1, y1 = start[0][0]
    assert (x0, y1) == (0.0, 600.0) and x1 == 120.0 and y0 == 480.0
    lines = calls(p, "line")
    assert sum(1 for l in lines if l[1].get("fill") == av.GRID_MAJOR) == 5 * 2
    assert sum(1 for l in lines if l[1].get("fill") == av.GRID_MINOR) == 16 * 2


def test_each_obstacle_gets_a_body_a_face_stripe_and_a_label():
    arena = load(os.path.join(TESTDATA, "02-four-obstacles.json"))
    p = RecordingPainter()
    av.draw_static(p, G, av.Scene(arena))
    bodies = [r for r in calls(p, "rect") if r[1].get("fill") == av.INK]
    stripes = [r for r in calls(p, "rect") if r[1].get("fill") == av.FACE]
    labels = [t for t in calls(p, "text") if t[0][2] in {"11", "12", "13", "14"}]
    assert len(bodies) == 4 and len(stripes) == 4 and len(labels) == 4
    # obstacle 11 at (50,90) faces SOUTH: its stripe is at the bottom edge of the body
    body = next(r for r in bodies if r[0][:2] == (150.0, 300.0))
    stripe = next(s for s in stripes if abs(s[0][3] - body[0][3]) < 1e-9 and s[0][0] == body[0][0])
    assert stripe[0][1] > body[0][1]


def test_unreachable_obstacle_uses_warning_style_and_reason():
    arena = load(os.path.join(TESTDATA, "03-unreachable.json"))
    p = RecordingPainter()
    av.draw_static(p, G, av.Scene(arena, unreachable={13: "NO_OBJECTIVES"}))
    warned = [r for r in calls(p, "rect") if r[1].get("outline") == av.FACE and r[1].get("dash")]
    assert len(warned) == 1
    assert any(t[0][2] == "NO_OBJECTIVES" for t in calls(p, "text"))


def test_car_is_drawn_at_the_pose_and_trail_uses_segment_colours():
    arena = empty().add(5, 9)
    pose = Pose(60, 40, 90)
    trail = ((Pose(15, 16, 0), 0), (Pose(15, 17, 0), 0))
    remaining = ((Pose(15, 18, 0), 1), (Pose(15, 19, 0), 1))
    p = RecordingPainter()
    av.draw_dynamic(p, G, av.Scene(arena, pose=pose, trail=trail, remaining=remaining,
                                    colour_of={1: av.segment_colour(0)}))
    polys = calls(p, "polygon")
    assert len(polys) == 5                      # body + 4 wheels
    ovals = calls(p, "oval")
    assert len(ovals) == 1 and ovals[0][1]["fill"] == av.CAMERA
    ox0, oy0, ox1, oy1 = ovals[0][0]
    assert (ox0 + ox1) / 2 > G.to_canvas(60, 40)[0]        # camera is east of the centre
    lines = calls(p, "line")
    assert any(l[1]["fill"] == av.segment_colour(0) for l in lines)
    assert any(l[1]["fill"] == av.PLANNED and l[1].get("dash") for l in lines)


def test_dynamic_draws_the_start_pose_when_there_is_no_route():
    p = RecordingPainter()
    av.draw_dynamic(p, G, av.Scene(empty()))
    assert len(calls(p, "polygon")) == 5 and len(calls(p, "line")) == 0


def test_segment_colours_cycle():
    assert av.segment_colour(0) == av.SEGMENT_COLOURS[0]
    assert av.segment_colour(8) == av.SEGMENT_COLOURS[0]
```

- [ ] **Step 2: run, expect ImportError**

- [ ] **Step 3: implement `simulator/painters.py` (protocol and recorder only)**

```python
"""
What arena_view draws with. A Painter is five primitives in canvas pixels; the window backs it
with a tk.Canvas and `--snapshot` backs it with a Pillow image, so one drawing routine serves
both. RecordingPainter is for tests.
"""
from __future__ import annotations

from typing import Protocol, Sequence

Points = Sequence[tuple[float, float]]


class Painter(Protocol):
    def rect(self, x0: float, y0: float, x1: float, y1: float, *, fill: str | None = None,
             outline: str | None = None, width: float = 1.0, dash: tuple[int, ...] | None = None) -> None: ...

    def line(self, points: Points, *, fill: str, width: float = 1.0,
             dash: tuple[int, ...] | None = None) -> None: ...

    def polygon(self, points: Points, *, fill: str | None = None, outline: str | None = None,
                width: float = 1.0) -> None: ...

    def oval(self, x0: float, y0: float, x1: float, y1: float, *, fill: str | None = None,
             outline: str | None = None, width: float = 1.0) -> None: ...

    def text(self, x: float, y: float, text: str, *, fill: str, size: int, bold: bool = False,
             mono: bool = False, anchor: str = "center") -> None: ...


class RecordingPainter:
    """Records every call as (op, args, kwargs). Tests assert on what was drawn, not pixels."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def rect(self, *args, **kwargs):
        self.calls.append(("rect", args, kwargs))

    def line(self, *args, **kwargs):
        self.calls.append(("line", args, kwargs))

    def polygon(self, *args, **kwargs):
        self.calls.append(("polygon", args, kwargs))

    def oval(self, *args, **kwargs):
        self.calls.append(("oval", args, kwargs))

    def text(self, *args, **kwargs):
        self.calls.append(("text", args, kwargs))
```

- [ ] **Step 4: implement `simulator/arena_view.py`**

Layout: the canvas is `arena_px + AXIS_MARGIN_PX` wide and tall. The arena occupies `(0, 0)` to `(arena_px, arena_px)`; axis labels are drawn in the margin below (x labels, anchor `n`) and to the right (y labels, anchor `w`). Draw order in `draw_static`: paper, minor grid, major grid, start zone, obstacles (body, stripe, label; unreachable variant), arena border, axis labels. `draw_dynamic`: remaining route (dashed, PLANNED, one `line` per segment index), trail (one `line` per segment index in its colour, width 3), then the car at `scene.pose` or, with no route, a `Pose` at the robot's centre with its start heading (footprint dashed MUTED square from the Robot's own extents, body polygon fill `#FFFFFF` outline INK width 2, wheels INK, camera oval CAMERA). A trail or remaining segment with a single point is skipped (a line needs two).

```python
"""
Drawing the arena. Pure: a Scene in, painter calls out. Nothing here holds state or imports tk.

The look is graph paper with a car: green-lined paper, ink obstacles with a red mark on the
image face, and a top-down car with wheels and a camera dot so turns are visible without a
separate heading arrow.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import groupby

import config
from pathfinding.world.primitives import Direction
from pathfinding.world.world import Obstacle, Robot
from simulator.arena import Arena
from simulator.geometry import HEADING_DEG, Geometry, Pose, car_shapes
from simulator.painters import Painter

PAPER, GRID_MINOR, GRID_MAJOR = "#FDFDFA", "#D5E8DC", "#A8CDB6"
INK, MUTED, WINDOW, PANEL, RULE = "#1B2A2F", "#6A7A7E", "#F7F7F2", "#FFFFFF", "#E3E7E1"
START_FILL, START_EDGE = "#E8F1EA", "#2A9D6B"
FACE, CAMERA, PLANNED, BODY_FILL = "#E4572E", "#2457A8", "#9AA5A8", "#FFFFFF"
SEGMENT_COLOURS = ("#2457A8", "#E4572E", "#2A9D6B", "#8E5AC8", "#D99A00", "#0E9AA7", "#C2185B", "#7A5230")

AXIS_MARGIN_PX = 26
GRID_MINOR_CM, GRID_MAJOR_CM = 10, 50
FACE_STRIPE_CM = 1.5


def segment_colour(index: int) -> str:
    return SEGMENT_COLOURS[index % len(SEGMENT_COLOURS)]


@dataclass(frozen=True)
class Scene:
    arena: Arena
    colour_of: dict[int, str] = field(default_factory=dict)      # image_id -> segment colour
    unreachable: dict[int, str] = field(default_factory=dict)    # image_id -> reason
    captured: frozenset[int] = frozenset()
    next_id: int | None = None
    pose: Pose | None = None
    trail: tuple[tuple[Pose, int], ...] = ()
    remaining: tuple[tuple[Pose, int], ...] = ()


def draw_static(p: Painter, g: Geometry, scene: Scene) -> None:
    size = g.arena_px
    p.rect(0, 0, size, size, fill=PAPER)
    for cm in range(0, g.arena_cm + 1, GRID_MINOR_CM):
        major = cm % GRID_MAJOR_CM == 0
        colour, width = (GRID_MAJOR, 1.2) if major else (GRID_MINOR, 0.8)
        x, _ = g.to_canvas(cm, 0)
        _, y = g.to_canvas(0, cm)
        p.line([(x, 0), (x, size)], fill=colour, width=width)
        p.line([(0, y), (size, y)], fill=colour, width=width)
    zone = config.START_ZONE_CM
    p.rect(*g.rect(0, 0, zone, zone), fill=START_FILL, outline=START_EDGE, width=1.5, dash=(6, 4))
    zx, zy = g.to_canvas(zone / 2, 3)
    p.text(zx, zy, "start", fill=START_EDGE, size=10, mono=True, anchor="s")
    for obstacle in scene.arena.obstacles:
        _draw_obstacle(p, g, obstacle, scene)
    p.rect(0, 0, size, size, outline=INK, width=2)
    for cm in range(0, g.arena_cm + 1, GRID_MAJOR_CM):
        x, _ = g.to_canvas(cm, 0)
        _, y = g.to_canvas(0, cm)
        p.text(x, size + 4, str(cm), fill=MUTED, size=10, mono=True, anchor="n")
        p.text(size + 4, y, str(cm), fill=MUTED, size=10, mono=True, anchor="w")


def _draw_obstacle(p: Painter, g: Geometry, o: Obstacle, scene: Scene) -> None:
    side = o.clearance
    x0, y0, x1, y1 = g.rect(o.south_west.x, o.south_west.y, side, side)
    reason = scene.unreachable.get(o.image_id)
    if reason is not None:
        p.rect(x0, y0, x1, y1, fill=PAPER, outline=FACE, width=2, dash=(4, 3))
        label_colour = FACE
    else:
        p.rect(x0, y0, x1, y1, fill=INK)
        label_colour = PAPER
    stripe = FACE_STRIPE_CM
    sx, sy = o.south_west.x, o.south_west.y
    stripe_rect = {
        Direction.NORTH: g.rect(sx, sy + side - stripe, side, stripe),
        Direction.SOUTH: g.rect(sx, sy, side, stripe),
        Direction.EAST: g.rect(sx + side - stripe, sy, stripe, side),
        Direction.WEST: g.rect(sx, sy, stripe, side),
    }[o.direction]
    p.rect(*stripe_rect, fill=FACE)
    p.text((x0 + x1) / 2, (y0 + y1) / 2, str(o.image_id), fill=label_colour, size=12, bold=True)
    if reason is not None:
        p.text((x0 + x1) / 2, y1 + 3, reason, fill=FACE, size=9, mono=True, anchor="n")


def draw_dynamic(p: Painter, g: Geometry, scene: Scene) -> None:
    _draw_route(p, g, scene.remaining, colour=None)
    _draw_route(p, g, scene.trail, colour="segment")
    robot = scene.arena.robot
    pose = scene.pose if scene.pose is not None else Pose(robot.centre.x, robot.centre.y, HEADING_DEG[robot.direction])
    _draw_car(p, g, robot, pose)


def _draw_route(p: Painter, g: Geometry, poses: tuple[tuple[Pose, int], ...], colour: str | None) -> None:
    for index, group in groupby(poses, key=lambda item: item[1]):
        points = [g.to_canvas(pose.x, pose.y) for pose, _ in group]
        if len(points) < 2:
            continue
        if colour is None:
            p.line(points, fill=PLANNED, width=2, dash=(5, 6))
        else:
            p.line(points, fill=segment_colour(index), width=3)


def _draw_car(p: Painter, g: Geometry, robot: Robot, pose: Pose) -> None:
    cx, cy = pose.x, pose.y
    half = robot.clearance / 2
    p.rect(*g.rect(cx - half, cy - half, robot.clearance, robot.clearance), outline=MUTED, width=1, dash=(3, 3))
    car = car_shapes(pose)
    for wheel in car.wheels:
        p.polygon([g.to_canvas(x, y) for x, y in wheel], fill=INK)
    p.polygon([g.to_canvas(x, y) for x, y in car.body], fill=BODY_FILL, outline=INK, width=2)
    x, y, r = car.camera
    px, py = g.to_canvas(x, y)
    rp = r * g.scale
    p.oval(px - rp, py - rp, px + rp, py + rp, fill=CAMERA)
```

Poses are robot-centre positions from playback (continuous floats), so they are drawn as-is; obstacles keep their corner-based `g.rect`.

- [ ] **Step 5: run, expect 6 passed; suite green**

---

### Task 6: PilPainter, snapshot, `python -m simulator --snapshot`

**Files:**
- Modify: `algorithm/simulator/painters.py` (add `PilPainter`)
- Create: `algorithm/simulator/snapshot.py`, `algorithm/simulator/__main__.py`
- Modify: `algorithm/requirements.txt` (add `Pillow>=10` under a "Dev only" comment)
- Test: `algorithm/tests/test_snapshot.py`

**Interfaces:**
- Consumes: Task 5's `draw_static/draw_dynamic/Scene`, Task 4's `Playback`, `routes.SOURCES`, `arena.load`.
- Produces: `painters.PilPainter(image: PIL.Image.Image)`; `snapshot.render(arena, *, frame: int | None, source_name: str | None, scale: float) -> PIL.Image.Image`; `snapshot.write(arena_path, out_path, frame, scale) -> None`; `__main__.py` CLI: `--arena PATH` (default `testdata/02-four-obstacles.json`), `--snapshot OUT.png`, `--frame N` (default: last frame), `--scale PX_PER_CM` (default 3.2), `--selftest` (wired in Task 7; in this task it prints "selftest needs the window; see Task 7" and exits 2).

- [ ] **Step 1: failing test**

`algorithm/tests/test_snapshot.py`:
```python
import os

from PIL import Image

from simulator import arena_view as av
from simulator.arena import load
from simulator.snapshot import render, write

TESTDATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testdata")


def test_render_has_the_arena_size_plus_margin():
    image = render(load(os.path.join(TESTDATA, "02-four-obstacles.json")), frame=None, source_name=None, scale=2.0)
    assert image.size == (400 + av.AXIS_MARGIN_PX, 400 + av.AXIS_MARGIN_PX)
    # start zone corner is tinted, an obstacle cell is ink
    assert image.getpixel((5, 395)) != image.getpixel((5, 5))
    assert image.getpixel((103, 203)) == (0x1B, 0x2A, 0x2F)   # inside obstacle 11's body, clear of its label


def test_write_creates_a_png(tmp_path):
    out = tmp_path / "shot.png"
    write(os.path.join(TESTDATA, "01-single-obstacle.json"), out, frame=0, scale=2.0)
    assert out.exists() and Image.open(out).format == "PNG"
```

- [ ] **Step 2: run, expect ImportError**

- [ ] **Step 3: `PilPainter`**

Append to `painters.py`:
```python
class PilPainter:
    """Paints onto a Pillow image. Fonts: the first system TTF found from the same candidate
    families the window uses, else Pillow's default. Dev-only; the window never imports this."""

    UI_FILES = ("Avenir Next.ttc", "HelveticaNeue.ttc", "segoeui.ttf", "DejaVuSans.ttf", "Helvetica.ttc")
    MONO_FILES = ("Menlo.ttc", "consola.ttf", "DejaVuSansMono.ttf", "Courier New.ttf")

    def __init__(self, image) -> None:
        from PIL import ImageDraw
        self.image = image
        self.draw = ImageDraw.Draw(image)
        self._fonts: dict[tuple[bool, bool, int], object] = {}

    def _font(self, mono: bool, bold: bool, size: int):
        from PIL import ImageFont
        key = (mono, bold, size)
        if key not in self._fonts:
            font = None
            for name in (self.MONO_FILES if mono else self.UI_FILES):
                try:
                    font = ImageFont.truetype(name, size, index=1 if bold and name.endswith(".ttc") else 0)
                    break
                except OSError:
                    continue
            self._fonts[key] = font or ImageFont.load_default(size)
        return self._fonts[key]

    def rect(self, x0, y0, x1, y1, *, fill=None, outline=None, width=1.0, dash=None):
        if dash and outline:
            self.draw.rectangle([x0, y0, x1, y1], fill=fill)
            self._dashed([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], outline, width, dash)
        else:
            self.draw.rectangle([x0, y0, x1, y1], fill=fill, outline=outline, width=max(1, round(width)))

    def line(self, points, *, fill, width=1.0, dash=None):
        if dash:
            self._dashed(list(points), fill, width, dash)
        else:
            self.draw.line(list(points), fill=fill, width=max(1, round(width)), joint="curve")

    def polygon(self, points, *, fill=None, outline=None, width=1.0):
        self.draw.polygon(list(points), fill=fill, outline=outline, width=max(1, round(width)))

    def oval(self, x0, y0, x1, y1, *, fill=None, outline=None, width=1.0):
        self.draw.ellipse([x0, y0, x1, y1], fill=fill, outline=outline, width=max(1, round(width)))

    def text(self, x, y, text, *, fill, size, bold=False, mono=False, anchor="center"):
        pil_anchor = {"center": "mm", "n": "ma", "s": "ms", "e": "rm", "w": "lm",
                      "nw": "la", "ne": "ra", "sw": "ls", "se": "rs"}[anchor]
        self.draw.text((x, y), text, fill=fill, font=self._font(mono, bold, size), anchor=pil_anchor)

    def _dashed(self, points, colour, width, dash):
        import math
        on, off = dash[0], dash[1] if len(dash) > 1 else dash[0]
        w = max(1, round(width))
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            length = math.hypot(bx - ax, by - ay)
            if length == 0:
                continue
            ux, uy = (bx - ax) / length, (by - ay) / length
            pos = 0.0
            while pos < length:
                end = min(pos + on, length)
                self.draw.line([(ax + ux * pos, ay + uy * pos), (ax + ux * end, ay + uy * end)], fill=colour, width=w)
                pos = end + off
```

- [ ] **Step 4: `snapshot.py` and `__main__.py`**

`simulator/snapshot.py`:
```python
"""
Headless render of an arena to a PNG. This is how an agent with no display, or a README, gets a
picture of exactly what the window would draw: same Scene, same drawing code, a Pillow painter.
"""
from __future__ import annotations

from pathlib import Path

import config
from simulator import arena_view
from simulator.arena import Arena, load
from simulator.geometry import Geometry
from simulator.painters import PilPainter
from simulator.playback import Playback
from simulator.routes import SOURCES


def render(arena: Arena, *, frame: int | None, source_name: str | None, scale: float):
    from PIL import Image
    g = Geometry(scale=scale, arena_cm=config.ARENA_SIZE_CM)
    size = int(g.arena_px + arena_view.AXIS_MARGIN_PX)
    image = Image.new("RGB", (size, size), arena_view.WINDOW)
    painter = PilPainter(image)
    scene = arena_view.Scene(arena)
    if arena.obstacles:
        source = next((s for s in SOURCES if s.name == source_name), SOURCES[0])
        route = source.plan(arena.world())
        playback = Playback(route)
        playback.seek(len(playback.frames) - 1 if frame is None else frame)
        current = playback.current
        scene = arena_view.Scene(
            arena,
            colour_of={s.image_id: arena_view.segment_colour(i) for i, s in enumerate(route.segments)},
            unreachable={u.image_id: u.reason.value for u in route.unreachable},
            captured=frozenset(i for i, _ in playback.captured),
            next_id=playback.next_id,
            pose=current.pose if current else None,
            trail=tuple(playback.trail),
            remaining=tuple(playback.remaining),
        )
    arena_view.draw_static(painter, g, scene)
    arena_view.draw_dynamic(painter, g, scene)
    return image


def write(arena_path: str | Path, out_path: str | Path, frame: int | None, scale: float,
          source_name: str | None = None) -> None:
    render(load(arena_path), frame=frame, source_name=source_name, scale=scale).save(out_path, "PNG")
```

`simulator/__main__.py`:
```python
"""
python -m simulator                       open the window
python -m simulator --arena FILE          open with an arena loaded
python -m simulator --snapshot OUT.png    render FILE (default testdata/02) to a PNG, no window
python -m simulator --selftest            open, plan, step through, exit; a crash means a bug
"""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m simulator", description="MDP arena simulator.")
    parser.add_argument("--arena", default="testdata/02-four-obstacles.json", help="request JSON to load")
    parser.add_argument("--snapshot", metavar="OUT.png", help="render headlessly to a PNG and exit")
    parser.add_argument("--frame", type=int, default=None, help="playback frame for --snapshot (default: last)")
    parser.add_argument("--scale", type=float, default=3.2, help="pixels per cm for --snapshot")
    parser.add_argument("--selftest", action="store_true", help="open the window, drive one route, exit")
    args = parser.parse_args(argv)

    if args.snapshot:
        from simulator.snapshot import write
        write(args.arena, args.snapshot, args.frame, args.scale)
        print(f"wrote {args.snapshot}")
        return 0

    from simulator.app import run
    return run(arena_path=args.arena, selftest=args.selftest)


if __name__ == "__main__":
    sys.exit(main())
```
Until Task 7 lands, `simulator/app.py` does not exist; for this task create a stub `simulator/app.py` containing only:
```python
def run(arena_path: str, selftest: bool = False) -> int:
    print("the window arrives in Task 7; use --snapshot for now")
    return 2
```

- [ ] **Step 5: run tests, then look at the picture**

Run: `./.venv/bin/python -m pytest tests -q` → all green.
Run: `./.venv/bin/python -m simulator --snapshot /tmp/claude/shot.png` (use `$TMPDIR` if `/tmp/claude` is not writable) and open the PNG with the Read tool. Check against SPEC "Visual design": start zone bottom-left, four ink obstacles with a red stripe on the correct face (11 south edge, 12 west, 13 west, 14 east), labels readable, coloured trail per segment, car at the last pose with the camera dot facing the obstacle, axis labels 0..200. Fix anything that looks wrong before reporting, and put the PNG path in the report.

---

### Task 7: the window, phase 1 (static render)

**Files:**
- Create: `algorithm/simulator/fonts.py`
- Modify: `algorithm/simulator/painters.py` (add `TkPainter`)
- Replace: `algorithm/simulator/app.py`
- Test: `algorithm/tests/test_fonts.py` (the pure `pick` only)

**Interfaces:**
- Produces:
  - `fonts.UI_CANDIDATES`, `fonts.MONO_CANDIDATES`, `fonts.pick(installed: Iterable[str], candidates: Sequence[str], fallback: str) -> str`, `fonts.Fonts(root)` with `.ui(size, bold=False)` and `.mono(size)` returning cached `tkinter.font.Font` objects, and `.ui_family`, `.mono_family`.
  - `painters.TkPainter(canvas, fonts, tag)`: every item created carries `tag` so `canvas.delete(tag)` clears one layer.
  - `app.SimulatorApp(root, arena_path: str | None)` and `app.run(arena_path, selftest) -> int`.

- [ ] **Step 1: failing test for `pick`**

`algorithm/tests/test_fonts.py`:
```python
from simulator.fonts import MONO_CANDIDATES, UI_CANDIDATES, pick


def test_pick_first_installed_candidate():
    assert pick(["Arial", "Helvetica Neue", "Menlo"], UI_CANDIDATES, "TkDefaultFont") == "Helvetica Neue"
    assert pick(["Consolas"], MONO_CANDIDATES, "TkFixedFont") == "Consolas"


def test_pick_falls_back():
    assert pick([], UI_CANDIDATES, "TkDefaultFont") == "TkDefaultFont"
```

- [ ] **Step 2: `fonts.py`**

```python
"""Font families for the window, with fallbacks, because the demo laptop can be anyone's."""
from __future__ import annotations

import tkinter
import tkinter.font as tkfont
from typing import Iterable, Sequence

UI_CANDIDATES = ("Avenir Next", "Helvetica Neue", "Segoe UI", "DejaVu Sans", "Helvetica")
MONO_CANDIDATES = ("Menlo", "Consolas", "DejaVu Sans Mono", "Courier New", "Courier")


def pick(installed: Iterable[str], candidates: Sequence[str], fallback: str) -> str:
    have = set(installed)
    return next((c for c in candidates if c in have), fallback)


class Fonts:
    def __init__(self, root: tkinter.Misc) -> None:
        installed = tkfont.families(root)
        self.ui_family = pick(installed, UI_CANDIDATES, "TkDefaultFont")
        self.mono_family = pick(installed, MONO_CANDIDATES, "TkFixedFont")
        self._cache: dict[tuple[str, int, bool], tkfont.Font] = {}

    def _get(self, family: str, size: int, bold: bool) -> tkfont.Font:
        key = (family, size, bold)
        if key not in self._cache:
            self._cache[key] = tkfont.Font(family=family, size=size, weight="bold" if bold else "normal")
        return self._cache[key]

    def ui(self, size: int, bold: bool = False) -> tkfont.Font:
        return self._get(self.ui_family, size, bold)

    def mono(self, size: int) -> tkfont.Font:
        return self._get(self.mono_family, size, False)
```

- [ ] **Step 3: `TkPainter`** (append to `painters.py`)

```python
class TkPainter:
    """Paints onto a tk.Canvas. Everything it creates carries `tag`, so one layer clears at a time."""

    def __init__(self, canvas, fonts, tag: str) -> None:
        self.canvas, self.fonts, self.tag = canvas, fonts, tag

    def rect(self, x0, y0, x1, y1, *, fill=None, outline=None, width=1.0, dash=None):
        self.canvas.create_rectangle(x0, y0, x1, y1, fill=fill or "", outline=outline or "",
                                     width=width, dash=dash or (), tags=self.tag)

    def line(self, points, *, fill, width=1.0, dash=None):
        flat = [c for point in points for c in point]
        self.canvas.create_line(*flat, fill=fill, width=width, dash=dash or (), capstyle="round",
                                joinstyle="round", tags=self.tag)

    def polygon(self, points, *, fill=None, outline=None, width=1.0):
        flat = [c for point in points for c in point]
        self.canvas.create_polygon(*flat, fill=fill or "", outline=outline or "", width=width, tags=self.tag)

    def oval(self, x0, y0, x1, y1, *, fill=None, outline=None, width=1.0):
        self.canvas.create_oval(x0, y0, x1, y1, fill=fill or "", outline=outline or "", width=width, tags=self.tag)

    def text(self, x, y, text, *, fill, size, bold=False, mono=False, anchor="center"):
        font = self.fonts.mono(size) if mono else self.fonts.ui(size, bold)
        self.canvas.create_text(x, y, text=text, fill=fill, font=font, anchor=anchor, tags=self.tag)
```

- [ ] **Step 4: `app.py`, phase 1**

Structure to build (complete widgets now, handlers land in Tasks 8-11; unwired buttons show the status line message "coming in a later phase" when pressed):

```python
"""
The simulator window. Owns every piece of mutable state: the arena, the route, the playback,
the timer handle. Drawing is delegated to arena_view through a TkPainter; numbers come from
playback; rules come from arena. This file is wiring.
"""
from __future__ import annotations

import tkinter as tk

import config
from simulator import arena_view as av
from simulator.arena import Arena, empty, load
from simulator.fonts import Fonts
from simulator.geometry import Geometry, corners_to_cell, fit_scale
from simulator.painters import TkPainter

STATIC, DYNAMIC = "static", "dynamic"


class FlatButton(tk.Label):
    """A button drawn as a label so it looks the same on every platform (tk.Button ignores
    colours on macOS). `primary` is ink-filled; otherwise a hairline outline."""

    def __init__(self, master, text, command, fonts: Fonts, primary=False):
        fill, fg = (av.INK, av.PANEL) if primary else (av.PANEL, av.INK)
        super().__init__(master, text=text, font=fonts.ui(12), bg=fill, fg=fg, padx=12, pady=5,
                         cursor="hand2", highlightthickness=1, highlightbackground=av.INK if primary else "#C7CDC8")
        self.command = command
        self.bind("<Button-1>", lambda _e: self.command() if self.command and self["state"] != "disabled" else None)

    def set_text(self, text):
        self.configure(text=text)


class SimulatorApp:
    def __init__(self, root: tk.Tk, arena_path: str | None) -> None:
        self.root = root
        root.title("MDP simulator")
        root.configure(bg=av.WINDOW)
        self.fonts = Fonts(root)
        self.geometry = Geometry(fit_scale(root.winfo_screenheight(), config.ARENA_SIZE_CM), config.ARENA_SIZE_CM)
        self.arena: Arena = load(arena_path) if arena_path else empty()
        self.status_var = tk.StringVar(value="")
        self._build_layout()
        self.redraw_static()
        self.redraw_dynamic()

    # ----- layout -------------------------------------------------------------------------

    def _build_layout(self) -> None:
        size = int(self.geometry.arena_px + av.AXIS_MARGIN_PX)
        left = tk.Frame(self.root, bg=av.WINDOW, padx=14, pady=14)
        left.grid(row=0, column=0, sticky="nsew")
        self.canvas = tk.Canvas(left, width=size, height=size, bg=av.WINDOW, highlightthickness=0)
        self.canvas.pack()
        self.static_painter = TkPainter(self.canvas, self.fonts, STATIC)
        self.dynamic_painter = TkPainter(self.canvas, self.fonts, DYNAMIC)

        self.panel = tk.Frame(self.root, bg=av.PANEL, width=300, padx=18, pady=16)
        self.panel.grid(row=0, column=1, sticky="nsew")
        self.panel.grid_propagate(False)
        self._build_panel()

        self.bar = tk.Frame(self.root, bg=av.PANEL, padx=18, pady=10,
                            highlightthickness=1, highlightbackground=av.RULE)
        self.bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        self._build_bar()
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

    def _build_panel(self) -> None:
        f = self.fonts
        buttons = tk.Frame(self.panel, bg=av.PANEL)
        buttons.pack(anchor="w", pady=(0, 16))
        self.plan_button = FlatButton(buttons, "Plan route", self.on_plan, f, primary=True)
        self.plan_button.pack(side="left", padx=(0, 8))
        FlatButton(buttons, "Open arena", self.on_open, f).pack(side="left", padx=(0, 8))
        FlatButton(buttons, "Save arena", self.on_save, f).pack(side="left")

        self._heading("Route")
        self.route_frame = tk.Frame(self.panel, bg=av.PANEL)
        self.route_frame.pack(fill="x", pady=(0, 16))
        self._heading("Obstacles, click the arena to add")
        self.obstacle_frame = tk.Frame(self.panel, bg=av.PANEL)
        self.obstacle_frame.pack(fill="x", pady=(0, 16))
        self._heading("Captured, in order")
        self.captured_frame = tk.Frame(self.panel, bg=av.PANEL)
        self.captured_frame.pack(fill="x")
        tk.Label(self.panel, textvariable=self.status_var, font=f.ui(11), bg=av.PANEL, fg=av.FACE,
                 wraplength=260, justify="left").pack(side="bottom", anchor="w")

    def _heading(self, text: str) -> None:
        tk.Label(self.panel, text=text, font=self.fonts.ui(11, bold=True), bg=av.PANEL, fg=av.MUTED,
                 anchor="w").pack(fill="x", pady=(0, 6))

    def _row(self, parent, left: str, right: str = "", *, chip: str | None = None,
             chip_colour: str = av.MUTED, right_colour: str = av.MUTED) -> None:
        """One panel row: optional coloured chip, left text, right-aligned mono text."""
        row = tk.Frame(parent, bg=av.PANEL, highlightthickness=1, highlightbackground=av.RULE)
        row.pack(fill="x", pady=(0, 2))
        if chip is not None:
            tk.Label(row, text=chip, font=self.fonts.mono(11), bg=chip_colour, fg="#FFFFFF",
                     padx=6).pack(side="left", padx=(0, 8), pady=4)
        tk.Label(row, text=left, font=self.fonts.ui(12), bg=av.PANEL, fg=av.INK, anchor="w").pack(side="left", pady=4)
        tk.Label(row, text=right, font=self.fonts.mono(11), bg=av.PANEL, fg=right_colour, anchor="e").pack(side="right", pady=4)

    def _build_bar(self) -> None:
        f = self.fonts
        self.play_button = FlatButton(self.bar, "Play", self.on_play, f, primary=True)
        self.play_button.pack(side="left", padx=(0, 8))
        FlatButton(self.bar, "Step", self.on_step, f).pack(side="left", padx=(0, 8))
        FlatButton(self.bar, "Reset", self.on_reset, f).pack(side="left", padx=(0, 16))
        self.clock_var = tk.StringVar(value="0:00")
        self.count_var = tk.StringVar(value="")
        tk.Label(self.bar, textvariable=self.count_var, font=f.mono(12), bg=av.PANEL, fg=av.MUTED).pack(side="right")
        tk.Label(self.bar, text="est. of 6:00", font=f.ui(11), bg=av.PANEL, fg=av.MUTED).pack(side="right", padx=(4, 18))
        tk.Label(self.bar, textvariable=self.clock_var, font=f.mono(15), bg=av.PANEL, fg=av.INK).pack(side="right")

    # ----- drawing --------------------------------------------------------------------------

    def scene(self) -> av.Scene:
        return av.Scene(self.arena)

    def redraw_static(self) -> None:
        self.canvas.delete(STATIC)
        av.draw_static(self.static_painter, self.geometry, self.scene())
        self.canvas.tag_lower(STATIC)
        self.refresh_panel()

    def redraw_dynamic(self) -> None:
        self.canvas.delete(DYNAMIC)
        av.draw_dynamic(self.dynamic_painter, self.geometry, self.scene())
        self.canvas.tag_raise(DYNAMIC)

    def refresh_panel(self) -> None:
        for frame in (self.route_frame, self.obstacle_frame, self.captured_frame):
            for child in frame.winfo_children():
                child.destroy()
        for o in self.arena.obstacles:
            cx, cy = corners_to_cell(o.south_west)
            self._row(self.obstacle_frame, f"({cx}, {cy}) faces {o.direction.value[0]}", "",
                      chip=str(o.image_id), chip_colour=av.MUTED)

    # ----- handlers, wired in later tasks --------------------------------------------------

    def later(self) -> None:
        self.status_var.set("Coming in a later phase.")

    on_plan = on_open = on_save = on_play = on_step = on_reset = later


def run(arena_path: str | None, selftest: bool = False) -> int:
    root = tk.Tk()
    app = SimulatorApp(root, arena_path)
    if selftest:
        root.after(300, root.destroy)
    root.mainloop()
    return 0
```

The "est. of 6:00" label must read `config.TASK_1_TIME_LIMIT_S` formatted as `m:ss`, not a literal; write a module-level `def clock(seconds: float) -> str` returning `f"{int(seconds) // 60}:{int(seconds) % 60:02d}"` and use it for both the limit label and (later) the clock.

- [ ] **Step 5: run**

Run: `./.venv/bin/python -m pytest tests -q` → green.
Run: `./.venv/bin/python -m simulator --selftest` → exits 0 with no traceback. If Tk fails with XPC "Connection invalid"/`NSInternalInconsistencyException`, rerun with the sandbox disabled; if it still cannot open, report that and rely on the snapshot from Task 6.
Run: `./.venv/bin/python -m simulator --snapshot $TMPDIR/t7.png` and view it; unchanged from Task 6 is expected.

---

### Task 8: the window, phase 2 (plan, play, pause, step, reset, speed, scrubber)

**Files:**
- Modify: `algorithm/simulator/app.py`

**Interfaces:**
- Consumes: `routes.SOURCES`, `playback.Playback`, `av.Scene` fields.
- Produces: `SimulatorApp.route`, `.playback`, `.source` (selected `RouteSource`), `.speed_ms`, `.timer` (after handle or None), `on_plan`, `on_play` (toggles Play/Pause), `on_step`, `on_reset`, `on_speed(ms)`, `on_scrub(index)`, `tick()`.

- [ ] **Step 1: state and planning**

Add to `__init__`: `self.route = None`, `self.playback = None`, `self.source = SOURCES[0]`, `self.speed_ms = 20`, `self.timer = None`. Replace the `scene()` method:
```python
    def scene(self) -> av.Scene:
        if self.route is None or self.playback is None:
            return av.Scene(self.arena)
        current = self.playback.current
        return av.Scene(
            self.arena,
            colour_of={s.image_id: av.segment_colour(i) for i, s in enumerate(self.route.segments)},
            unreachable={u.image_id: u.reason.value for u in self.route.unreachable},
            captured=frozenset(i for i, _ in self.playback.captured),
            next_id=self.playback.next_id,
            pose=current.pose if current else None,
            trail=tuple(self.playback.trail),
            remaining=tuple(self.playback.remaining),
        )
```
`on_plan`:
```python
    def on_plan(self) -> None:
        self.stop_timer()
        self.plan_button.set_text("Planning...")
        self.status_var.set("")
        self.root.update_idletasks()
        try:
            self.route = self.source.plan(self.arena.world())
        except Exception as error:                      # a planner bug must not kill the demo
            self.route = None
            self.status_var.set(f"Planning failed: {error}")
        finally:
            self.plan_button.set_text("Plan route")
        self.playback = Playback(self.route) if self.route else None
        self.scrub.configure(to=max(0, (len(self.playback.frames) - 1) if self.playback else 0))
        self.redraw_static()
        self.redraw_dynamic()
```
Route section in `refresh_panel`: one `tk.Radiobutton` per source in `SOURCES` (variable `self.source_var`, command sets `self.source` and clears the route), then rows "Total length" `f"{route.total_cost:,} cm"` and "Planned in" `f"{route.plan_ms / 1000:.1f} s"` when a route exists. Obstacle rows use the segment colour as the chip when the obstacle is in `colour_of`, `av.FACE` when unreachable, else `av.MUTED`; the right-hand text is "captured" (colour `av.START_EDGE`), "next", the unreachable reason (colour `av.FACE`), or "".

- [ ] **Step 2: transport**

```python
    def on_play(self) -> None:
        if self.playback is None or self.playback.finished:
            return
        if self.timer is None:
            self.play_button.set_text("Pause")
            self.tick()
        else:
            self.stop_timer()

    def stop_timer(self) -> None:
        if self.timer is not None:
            self.root.after_cancel(self.timer)
            self.timer = None
        self.play_button.set_text("Play")

    def tick(self) -> None:
        self.timer = None
        if self.playback is None or self.playback.step() is None:
            self.stop_timer()
            return
        self.after_frame()
        self.timer = self.root.after(self.speed_ms, self.tick)

    def on_step(self) -> None:
        self.stop_timer()
        if self.playback and self.playback.step() is not None:
            self.after_frame()

    def on_reset(self) -> None:
        self.stop_timer()
        if self.playback:
            self.playback.reset()
            self.after_frame()

    def on_speed(self, ms: int) -> None:
        self.speed_ms = ms
        for pill, pill_ms in self.speed_pills:
            pill.configure(bg=av.INK if pill_ms == ms else av.PANEL, fg=av.PANEL if pill_ms == ms else av.MUTED)

    def on_scrub(self, value: str) -> None:
        if self.playback is None or self.scrubbing_programmatically:
            return
        self.stop_timer()
        self.playback.seek(int(float(value)))
        self.after_frame()

    def after_frame(self) -> None:
        """Everything that changes between frames. Static layers redraw only when a capture happens."""
        captured_now = len(self.playback.captured)
        if captured_now != self.captured_seen:
            self.captured_seen = captured_now
            self.redraw_static()
        self.redraw_dynamic()
        self.scrubbing_programmatically = True
        self.scrub.set(self.playback.index)
        self.scrubbing_programmatically = False
        self.refresh_readouts()
```
Bar widgets: speed pills as four `tk.Label`s (`0.5x`=40, `1x`=20, `2x`=10, `4x`=5 ms) in a frame, each bound to `on_speed`; `self.scrub = tk.Scale(self.bar, orient="horizontal", showvalue=0, from_=0, to=0, command=self.on_scrub, bg=av.PANEL, troughcolor=av.RULE, highlightthickness=0, sliderrelief="flat", length=260)`. Initialise `self.captured_seen = 0` and `self.scrubbing_programmatically = False`; `refresh_readouts()` is a no-op placeholder body `pass` in this task (Task 9 fills it). Bind the window close (`root.protocol("WM_DELETE_WINDOW", ...)`) to `stop_timer()` then `root.destroy()`. Speed 1x is selected on start. Keyboard: space toggles play, right arrow steps, `r` resets (bind on root).

- [ ] **Step 3: selftest**

`run()` with `selftest=True`: after 300 ms call `app.on_plan()`, then `app.on_speed(5)`, `app.on_play()`, and after a further 2000 ms `app.on_step()`, `app.on_reset()`, `app.on_scrub("50")`, then destroy. Any exception propagates and fails the run.

- [ ] **Step 4: verify**

Run: `./.venv/bin/python -m pytest tests -q` → green (nothing new; the pure modules are unchanged).
Run: `./.venv/bin/python -m simulator --selftest` → exit 0, no traceback.
Run: `./.venv/bin/python -m simulator --snapshot $TMPDIR/t8.png --frame 350` and view: the car is mid-route, trail coloured, remaining dashed.

---

### Task 9: the window, phase 3 (captured list, clock, obstacle states)

**Files:**
- Modify: `algorithm/simulator/app.py`

- [ ] **Step 1: readouts**

```python
    def refresh_readouts(self) -> None:
        if self.playback is None:
            self.clock_var.set(clock(0))
            self.count_var.set("")
            return
        self.clock_var.set(clock(self.playback.estimated_seconds))
        self.count_var.set(f"{len(self.playback.captured)} of {len(self.route.segments)}")
```
Captured section in `refresh_panel`: one row per `(image_id, seconds)` in `playback.captured`, left `f"Obstacle {image_id}"`, right `clock(seconds)`. Empty state text (muted, 11 px): "Plays as the robot arrives at each image." when a route exists but nothing is captured yet, and "Plan a route to begin." when there is no route. Obstacle rows: state text and colours per Task 8. The obstacle being captured right now gets a green ring on the canvas: add `capturing: int | None = None` to `Scene`, and in `arena_view.draw_dynamic`, when it is set, find that obstacle and draw `p.rect(*g.rect(sx - 3, sy - 3, side + 6, side + 6), outline=START_EDGE, width=2)` around it (sx, sy its south-west corner, side its clearance). `app.scene()` sets it to `current.captured_id if current and current.dwell else None`. Add one test to `test_arena_view.py` asserting the ring is drawn when `capturing=1` and absent otherwise.

- [ ] **Step 2: verify**

Tests green; `--selftest` exit 0; snapshot at `--frame` equal to a capture frame plus 3 shows the green ring.

---

### Task 10: the window, phase 4 (editing, open, save)

**Files:**
- Modify: `algorithm/simulator/app.py`

- [ ] **Step 1: canvas mouse bindings**

```python
        self.canvas.bind("<Button-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        for right in ("<Button-2>", "<Button-3>", "<Control-Button-1>"):
            self.canvas.bind(right, self.on_remove)
```
```python
    def cell_at(self, event) -> tuple[int, int]:
        x_cm, y_cm = self.geometry.to_arena(event.x, event.y)
        step = config.OBSTACLE_SIZE_CM
        return snap(x_cm, step) // step, snap(y_cm, step) // step

    def on_press(self, event) -> None:
        x_cm, y_cm = self.geometry.to_arena(event.x, event.y)
        hit = self.arena.at(x_cm, y_cm)
        self.drag = (hit.image_id, self.cell_at(event)) if hit else None
        self.dragged = False

    def on_drag(self, event) -> None:
        if self.drag is None:
            return
        image_id, origin = self.drag
        cell = self.cell_at(event)
        if cell != origin:
            self.dragged = True
            self.try_edit(lambda: self.arena.move(image_id, *cell))
            self.drag = (image_id, cell)

    def on_release(self, event) -> None:
        if self.drag is None:
            x_cm, y_cm = self.geometry.to_arena(event.x, event.y)
            if 0 <= x_cm < self.geometry.arena_cm and 0 <= y_cm < self.geometry.arena_cm:
                self.try_edit(lambda: self.arena.add(*self.cell_at(event)))
        elif not self.dragged:
            image_id, _ = self.drag
            self.try_edit(lambda: self.arena.cycle_face(image_id))
        self.drag = None

    def on_remove(self, event) -> None:
        x_cm, y_cm = self.geometry.to_arena(event.x, event.y)
        hit = self.arena.at(x_cm, y_cm)
        if hit:
            self.try_edit(lambda: self.arena.remove(hit.image_id))

    def try_edit(self, edit) -> None:
        try:
            new_arena = edit()
        except ArenaError as refused:
            self.status_var.set(f"Can't place there: {refused}.")
            return
        self.arena = new_arena
        self.status_var.set("")
        self.clear_route()

    def clear_route(self) -> None:
        self.stop_timer()
        self.route = self.playback = None
        self.captured_seen = 0
        self.scrub.configure(to=0)
        self.redraw_static()
        self.redraw_dynamic()
        self.refresh_readouts()
```

- [ ] **Step 2: open and save**

`on_open`: `tkinter.filedialog.askopenfilename(initialdir="testdata", filetypes=[("Arena JSON", "*.json")])`; if a path comes back, `self.arena = load(path)` inside a try that reports `KeyError/ValueError/OSError/AssertionError` as `status_var` "Couldn't open <name>: <error>", then `clear_route()`. `on_save`: `asksaveasfilename(defaultextension=".json", initialfile="arena.json", filetypes=...)`, `save(path, self.arena)`, status "Saved <name>". Initialise `self.drag = None` and `self.dragged = False` in `__init__`.

- [ ] **Step 3: verify**

Tests green; `--selftest` extended: after the Task 8 sequence, call `app.try_edit(lambda: app.arena.add(15, 15))`, `app.try_edit(lambda: app.arena.add(15, 15))` (must set the status line, not raise), `app.try_edit(lambda: app.arena.cycle_face(app.arena.obstacles[-1].image_id))`, `app.try_edit(lambda: app.arena.remove(app.arena.obstacles[-1].image_id))`, then `app.on_plan()` and destroy. Exit 0.

---

### Task 11: phase 5 polish, README, and the human gate

**Files:**
- Modify: `algorithm/README.md` (new "Simulator" section), `algorithm/simulator/SPEC.md` (status line and any drift), `algorithm/requirements.txt` comment
- Modify: `algorithm/simulator/app.py` only if a listed item is missing

- [ ] **Step 1: walk the spec once**

Check every line of SPEC "Visual design", "Playback", "Editing", "Open and save" against the code and fix drift in the code, not the spec, unless the spec is wrong (then fix the spec and say so in the report).

- [ ] **Step 2: README section**

Add to `algorithm/README.md` after "Smoke test":

```markdown
## Simulator

Checklist items B.1 and B.2 are demonstrated with it (B.3 once the shortest-time source lands).

    ./.venv/bin/python -m simulator                                   # opens with testdata/02
    ./.venv/bin/python -m simulator --arena .replay/<file>.json       # replay a real RPi request
    ./.venv/bin/python -m simulator --snapshot out.png --frame 350    # no window, just a PNG

Needs tkinter. macOS Homebrew Python: `brew install python-tk@3.11`. Windows python.org
installers include it. Debian/Ubuntu: `sudo apt install python3-tk`. Check with
`./.venv/bin/python -c "import tkinter; tkinter.Tk().destroy()"`.

Click an empty cell to add an obstacle, click an obstacle to turn its image face, drag to move,
right-click (or control-click) to remove. Plan route, then Play. Space plays and pauses, right
arrow steps, r resets. The clock is an estimate from `config.ROBOT_SPEED_CM_S` and
`config.CAPTURE_DWELL_S`, both placeholders until STM and CV measure them.

`--snapshot` needs Pillow (`pip install Pillow`); the window does not.
```

- [ ] **Step 3: verify everything**

Run: `./.venv/bin/python -m pytest tests -q` → green, no warnings.
Run: `./.venv/bin/python smoke.py | tail -1` → 4/4.
Run: `./.venv/bin/python -m simulator --selftest` → 0.
Run: `./.venv/bin/python -m simulator --snapshot $TMPDIR/final.png --arena testdata/03-unreachable.json` and view: obstacle 13 is drawn in the warning style with `NO_OBJECTIVES` under it.
Then STOP. The manual checklist in SPEC is for the repo owner at a keyboard; list in the report which items an agent could not verify.

---

### Task 12: smooth arcs analytically in playback

Added 2026-09-03 after Task 6's snapshot: turn arcs drawn through the planner's integer rear-point
cells stair-step by up to 1.65 cm per frame and look hairy. The rear point actually follows a
circle of known radius between two known cells, so playback can place every arc frame on the true
circle and give it the exact swept heading. Frame count, distance bookkeeping and the end pose are
unchanged; only the positions and headings of arc frames move.

**Files:**
- Modify: `algorithm/simulator/playback.py` (the turn branch of frame building only)
- Test: `algorithm/tests/test_playback.py` (add two tests), `algorithm/simulator/SPEC.md` (one sentence in "Playback")

**Interfaces:** unchanged. `Frame.pose` for arc frames now lies on the analytic arc.

- [ ] **Step 1: failing tests**

Append to `tests/test_playback.py`:

```python
def _turns(playback):
    """(start_deg, end_deg, frames) for every turn in the route, in order."""
    from pathfinding.search.instructions import Turn
    out = []
    i = 0
    for seg_index, segment in enumerate(playback.route.segments):
        for move in segment.moves:
            n = len(move.vectors)
            if isinstance(move, Turn):
                out.append(playback.frames[i:i + n])
            i += n
        i += CAPTURE_DWELL_FRAMES
    return out


def test_arc_frames_lie_on_a_circle_of_the_turn_radius():
    import math
    p = Playback(route_for("02-four-obstacles.json"))
    lead = p.route.robot.south_length - config.TURN_PIVOT_OFFSET_CM // p.route.cell_size
    for frames in _turns(p):
        # rear point of every arc frame (frame pose minus lead along heading)
        rears = []
        for f in frames[:-1]:
            t = math.radians(f.pose.heading_deg)
            rears.append((f.pose.x - lead * math.sin(t), f.pose.y - lead * math.cos(t)))
        (x0, y0), (x1, y1) = rears[0], rears[-1]
        r = max(abs(x1 - x0), abs(y1 - y0))
        assert 30 <= r <= 45
        # the centre is offset from the first rear point perpendicular to the initial heading
        h0 = frames[0].pose.heading_deg
        first_heading_is_vertical = round(h0) % 180 in (0, 90) and abs(math.cos(math.radians(round(h0)))) > 0.5
        cx, cy = (x0 + (x1 - x0), y0) if first_heading_is_vertical else (x0, y0 + (y1 - y0))
        for rx, ry in rears:
            assert math.isclose(math.hypot(rx - cx, ry - cy), r, abs_tol=0.6), (cx, cy, r, rx, ry)


def test_arc_frames_step_evenly():
    import math
    p = Playback(route_for("02-four-obstacles.json"))
    for frames in _turns(p):
        steps = [math.hypot(b.pose.x - a.pose.x, b.pose.y - a.pose.y) for a, b in zip(frames, frames[1:])]
        assert max(steps) <= 1.25 and min(steps) >= 0.5, steps
```

(`test_playback_is_continuous`'s 2.5 cm bound still applies; keep it.)

- [ ] **Step 2: run, expect the circle test to fail on the lattice positions**

- [ ] **Step 3: implement, in the `Turn` branch of `Playback.__init__`**

Keep `start_deg`, `end_deg`, `delta`, `lead`, the per-frame distance step and the final end-pose
frame exactly as they are. Replace only how the `m` arc frames get their positions:

```python
                *arc, end = move.vectors
                m = len(arc)
                rear_start = (arc[0].x, arc[0].y)
                rear_end = (arc[-1].x, arc[-1].y)
                dx, dy = rear_end[0] - rear_start[0], rear_end[1] - rear_start[1]
                # The rear point rides a quarter circle. Its centre sits beside the first rear cell,
                # perpendicular to the initial heading: along x when starting north/south, along y
                # when starting east/west.
                if start_deg % 180 == 0:
                    cx, cy = rear_start[0] + dx, rear_start[1]
                else:
                    cx, cy = rear_start[0], rear_start[1] + dy
                phi0 = math.atan2(rear_start[1] - cy, rear_start[0] - cx)
                phi1 = math.atan2(rear_end[1] - cy, rear_end[0] - cx)
                sweep = ((phi1 - phi0 + math.pi) % (2 * math.pi)) - math.pi      # signed, +-pi/2
                radius = math.hypot(rear_start[0] - cx, rear_start[1] - cy)
                for k in range(m):
                    t = (k + 1) / (m + 1)
                    phi = phi0 + sweep * t
                    heading = (start_deg + delta * t) % 360
                    ux, uy = unit(heading)
                    rx, ry = cx + radius * math.cos(phi), cy + radius * math.sin(phi)
                    pose = Pose(rx + lead * ux, ry + lead * uy, heading)
                    ... (append the frame exactly as before, with the same distance step)
                then the end-pose frame as before.
```

Note `t = (k + 1) / (m + 1)` so the `m` arc frames plus the end frame divide the sweep evenly and
the last arc frame is not a duplicate of the end pose. Update the SPEC "Playback" bullet: "arc
cells reconstruct the centre" becomes "arc frames are placed on the true circle through the arc's
end cells, with the heading equal to the angle swept, so the car glides through turns".

- [ ] **Step 4: run the suite and smoke; then `./.venv/bin/python -m simulator --snapshot $TMPDIR/t12.png` and look at a turn at 4x** (crop with Pillow and Read it). The arcs must be smooth curves; straight legs unchanged.
