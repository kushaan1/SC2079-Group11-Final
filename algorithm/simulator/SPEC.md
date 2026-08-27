# Simulator — specification and implementation plan

> **Status:** approved design, not yet implemented.
> **Written:** 2026-08-27. **Owner:** algorithms.
> **Read this first if you are taking over the simulator work.** It is both the spec and the
> implementation plan; work the phases in §7 in order.

---

## 1. Why this exists

Three graded checklist items — **B.1, B.2, B.3**, the entire algorithms share of the 20% functionality
checklist — are demonstrated through a simulator. Their exact wording, from
`docs/MDP assessment and system checklist.pdf` pp. 7–8:

| Item | Requirement |
|---|---|
| **B.1 Robot Movement Area Simulator** | *"display the robot's 2.0m x 2.0m movement area, the start zone, the locations of the obstacles and the positions of the images. The simulator should be able to show the position of the robot as it moves forward/backward and turns."* |
| **B.2 Hamiltonian Path Computation Simulator** | *"demonstrate the implementation of an algorithm that guides the robot to traverse the 2.0m x 2.0m movement area, starting from the start zone and visiting each image position once. The recognition of the 5 images should be completed within the time limit... the number of images recognized within the time limit is accepted."* |
| **B.3 Shortest-time Hamiltonian Path Computation** | *"demonstrate the robot following a shortest-time Hamiltonian path to recognize the 5 images."* |

All three additionally require: *"This should be shown on a simulator displaying a **grid map** of the
movement area of the robot."*

Two further requirements come from `docs/algarithms_briefing_25S2.pdf` p. 40:

- *"Display the robot's positions in real time (**a square shape or a marker is ok**) in a **time
  stepped** manner"* — animation is required; crude rendering is explicitly acceptable.
- *"**Report images recognized as it is done**"* — announce each image as the robot reaches it, not
  only at the end.

**Without a simulator these three items score zero regardless of planner quality.** A correct planner
is not a demonstrable one, and demonstration is the assessment mechanism.

### This is not the Android arena map

The tablet has its own, separately graded 2D arena display (checklist **C.5–C.9**, owned by the
Android subsystem) which shows the **real** robot over Bluetooth during a run. This simulator runs
**standalone on the algorithms laptop with no robot, no RPi and no tablet**. Do not merge the two or
assume one substitutes for the other.

---

## 2. Scope

### In scope

- A tkinter desktop window showing a grid map of the 200 × 200 cm arena.
- Start zone, obstacles, and each obstacle's image face, drawn distinctly.
- Click-to-place arena editing: add, remove, and set the image face of obstacles.
- Animated time-stepped playback of a planned route, showing straights and turns.
- Play / pause / step / reset / speed controls.
- A panel that fills in with each image ID as the robot reaches it.
- An estimated real-robot elapsed time against the Task 1 6-minute limit.
- Obstacles the planner could not reach, drawn distinctly with the reason.
- A pluggable route source, so the visiting-order strategy can be swapped and compared.

### Explicitly out of scope

- **The Held–Karp ordering layer itself.** B.3 requires a shortest-time route; the current planner is
  greedy nearest-first. This spec defines the *interface* the optimiser will plug into (§5.4) and
  nothing more. Building the optimiser is separate work, tracked as a follow-up. **B.1 and B.2 are
  satisfiable on this spec alone; B.3 is not, and this document does not claim otherwise.**
- Simulating sensors, the camera, image recognition, or motor error. The simulator replays the
  planner's intended path. It is not a physics model.
- Task 2. That is a reactive state machine owned by STM/RPi and shares no planning code.
- Any network communication. The simulator imports the planner in-process (§5.1).
- Live display of the real robot. That is the tablet's job.

---

## 3. Architecture

```
algorithm/simulator/
├── __init__.py
├── __main__.py       entry point, so `python -m simulator` works
├── SPEC.md           this file
├── geometry.py       arena-cm <-> canvas-px conversion. Pure functions, no tkinter
├── arena_view.py     all drawing. Given state, paints a canvas. Holds no application state
├── playback.py       the animation timeline. Pure logic, no tkinter
├── routes.py         RouteSource implementations: how a route gets planned
└── app.py            the window, widgets, event handling. Wires the above together
```

Design rule: **only `app.py` and `arena_view.py` import tkinter.** `geometry.py`, `playback.py` and
`routes.py` are plain Python and unit-testable without a display. This is what makes the timing and
coordinate logic — where the bugs will be — testable at all.

Dependency direction, no cycles:

```
app.py ──> arena_view.py ──> geometry.py
   │                              ^
   ├──> playback.py ──────────────┘
   └──> routes.py ──> pathfinding.* (the existing planner)
```

---

## 4. The single most likely bug: the Y axis is flipped

**The arena's origin is bottom-left with y increasing upward. A tkinter canvas's origin is top-left
with y increasing downward.** Every coordinate must be flipped exactly once.

Get this wrong and the whole arena renders upside down — obstacles in mirrored positions, "north"
pointing down. It is the single defect most likely to consume an afternoon.

Mitigation: **all conversion lives in `geometry.py` and nowhere else.** No file may compute a pixel
coordinate inline. `geometry.py` has unit tests asserting the flip explicitly (§6.1).

---

## 5. Module specifications

### 5.1 `routes.py` — where a route comes from

The simulator calls the planner **directly, in-process**. No HTTP, no server to start, nothing to
misconfigure in front of a supervisor. The planner speaks plain Python objects and has no knowledge
of the RPi, so this is a supported use, not a workaround.

```python
@dataclass(frozen=True)
class Route:
    """A planned route, plus what it could not reach."""
    segments: list[Segment]                    # from pathfinding.search.search
    unreachable: list[UnreachableObstacle]     # from pathfinding.report
    source_name: str                           # the RouteSource.name that produced it
    plan_ms: float                             # wall-clock planning time, shown in the UI

    @property
    def total_cost(self) -> int:               # sum of segment costs; the number B.3 compares on
        ...


class RouteSource(Protocol):
    name: str
    def plan(self, world: World) -> Route: ...


class GreedyRouteSource:
    """The planner as it exists today: generate_objectives() then search()."""
    name = "Greedy (nearest-first)"
```

`GreedyRouteSource.plan()` must be a thin wrapper — call `generate_objectives(world)` then
`search(world, objectives)`, time it, wrap in `Route`. **It must not reimplement or alter any
planning logic.** If simulator behaviour and `smoke.py` behaviour ever diverge, that is a bug here.

A future `OptimalRouteSource` (Held–Karp) implements the same Protocol and needs no simulator change.
The UI lists every registered source (§5.5), which is what makes a side-by-side B.3 demo possible.

### 5.2 `geometry.py` — coordinates

Pure functions. No tkinter import. No state.

```python
SCALE_PX_PER_CM = 3          # 200 cm -> 600 px canvas; fits a laptop screen
ARENA_PX = config.ARENA_SIZE_CM * SCALE_PX_PER_CM

def to_canvas(x_cm: float, y_cm: float) -> tuple[float, float]:
    """Arena centimetres (origin bottom-left, y up) -> canvas pixels (origin top-left, y down)."""
    return x_cm * SCALE_PX_PER_CM, (config.ARENA_SIZE_CM - y_cm) * SCALE_PX_PER_CM

def to_arena(px: float, py: float) -> tuple[int, int]:
    """Canvas pixels -> arena centimetres. Inverse of to_canvas, for mouse clicks."""

def cell_rect(x_cm: int, y_cm: int, size_cm: int) -> tuple[float, float, float, float]:
    """The canvas bounding box (x0, y0, x1, y1) of a square of `size_cm` with its
    SOUTH-WEST corner at (x_cm, y_cm). Note y0/y1 are swapped relative to naive
    intuition because of the flip."""

def snap(value_cm: float, step_cm: int) -> int:
    """Round down to the nearest multiple of step_cm. Used to snap clicks to the obstacle grid."""
```

`SCALE_PX_PER_CM` and grid step live here, **not** in `config.py`. `config.py` is documented as
holding numbers *the planner* uses; display scale is not a physical property of the robot and putting
it there would dilute that rule. Physical constants the simulator needs (`ROBOT_SPEED_CM_S`) do go in
`config.py` — see §5.6.

### 5.3 `playback.py` — the animation timeline

Pure logic, no tkinter, no drawing. This is the module most worth testing.

The planner returns one `Segment` per obstacle, each with `.vectors: list[Vector]` — the cell-by-cell
path. Flatten them into a single timeline, remembering where each segment ends so the "image
recognised" event can fire there.

```python
@dataclass(frozen=True)
class Frame:
    vector: Vector                  # robot CENTRE position and heading at this step
    segment_index: int              # which segment (0-based) this frame belongs to
    captured_image_id: int | None   # image_id if this is a segment's LAST frame, else None


class Playback:
    def __init__(self, route: Route) -> None: ...

    @property
    def frames(self) -> list[Frame]: ...
    @property
    def index(self) -> int: ...
    @property
    def current(self) -> Frame | None: ...       # None when frames is empty
    @property
    def finished(self) -> bool: ...
    @property
    def recognised(self) -> list[int]: ...       # image_ids captured up to and including index

    def step(self) -> Frame | None: ...          # advance one frame; None when already finished
    def reset(self) -> None: ...
    def seek(self, index: int) -> None: ...      # clamped to [0, len(frames) - 1]

    @property
    def distance_cm(self) -> int: ...            # == index; see the note below
    def estimated_seconds(self) -> float: ...    # distance_cm / config.ROBOT_SPEED_CM_S
```

**Why `distance_cm == index`.** Each vector is one 1 cm grid cell, so frame count is centimetres
travelled. Verified against the 4-obstacle reference arena on 2026-08-27: 1024 vectors against a
planner cost of 1083, a ratio of **1.06**. Turn arcs are the 6% discrepancy — the cost model charges
`radius × π/2` for an arc while the midpoint-circle generator emits marginally fewer cells. **The
timer must be labelled an estimate**; do not present it as exact.

Edge cases that must be handled and tested:

- An empty route (every obstacle unreachable) — `frames == []`, `current is None`, `finished` is
  `True`, `step()` returns `None`. The UI must not crash; it shows the arena statically.
- A single-frame route.
- `step()` past the end is a no-op returning `None`, never an exception or an index error.
- `recognised` after `reset()` is empty again.

### 5.4 `arena_view.py` — drawing

One class holding a canvas reference. **All state is passed in as arguments** — it never owns the
world, the route, or the playback position. That keeps every drawing decision reproducible from its
inputs.

```python
class ArenaView:
    def __init__(self, canvas: tkinter.Canvas) -> None: ...

    def draw_grid(self) -> None:
        """Arena border plus grid lines every 10 cm. A 20x20 grid, which is what satisfies the
        checklist's 'grid map' requirement. Heavier line every 50 cm for readability."""

    def draw_start_zone(self) -> None:
        """The 40 x 40 cm start zone at the origin, per AGENTS.md 3.1. Tinted fill plus a label."""

    def draw_obstacle(self, obstacle: Obstacle, *, unreachable_reason: str | None = None) -> None:
        """A 10 x 10 cm filled square, the image_id centred on it, and a THICK COLOURED EDGE on the
        face carrying the image (obstacle.direction). The image face is a checklist requirement in
        its own right - B.1 asks for 'the positions of the images', not just the obstacles.

        When unreachable_reason is given, draw the square in a warning style and append the reason.
        This makes a skipped obstacle visible rather than absent, which is the same honesty the
        `unreachable` API field exists for."""

    def draw_keep_out(self, world: World) -> None:
        """OPTIONAL overlay, default off: shade every cell where world.grid is False, i.e. where the
        robot's centre may not go. Not required by any checklist item; included because it makes the
        oversized-clearance problem (README limitation 1) visible instead of theoretical."""

    def draw_robot(self, vector: Vector) -> None:
        """The robot at `vector`, which is its CENTRE - not a corner. A footprint square of
        config.ROBOT_FOOTPRINT_CM plus a heading indicator (a line or triangle from the centre
        toward `vector.direction`) so that TURNS ARE VISIBLE. B.1 requires showing the robot 'as it
        moves forward/backward and turns'; a plain square rotating through 90 degrees looks
        identical at every heading, so the heading indicator is a requirement, not decoration."""

    def draw_trail(self, trail: list[tuple[Vector, int]]) -> None:
        """The path already driven, as a thin line. Each entry is (vector, segment_index);
        colour-code by segment_index so the visiting ORDER is legible at a glance - that is what
        makes B.2's 'visiting each image position once' visually checkable rather than asserted.

        Takes plain (Vector, int) tuples rather than playback.Frame ON PURPOSE: it keeps
        arena_view free of any import from playback, so the dependency graph in section 3 stays
        acyclic and arena_view depends only on geometry and the planner's primitives. app.py does
        the slicing and unpacking."""

    def clear(self) -> None: ...
```

Rendering order matters — later draws paint over earlier: grid → start zone → keep-out (if on) →
trail → obstacles → robot. The robot must be on top; obstacles must be above the trail so a path
passing behind one still reads correctly.

### 5.5 `app.py` — window, widgets, events

Owns all mutable application state: the obstacle list, the current `World`, the current `Route`, the
`Playback`, and the tkinter timer handle.

**Layout** (matching the mockup approved during design):

```
┌──────────────────────────────────────┬─────────────────────┐
│                                      │  Route source:      │
│                                      │   (•) Greedy        │
│         600 x 600 canvas             │                     │
│         the arena grid map            │  Obstacles          │
│                                      │   11  (50, 90)  S   │
│                                      │   12  (120,60)  W   │
│                                      │                     │
│                                      │  Recognised         │
│                                      │   ✓ 12              │
│                                      │   ✓ 11              │
│                                      │                     │
│                                      │  ⚠ 13 NO_OBJECTIVES │
├──────────────────────────────────────┴─────────────────────┤
│ [Plan] [Play/Pause] [Step] [Reset]   speed [0.5x 1x 2x 4x] │
│ est. 0:34 / 6:00     recognised 2/4     plan took 2470 ms  │
└────────────────────────────────────────────────────────────┘
```

**Mouse interaction on the canvas:**

| Action | Effect |
|---|---|
| Left-click empty space | Add a 10 cm obstacle, snapped to the 10 cm grid, image face defaulting to SOUTH, `image_id` = lowest unused value from `config.IMAGE_ID_MIN` |
| Left-click an existing obstacle | Cycle its image face NORTH → EAST → SOUTH → WEST |
| Right-click an existing obstacle | Remove it |

Placement must be **rejected with a visible message, never silently**, when the new obstacle would:
overlap an existing obstacle; lie outside the arena; or overlap the 40 × 40 cm start zone. Reuse
`config.IMAGE_ID_MAX` as the ceiling — refuse to add a 31st obstacle rather than emit an illegal ID.

**Buttons:**

- **Plan** — build a fresh `World` from the current obstacles, call the selected `RouteSource`, build
  a `Playback`, redraw. Planning takes ~2.5 s for 4 obstacles and **blocks the UI**; see §8.
- **Play / Pause** — start or stop the timer loop.
- **Step** — advance exactly one frame. Essential for demonstrating a single turn to a supervisor.
- **Reset** — `Playback.reset()` and redraw at frame 0.
- **Speed** — sets milliseconds per frame: `0.5x → 40ms`, `1x → 20ms`, `2x → 10ms`, `4x → 5ms`.

**The animation loop uses `root.after(delay_ms, tick)` — never a thread.** Tkinter is not
thread-safe; touching widgets from another thread produces intermittent crashes that are very hard to
diagnose. Store the handle returned by `after()` so Pause can `after_cancel()` it, and cancel it on
window close.

At 1x the reference 4-obstacle arena animates in about 20 seconds (1024 frames × 20 ms), which is a
sensible pace for a supervisor to watch.

### 5.6 Change to `config.py`

One constant, in the existing provenance format:

```python
# How fast the robot actually drives, in centimetres per second, at competition speed.
# Used ONLY to convert a planned path length into an estimated real-world duration for the
# simulator's clock (checklist B.2 is scored on images recognised within the time limit).
# The planner itself does not use this: it costs paths in centimetres, not seconds.
# SOURCE: STM | placeholder | NOT MEASURED. 30 is a guess. Ask the STM owner for the actual figure
#   at competition speed and update this together with TURN_RADIUS_CM, which must be measured at the
#   same speed - turning radius grows with speed, so the two numbers are only valid as a pair.
ROBOT_SPEED_CM_S = 30
```

Also add, in the same section:

```python
# The Task 1 timeout, in seconds. The simulator shows elapsed estimate against this.
# SOURCE: RULES | measured | 6 minutes for Task 1, 3 minutes for Task 2. MDP briefing(1).pdf.
TASK_1_TIME_LIMIT_S = 360
```

At the placeholder 30 cm/s the reference 4-obstacle arena estimates **34 s against the 360 s budget**
— comfortable, and consistent with the measured 2.2 s planning latency being irrelevant.

---

## 6. Testing

### 6.1 Unit tests — `algorithm/tests/test_simulator.py`

Runnable as `python -m pytest tests/ -v` from `algorithm/`. `pytest` is already in
`requirements.txt`. A `conftest.py` putting `algorithm/` on `sys.path` is needed if not already
present.

**`geometry.py`** — the flip is the whole point, so assert it explicitly:

- `to_canvas(0, 0) == (0, 600)` — arena origin is bottom-left, canvas bottom-left is y=600.
- `to_canvas(0, 200) == (0, 0)` — arena top-left maps to canvas origin.
- `to_canvas(200, 0) == (600, 600)`.
- `to_arena(to_canvas(x, y)) == (x, y)` for a spread of integer inputs — round-trip.
- `cell_rect` produces a box whose height equals `size_cm * SCALE` and whose top edge is *above* its
  bottom edge in canvas terms.
- `snap(97, 10) == 90`, `snap(90, 10) == 90`, `snap(0, 10) == 0`.

**`playback.py`** — behaviour, on a real route from a real `World`:

- Total frames equals the sum of `len(segment.vectors)`.
- Exactly one frame per segment has `captures` set, and it is that segment's last frame.
- `recognised` grows in visit order and matches `[s.image_id for s in route.segments]` at the end.
- `reset()` returns `index` to 0 and empties `recognised`.
- `step()` at the end returns `None` and does not raise.
- Empty route: `frames == []`, `current is None`, `finished is True`, `step() is None`.
- `seek()` clamps rather than raising.
- `distance_cm == index`.

**`routes.py`**:

- `GreedyRouteSource.plan(world)` returns segments and unreachable **identical** to calling
  `generate_objectives()` + `search()` directly on the same world — compare `image_id`, `cost` and
  full instruction lists. This is the test that stops the simulator quietly diverging from the
  planner.

**Not unit-tested:** `app.py` and `arena_view.py`. Driving a tkinter event loop in CI is more
trouble than it is worth here, and the drawing is verified by eye against §6.2.

### 6.2 Manual verification checklist

Run through this before claiming a phase complete. It doubles as the demo script for §9.

1. Window opens; arena is square with visible grid lines every 10 cm.
2. Start zone is at the **bottom-left**. *(If it is top-left, the Y flip is wrong — see §4.)*
3. Click four obstacles; each shows an ID and a marked image face.
4. Click an obstacle repeatedly; the marked face cycles N → E → S → W.
5. Right-click removes an obstacle.
6. Try to place an obstacle overlapping another — refused, with a message.
7. Press Plan; a route appears.
8. Press Play; the robot moves smoothly and **turns are visibly arcs, not teleports**.
9. The heading indicator rotates through turns.
10. Each image ID appears in the Recognised panel **as the robot reaches it**, not all at the end.
11. The timer counts up and is labelled an estimate.
12. Step advances exactly one frame.
13. Reset returns to the start and clears Recognised.
14. Build an arena with an obstacle hard against a wall it faces; Plan; it is drawn as unreachable
     with `NO_OBJECTIVES`. *(This is correct behaviour, not a bug.)*
15. Plan with zero obstacles — no crash.

---

## 7. Implementation plan

Five phases. **Each ends in something demonstrable**, so work can be handed over or paused between
them, and so partial progress still earns something. Do them in order — later phases assume earlier
ones.

### Phase 0 — confirm a window opens

Before anything else, on the machine that will run the demo:

```sh
./.venv/bin/python -c "import tkinter; r=tkinter.Tk(); tkinter.Label(r, text='it works').pack(); r.mainloop()"
```

A window must appear. `import tkinter` succeeding is **not** sufficient evidence — a process without
window-server access imports fine and then dies with an `NSInternalInconsistencyException` on
`Tk()`. This bit during spec writing, from an agent shell with no GUI session.

Consequence for whoever implements this: **an automated agent cannot verify any of the visual
behaviour in §6.2.** Every manual check must be run by a human at the keyboard. Write the code so
the non-visual parts (`geometry`, `playback`, `routes`) carry real unit tests, because those are the
only parts that can be verified without eyes.

### Phase 1 — static render

`geometry.py`, `arena_view.py`, a minimal `app.py` that opens a window and draws a hardcoded arena
(reuse `testdata/02-four-obstacles.json`'s layout). No planning, no animation, no clicking.

Deliverable: a window showing the grid, start zone, four obstacles with image faces, and the robot
parked at the start pose.
Tests: all of `geometry.py`'s.
Gate: manual checks 1, 2, and a visual match against the layout in `testdata/`.

**Do not proceed until check 2 passes.** Everything downstream inherits the coordinate transform.

### Phase 2 — planning and playback

`routes.py`, `playback.py`. Add Plan / Play / Pause / Step / Reset / speed. Still a hardcoded arena.

Deliverable: press Plan then Play, watch the robot drive the route with visible arcs.
Tests: all of `playback.py`'s and `routes.py`'s.
Gate: manual checks 7, 8, 9, 12, 13.

**This phase alone satisfies B.1.**

### Phase 3 — recognition reporting and the clock

The Recognised panel, the estimated-time display, the `config.py` additions from §5.6.

Deliverable: image IDs appear as they are reached; the clock shows an estimate against 6:00.
Gate: manual checks 10, 11.

**This phase completes B.2.**

### Phase 4 — arena editing

Click-to-place, face cycling, removal, and validation with visible rejection messages.

Deliverable: build any arena live, then plan it.
Gate: manual checks 3, 4, 5, 6, 15.

This is what makes the demo robust to a supervisor asking for a different layout.

### Phase 5 — unreachable rendering and route switching

Unreachable obstacles drawn with their reason. The route-source selector. The optional keep-out
overlay.

Deliverable: skipped obstacles are visible and explained; route sources can be switched.
Gate: manual check 14.

**B.3 remains unsatisfied until an optimising `RouteSource` exists** — that is separate work (§2).
Phase 5 is what makes plugging it in a one-file change.

### Ordering of value against the deadline

If time runs short, **Phases 1–3 earn B.1 and B.2** and are the priority. Phase 4 protects the demo.
Phase 5 is presentation and honesty. Never skip Phase 1's gate to save time.

---

## 8. Known risks

| Risk | Mitigation |
|---|---|
| **Y-axis flip** renders everything upside down | All conversion isolated in `geometry.py`, asserted by unit test, and gated at the end of Phase 1 (§4) |
| **Planning blocks the UI for ~2.5 s.** The window will look frozen while Plan runs | Accepted, not fixed. Disable the button and show "Planning…" so it reads as busy rather than hung. **Do not move planning to a thread** — tkinter is not thread-safe and the cure is worse than the symptom. If it ever becomes intolerable, the fix is a faster planner (wire up the A\* heuristic), not concurrency |
| A supervisor asks for **obstacles at the legal 30 cm spacing**, and they come back unreachable | Real limitation, documented in `README.md` limitation 1. Phase 5's rendering at least makes it legible and explainable rather than looking like a crash. Say it out loud before demoing |
| **Turns look like teleports** and B.1's "and turns" is not convincingly shown | The heading indicator in `draw_robot`, plus the arc cells already present in `segment.vectors`. Manual checks 8 and 9 exist to catch this |
| `ROBOT_SPEED_CM_S` is a **guess**, so the clock is fiction | Labelled an estimate in the UI and `placeholder` in config. Update after STM measures |
| Tkinter missing from a Python build | **This fired.** Homebrew's `python@3.11` ships without `_tkinter`, so `import tkinter` failed. Resolved on 2026-08-27 with `brew install python-tk@3.11` — Tk 8.6, confirmed importable from both `python3.11` and `algorithm/.venv`. It is a system package, **not** a pip install, so `requirements.txt` does not and cannot cover it. Any new machine needs the brew step; note it in `README.md` when Phase 1 lands. macOS system `/usr/bin/python3` has tkinter but is 3.9 and cannot run the planner (`match`), so it is not a fallback |

---

## 9. Demo script for the checklist sign-off

What to do in front of the supervisor, in order. Roughly three minutes.

1. **"This is the 2m by 2m arena on a 10cm grid, with the start zone bottom-left."** — B.1's map.
2. **Place five obstacles by clicking**, setting a different image face on each. *(B.2 and B.3 both
   say "the 5 images", so five is the specified demo arena even though competition day is 4–8.)*
3. **"Each obstacle shows its image ID, and the thick edge is the face the image is on."** — B.1's
   "positions of the images".
4. **Press Plan.** — "It computed a route visiting all five in 2.5 seconds."
5. **Press Play.** — "The robot square is the planning footprint; the pointer is its heading. Watch
   it reverse away from an obstacle and swing through a turn." — B.1's "forward/backward and turns".
6. **Point at the Recognised panel filling in.** — the deck's "report images recognized as it is
   done", and B.2's "visiting each image position once".
7. **Point at the clock.** — "Estimated 34 seconds against the 6-minute limit." — B.2's time limit.
8. **Press Reset, then Step a few times through a turn.** — proves it is genuinely time-stepped
   rather than an animation of a precomputed picture.
9. **For B.3**, switch the route source and compare total costs. *(Requires the optimiser; until then
   B.3 cannot honestly be claimed.)*

---

## 10. References

- `docs/MDP assessment and system checklist.pdf` pp. 7–8 — B.1/B.2/B.3, the graded wording.
- `docs/algarithms_briefing_25S2.pdf` p. 40 — time-stepped display, report images as recognised.
- `docs/MDP briefing(1).pdf` — Task 1's 6-minute limit, 4–8 obstacles, image IDs 11–40.
- `AGENTS.md` §3.1 — robot footprint, start zone. §7.9 — simulator requirements. §9.2 — repo rules.
- `algorithm/PROVENANCE.md` — planner lineage and design decisions.
- `algorithm/README.md` — known limitations, especially limitation 1 (clearance) and 4 (ordering).
- `algorithm/testdata/` — ready-made arenas; Phase 1 reuses `02-four-obstacles.json`'s layout.
