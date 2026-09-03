# Algorithms: what is left to do

Updated 2026-09-04 (week 4). Checklist and quiz are Friday of week 7, about 25 Sep. The
simulator and the shortest-time optimiser are built; what remains is yours to do or to ask.

## 1. Commit the optimiser

One commit from the repo root on `kejun-structure`:

```sh
git add algorithm/PROVENANCE.md algorithm/README.md algorithm/config.py algorithm/pathfinding algorithm/pathfinding_controller.py algorithm/simulator algorithm/smoke.py algorithm/testdata algorithm/tests docs/protocols docs/algorithms-todo.md docs/superpowers
git commit -m "algorithm: shortest-time optimiser (B.3), optimal by default over http with a strategy field, sim gets a Shortest time source" -m "search core rewritten on int indices + cached arcs: 25x faster, byte-identical. 126 tests, smoke 5/5"
```

If Kushaan's branch `kushaan-simulator` is ever merged, take only his `SERVER_PORT` change (if
the RPi wants 8000) and drop his `turn.py` edit: it orders arcs the wrong way for half the turn
cases and lacks Fix 6. Our `turn.py` was rewritten since, so the merge will conflict on the whole file.

## 2. Manual test of the simulator (10 minutes, at the keyboard)

No agent can see the window. From `algorithm/` (Windows: `.venv\Scripts\python`):

```sh
./.venv/bin/python -m simulator
```

| # | Do | Expect |
|---|---|---|
| 1 | Open the window | Grid every 10 cm, start zone bottom-left |
| 2 | Open arena, pick `testdata/02-four-obstacles.json` | Four obstacles with ids and a red stripe on the image face (11 south, 12 west, 13 west, 14 east) |
| 3 | Click an empty cell; click it again; right-click it; place one on top of another | Adds with the lowest free id facing S; click cycles the face; right-click (or control-click) removes; overlap is refused with a message under the arena |
| 4 | Drag an obstacle | Moves cell by cell; the route is dropped |
| 5 | Plan route | Route drawn, chips take segment colours, remaining route dashed, Total length, Driving time and Planned in shown |
| 6 | Play | Continuous like a video, curved turns, the car rotates; Play reads Pause while running |
| 7 | Watch a capture | Green ring, a pause, the id under Captured with a time, "k of N" in the bar |
| 8 | Clock | Counts up, reads "est. of 6:00" (driving plus 2 s per capture) |
| 9 | Step, Reset, scrubber, speed pills, space, right arrow, r | Step is one frame; Reset clears; scrub seeks; pills change speed |
| 10 | Open `testdata/05-greedy-loses.json`; Plan with "Greedy, nearest first"; then pick "Shortest time" and Plan | Greedy's last leg loops around the right wall (35 s); shortest time has no loop (30 s). This is the B.3 demo |
| 11 | Open `testdata/03-unreachable.json`, Plan | Obstacle 13 red dashed with NO_OBJECTIVES. Correct: it faces a wall 40 cm away |
| 12 | Remove all obstacles, Plan | No crash, hint says "Plan a route to begin." |
| 13 | Save arena, then curl the file at the running service | Valid request body, 200 |

Screenshot anything odd. This list doubles as the demo script (place five obstacles live, Plan
with both sources, Play, point at Captured and the clock).

## 3. Questions for teammates

### RPi owner
1. What do you put in `image_id`: the Android obstacle number (1 to 8) or something else? The
   planner accepts 1 to 40 and echoes it back.
2. Android sends obstacles as one grid cell (cx, cy) in 0 to 19, origin bottom-left. Do you
   convert to cm corners (10cx, 10cy) to (10cx+9, 10cy+9), or should the planner accept cells?
3. Does your HTTP client reject unknown JSON fields? Responses now carry `unreachable`, and per
   segment `seconds`; requests may carry `strategy` ("optimal" default, "greedy").
4. Is port 5000 fine (Kushaan's branch says 8000)? Laptop IP on your hotspot, static?
5. For `ROBOT, x, y, d` to the tablet: do you want the robot's end pose per segment from me?
   Android expects the footprint centre in decimal cells and a heading letter or degrees.
6. Do you forward my instruction tokens to STM as-is or translate? What exact string does STM
   accept? Would you rather I emit STM strings directly?
7. When CV reports a bull's-eye, do you want a re-plan endpoint (current pose, remaining
   obstacles, faces already checked) or will you handle it on the Pi?
8. Do you request the plan once at start? Planning now takes under a second.
9. Heads-up: `segments[].path` is in driving order (was an unordered cell set), and routes for
   the same arena differ from anything recorded before 3 Sep (a turn bug was fixed; the default
   order is now shortest-time).

### STM owner
1. Four turning radii at competition speed (forward-left, forward-right, backward-left,
   backward-right): centre displacement dx, dy in cm after a 90 degree turn from a tape mark.
   Current values are another team's car (39/40/37/39).
2. Where is the turning pivot relative to the robot centre? The planner assumes the arc is traced
   by a point 12 cm behind the centre.
3. Does a turn command produce exactly 90 degrees? Any straight travel before or after, in cm?
4. Straight speed in cm/s and seconds per 90 degree turn at competition speed. The optimiser
   ranks routes by `distance / speed + turns x turn_time`; both are placeholders (30 cm/s, 3 s).
5. Chassis width and length including wheels and camera mount. The planner reserves 31 cm, which
   makes obstacles at the legal 30 cm spacing unreachable.
6. Smallest straight distance you can execute reliably: 1, 5, 10 cm?
7. Are backward turns reliable, with different radii?

### CV owner
1. Best camera-to-obstacle distance in cm and the acceptable band (deck says 20, checklist 20 to
   50). From the lens or the robot's front edge? Planner uses 25 to 30 today.
2. How far off-centre can the image be? The planner parks up to 10 cm off-centre to save turns.
3. Camera position: distance from the front edge and from the centreline.
4. Is a bull's-eye its own class, distinct from "nothing seen"?
5. Capture plus inference time in seconds (simulator assumes 2 s).

### Android owner
Read from branch `shuenwei-android`: `ADD,B<id>,(<cx>,<cy>)`, faces N/E/S/W, `ROBOT,x,y,d` as
centre in decimal cells, ids 1 to 8. Two confirmations:
1. Is that `ROBOT` format still current?
2. Do you want the planned path drawn on the tablet? I can supply it per cell.

## 4. Checklist status (algorithms share, items B.1 to B.3)

| Item | Status | What is left |
|---|---|---|
| B.1 Robot movement area simulator | Built | Manual test above, then demo |
| B.2 Hamiltonian path simulator | Built | Same, with five obstacles placed live |
| B.3 Shortest-time Hamiltonian path | Built | Manual test row 10, then demo the source switch |

Also on your plate: quiz (week 7 Friday 08:30) on the deck's algorithm material; video footage
(record the simulator now); commit under your own name.

## 5. What I still owe you, in order

1. **Config numbers once teammates answer** (footprint, clearance, standoff, lateral tolerance,
   turning radii, speed, turn time, dwell). Today an obstacle facing a wall within about 45 cm is
   unreachable, which is legal in the competition.
2. **Optional, Task 1 robustness:** re-plan endpoint from the current pose for the bull's-eye
   case, if the RPi owner wants it.
3. **Optional, quiz aid:** a small Dubins implementation. Not graded as code.

## 6. Greedy vs shortest time, in one paragraph

Greedy plans from wherever the robot is to the nearest unvisited obstacle by true path cost in
centimetres, and repeats. Shortest time first builds a table of estimated driving seconds
between every pair of obstacles (and the start), enumerates visiting orders in ascending
table cost, re-plans each candidate order leg by leg from the real arrival poses, and keeps the
best. Greedy's real route is always one of the candidates, so shortest time never photographs
fewer obstacles and, at equal count, never takes longer; it stops when the table proves no
remaining order can win ("proven optimal" in the log). On `testdata/05` it is 14% faster; on
`testdata/02` greedy was already optimal and the log says so.
