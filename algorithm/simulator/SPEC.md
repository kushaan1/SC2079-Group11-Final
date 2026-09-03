# Simulator spec

Status: implemented 2026-09-03 (plan tasks 1-12), shortest-time source added 2026-09-04; the
manual checklist below is still to be run by a human at the keyboard. Owner: algorithms.
Replaces the 2026-08-27 draft.

## Why

Checklist items B.1, B.2 and B.3 are the whole algorithms share of the 20% functionality
checklist, and every one of them is graded on a simulator:

| Item | Requirement (verbatim, `docs/MDP assessment and system checklist.pdf` pp. 7-8) |
|---|---|
| B.1 | "display the robot's 2.0m x 2.0m movement area, the start zone, the locations of the obstacles and the positions of the images. The simulator should be able to show the position of the robot as it moves forward/backward and turns." |
| B.2 | "demonstrate the implementation of an algorithm that guides the robot to traverse the 2.0m x 2.0m movement area, starting from the start zone and visiting each image position once. The recognition of the 5 images should be completed within the time limit." |
| B.3 | "demonstrate the robot following a shortest-time Hamiltonian path to recognize the 5 images." |

All three add: "This should be shown on a simulator displaying a grid map of the movement area."
The algorithms deck (p. 40) adds: robot position "in real time (a square shape or a marker is ok)
in a time stepped manner", and "report images recognized as it is done".

Without a simulator these score zero. This spec covers all three. B.1 and B.2 are the greedy
source; B.3 is the shortest-time source (`pathfinding/search/tour.py`, separate work) shown
through the same selector, so the two routes over one arena can be compared side by side in
front of the supervisor.

## Scope

In: a tkinter window; grid map of the arena; start zone; obstacles with the image face marked;
click-to-place editing; open/save arenas in the exact JSON the RPi sends; animated time-stepped
playback with play, pause, step, reset, speed; captured list filling in as the robot arrives;
estimated clock against the 6-minute limit; unreachable obstacles drawn with their reason; a
route-source selector carrying both the greedy planner and the shortest-time optimiser.

Out: the optimiser itself (it lives in `pathfinding/`; the simulator only calls it); sensors,
camera, motor error; Task 2; any network; live display of the real robot (that is the tablet's
job, checklist C.5 to C.10).

## Runs anywhere

The demo may happen on any teammate's laptop. Consequences:

- Python 3.11+ with tkinter. macOS Homebrew Python needs `brew install python-tk@3.11`;
  Windows python.org installers include it; Debian/Ubuntu need `python3-tk`. `README.md` says so.
- No fonts are shipped. `fonts.py` picks the first installed family from a candidate list
  (UI: Avenir Next, Helvetica Neue, Segoe UI, DejaVu Sans, Helvetica; numbers: Menlo, Consolas,
  DejaVu Sans Mono, Courier) using `tkinter.font.families()`.
- The arena canvas is sized from the screen: `arena_px = clamp(screen_height - 220, 480, 720)`,
  so scale (px per cm) is a runtime value passed to geometry, never a module constant.
- Entry point is `python -m simulator` from `algorithm/`, the same working directory the
  service uses, so `import config` and `from pathfinding...` resolve.

## Architecture

```
algorithm/simulator/
  __init__.py
  __main__.py     python -m simulator [--arena FILE] [--snapshot OUT.png --frame N]
  geometry.py     cm <-> px, y-flip, snapping, cell <-> corners, car outline. Pure
  arena.py        Arena (robot + obstacles), edit rules, load/save request JSON. Pure
  routes.py       RouteSource protocol + Greedy and Optimal RouteSource. Pure
  playback.py     frames, dwell, captured list, clock. Pure
  arena_view.py   Scene + Palette, and draw_static/draw_dynamic against a Painter. Pure
  painters.py     Painter protocol; TkPainter (tk.Canvas) and PilPainter (PNG)
  snapshot.py     headless render of an arena to PNG via PilPainter. Pure
  fonts.py        font family fallback. Only place that queries tk fonts
  app.py          the window, widgets, event loop. Owns all mutable state
```

Only `app.py`, `fonts.py` and `painters.TkPainter` import tkinter. Everything else runs
headless and is unit-tested. `arena_view` draws through a `Painter` protocol (rect, line,
polygon, oval, text) so the same drawing code paints a tk canvas in the window and a PNG in
`--snapshot` mode. The snapshot is how an agent, which cannot open a window, checks its own
rendering, and how the README shows a picture without a screenshot. Pillow is a dev-only
dependency for it; the window itself needs only tkinter.

Dependencies flow downward only: app -> arena_view -> geometry; app -> playback, routes,
arena -> pathfinding. The simulator calls the planner in-process (`generate_objectives` then
`search` or `tour.plan_optimal`). No HTTP.

## Coordinates

Arena origin is bottom-left, y up, centimetres, matching the planner. The canvas origin is
top-left, y down. **Every conversion lives in `geometry.py`** and is unit-tested; nothing else may
compute a pixel. Grid lines every 10 cm, heavier every 50 cm. Axis labels in cm at 0, 50, 100,
150, 200. Obstacles snap to the 10 cm grid.

The tablet (branch `shuenwei-android`, `protocol/Encoder.kt`) sends obstacles as one grid cell
each, `ADD,B<id>,(<cx>,<cy>)` with `cx, cy` in 0..19, origin bottom-left, ids B1..B8, and reports
the robot as `ROBOT,<x>,<y>,<heading>` where x, y are the footprint **centre** in decimal cells
(cell 1,1 is the centre of the start pose) and heading is N/E/S/W or degrees clockwise from
north. The simulator therefore shows positions in **cells** in the panel, the tablet's
vocabulary, and converts with one rule in `geometry.py`:

```
cell (cx, cy)  <->  south_west = (10 cx, 10 cy), north_east = (10 cx + 9, 10 cy + 9)
robot centre cm (x, y)  <->  tablet cell ((x - 5) / 10, (y - 5) / 10)
```

## Obstacles are numbered, not image-identified

In Task 1 the image on an obstacle is unknown until CV recognises it. The tablet identifies
obstacles by number (checklist C.6, C.9: "TARGET, <Obstacle Number>, <Target ID>"). The planner's
`image_id` field is therefore an obstacle identifier, and the simulator labels each obstacle with
that value. New obstacles get the lowest unused id from 1. The planner's accepted range widens
to `config.IMAGE_ID_MIN = 1` (it never uses the value semantically); `docs/protocols/
algorithm-service.md` is updated to say so.

## Visual design

Graph paper with a car. One memorable thing: the robot is a top-down car (body, four wheels,
camera dot) driving over lined paper; everything else is quiet ink on white.

| Token | Value | Used for |
|---|---|---|
| paper | `#FDFDFA` | arena background |
| grid minor / major | `#D5E8DC` / `#A8CDB6` | 10 cm / 50 cm lines |
| ink | `#1B2A2F` | arena border, obstacles, car outline, text |
| muted | `#6A7A7E` | axis labels, secondary text, footprint outline |
| window / panel | `#F7F7F2` / `#FFFFFF` | frame and side panel |
| rule | `#E3E7E1` | panel dividers, scrubber track |
| start zone | fill `#E8F1EA`, edge `#2A9D6B` dashed | 40 x 40 cm at origin |
| image face | `#E4572E` | 1.5 cm stripe (about 5 px) on the face carrying the image; also unreachable outline |
| camera dot | `#2457A8` | front of the car |
| segment colours | `#2457A8 #E4572E #2A9D6B #8E5AC8 #D99A00 #0E9AA7 #C2185B #7A5230` | trail of segment 1..8, and the obstacle chip in the panel |
| planned, not yet driven | `#9AA5A8` dashed | remaining route |

Robot: a dashed `muted` square for the 31 cm planning footprint (from the Robot's own extents,
not config), inside it a rounded body 19 x 23 cm filled white with a 2 px ink outline, four ink
wheel rectangles, a camera dot on the front edge. The sprite rotates with heading, so turns are
visible without a separate heading indicator. Sizes come from the Robot entity and config
constants, never literals in the drawing code.

Obstacle: ink square of `obstacle.clearance` cm with the id centred in paper-white text and the
image-face stripe. Unreachable: paper fill, `#E4572E` dashed outline, red id, reason below.

Panel (right, 300 px): "Plan route" primary button, "Open arena", "Save arena"; Route section
with a radio per registered `RouteSource` -- "Greedy, nearest first" and "Shortest time", in
registry order, greedy first because it is the fast one to press -- then total length in cm,
estimated time as `m:ss`, and planning time. Choosing a source clears the route, so the two are
never confused; "Driving time" is driving only, while the transport clock adds the capture
dwells, which is why the two disagree. Obstacles list with
a coloured chip per obstacle (colour = its segment), position, face, and state (captured / next /
unreachable + reason); Captured list in visit order with the estimated time of each capture.

Transport bar (bottom): Play/Pause, Step, Reset, speed pills 0.5x 1x 2x 4x, a scrubber, the
clock as `m:ss` followed by "est. of 6:00", and "k of N".

Fonts: UI family from `fonts.py`; all numbers in the mono family with tabular figures. Sentence
case everywhere. Buttons say what they do: "Plan route", "Open arena", "Save arena".

## Playback

The planner's `Segment.vectors` is a collision-check set, not a path: a turn's arc comes out of
`turn.__offsets` with its two ends interleaved, every arc cell carries the post-turn heading, and
the arc is the path of a point `lead` cm behind the robot centre (`robot.south_length -
TURN_PIVOT_OFFSET_CM`, 12 cm for the 31 cm robot), while the appended end pose is the new centre.
Two consequences, both handled:

- `Segment.compress` orders each arc in driving order and exposes `Segment.moves`, the parts in
  sequence. `vectors` (and the HTTP `path`) become an ordered path as a side effect.
- `playback.py` builds one `Frame` per cell with a continuous `Pose(x, y, heading_deg)`: straight
  cells as-is; arc frames are placed on the true circle through the arc's end cells, with the
  heading equal to the angle swept, so the car glides through turns; then the end pose. So the car
  rotates through turns and never jumps.

The last frame of each segment carries `captured_id` and is repeated `CAPTURE_DWELL_FRAMES` (10)
times so the capture moment is visible. Dwell frames add neither distance nor time.

Each frame carries two running totals, because they are not proportional. `distance_cm`
accumulates per move from the planner's own costs (a cell per straight cell, `arc_length` per
turn), so at the end it equals `Route.total_cost * cell_size`; that is the length readout.
`seconds` accumulates under `pathfinding.cost.TIME_SECONDS` -- the model the optimiser
minimises -- so a straight cell adds `cell_size / config.ROBOT_SPEED_CM_S` and a turn adds a
flat `config.TURN_TIME_S` spread evenly over its arc frames, and at the end it equals
`Route.seconds`. `estimated_seconds = frame.seconds` plus `config.CAPTURE_DWELL_S` per capture
so far. Empty routes, single-frame routes, `step()` past the end, `seek()` clamping and
`reset()` are all handled and tested.

Speed pills set ms per frame: 40, 20, 10, 5. The loop is `root.after`, never a thread. The handle
is stored so Pause and window close can cancel it.

## Editing

| Action | Effect |
|---|---|
| Left-click empty cell | add a 10 cm obstacle, face S, lowest unused id |
| Left-click an obstacle | cycle face N -> E -> S -> W |
| Right-click or control-click an obstacle | remove (control-click on empty space does nothing) |
| Drag an obstacle | move it, snapped |

Refused with a message in the status line, never silently: overlapping another obstacle, outside
the arena, overlapping the start zone, more than `config.IMAGE_ID_MAX` obstacles. Any edit
clears the current route and playback.

## Open and save

`arena.py` reads and writes the `PathfindingRequest` JSON exactly as the RPi sends it (robot
plus obstacles, cm, inclusive corners). Open accepts anything in `testdata/` or `.replay/`, so a
real request that misbehaved can be replayed in front of a supervisor. Save writes the current
arena with the configured start pose and `"verbose": false`.

## Config additions

In `config.py`, in the existing provenance format:

```python
START_ZONE_CM = 40          # RULES | measured
OBSTACLE_SIZE_CM = 10       # RULES | measured; also the tablet's grid cell
ROBOT_SPEED_CM_S = 30       # STM | placeholder, NOT MEASURED
CAPTURE_DWELL_S = 2.0       # CV | placeholder, capture + inference time
TASK_1_TIME_LIMIT_S = 360   # RULES | measured
ROBOT_BODY_CM = (19, 23)    # STM | measured from briefing photo, width x length
IMAGE_ID_MIN = 1            # was 11; see "Obstacles are numbered"
```

## Testing

`algorithm/tests/`, one file per module, run with `python -m pytest tests -q` from
`algorithm/`. A `conftest.py` puts `algorithm/` on `sys.path`.

- geometry: `to_canvas(0,0)` is bottom-left, `to_canvas(0,200)` is top-left, round trip,
  `rect` flip, `snap`, cell <-> corners, car outline rotates with heading.
- arena: add/remove/move/cycle, every refusal reason, `testdata/02-four-obstacles.json`
  round-trips; obstacles keep ids, faces, corners.
- routes: `GreedyRouteSource.plan(world)` equals `generate_objectives` + `search` directly:
  same ids, costs, instructions; `Route.seconds` is the sum of its segments'; the registry is
  greedy then optimal, and the optimal route photographs at least as many obstacles as greedy
  and, at the same count, takes no longer.
- playback: frame count, one capture per segment at its last frame, dwell repeats, distance
  and time both exclude dwell, the last frame's clock is `Route.seconds` plus one
  `CAPTURE_DWELL_S` per segment, captured order equals `[s.image_id for s in segments]`,
  reset, step past end, seek clamp, empty route.
- arena_view: against a recording painter, the start zone lands bottom-left, every obstacle is
  drawn with its face stripe, unreachable obstacles use the warning style, the car is drawn at
  the pose.
- snapshot: renders `testdata/02` to a PNG file that exists and has the arena's pixel size.

Not unit-tested: `app.py`, `fonts.py`, `TkPainter`. `python -m simulator --selftest` opens
the window, plans testdata 02, steps through the route, edits the arena and re-plans, then
switches to "Shortest time" and plans and plays that too, and exits, so a crash in wiring is
caught without eyes. Everything visual is verified by a human with the checklist below.

## Manual checklist (also the demo script)

1. Window opens; grid every 10 cm; start zone bottom-left. If it is top-left, the flip is wrong.
2. Open `testdata/02-four-obstacles.json`; four obstacles appear with ids and marked faces.
3. Click to add a fifth; click it to cycle its face; right-click removes it; overlap is refused.
4. Plan route; route appears, obstacles get segment colours, remaining route is dashed.
5. Play; the car drives, arcs are visibly arcs, the car rotates through turns.
6. Each id appears in Captured as the car arrives, with a visible pause.
7. Clock counts up and reads "est. of 6:00".
8. Step advances one frame; Reset returns to start and clears Captured.
9. Build an arena with an obstacle against the wall it faces; Plan; it is drawn unreachable
   with `NO_OBJECTIVES`. Correct, not a bug.
10. Plan with zero obstacles; no crash.
11. Save arena; the file is a valid request body (curl it at the service).
12. Choose "Shortest time" and Plan again (it thinks for longer; the button says
    "Planning..."). The route is drawn the same way; it photographs at least as many obstacles as greedy and, at equal count, its "Driving time" is no larger than the
    greedy one's. That is B.3.

## Phases

1. `geometry`, `fonts`, `arena_view`, minimal `app`: static render of testdata 02. Gate: checks 1-2.
2. `routes`, `playback`, transport bar. Gate: checks 4-5, 8. **Earns B.1.**
3. Captured list, clock, config additions. Gate: checks 6-7. **Earns B.2.**
4. Editing and `arena` open/save. Gate: checks 3, 9-11.
5. Unreachable rendering, route selector. Ready for the optimiser to plug in.
6. `OptimalRouteSource`, the time-model clock, "Driving time". Gate: check 12 and the
   selftest's second plan. **Earns B.3.**

## Risks

- Y flip: isolated in `geometry.py`, asserted by tests, gated at phase 1.
- Planning blocks the UI, and "Shortest time" costs several times what greedy does: disable
  the button and show "Planning..." Not threaded. Latency figures live in `README.md`
  limitation 8, so there is one place to keep them honest.
- Legal 30 cm obstacle spacing comes back unreachable: real planner limitation
  (`README.md` limitation 1). The simulator makes it visible; say it before demoing.
- Clock is a guess until STM measures speed: labelled "est." in the UI, placeholder in config.
- tkinter missing: documented per platform above.
