# Algorithms: what is left to do

Updated 2026-09-04 (week 4). Checklist and quiz are Friday of week 7, about 25 Sep.

Branches:

- `kejun-structure` is the stable one. Planner, tkinter simulator, shortest-time optimiser.
- `kejun-experimental-algo` adds the eight-heading experiment (section 5) and the fixes from
  the code review. Not merged.

Checklist items B.1, B.2 and B.3 are built and manually tested. What is left is on other
people, plus the demo and the quiz.

## 1. Commit

On `kejun-experimental-algo`. Everything up to the eight-heading experiment is committed
(`f864c5f`). Unstaged: the simulator heading toggle and the review fixes.

```sh
git add algorithm docs
git commit -m "fix: cardinal-only headings on the wire, true diagonal pricing, half-price 45 turns" -m "northwest face was a 500, now a 422. diagonal cells cost 1.41 in the search too, so routes are picked under the numbers they are driven under. 4-heading planning 27% quicker. 138 tests"
```

What is in that commit:

| Fix | Why it mattered |
|---|---|
| Requests accept only NORTH/EAST/SOUTH/WEST for a robot or obstacle direction | A face of `NORTHWEST` used to return 500. It now returns 422 |
| `docs/protocols/openapi.json` regenerated, deviation 7 added to the protocol doc | The published schema had drifted from the running server |
| The search prices a diagonal cell at 1.41, not 1 | It was choosing routes it was not paying for |
| A 45 degree turn costs half a 90 in seconds | It was charged a full turn. This is most of the change in section 5 |
| `MoveInstruction` reports ground distance | 25 diagonal cells used to go out as `FORWARD 25`. The robot has to drive 35 cm |
| The search allocates 4 headings when the diagonals are off, not 8 | Four-heading planning is 27% faster. Output is unchanged |
| Two diagonal tests strengthened | One of them could not fail. The new one checks that two 45 degree turns land where one 90 does |

If `kushaan-simulator` is ever merged, take only his `SERVER_PORT` change (if the RPi wants
8000). Drop his `turn.py` edit: it orders arcs the wrong way for half the turn cases and lacks
Fix 6. Our `turn.py` was rewritten since, so the merge will conflict on the whole file.

## 2. Manual test of the simulator

Run 2026-09-04. Rows 1 to 13 passed. Row 14 was added afterwards and has not been run.

From `algorithm/` (Windows: `.venv\Scripts\python`):

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
| 14 | **Not yet run.** Pick "Shortest time", tick `8 headings, 45 deg turns`, Plan; untick, Plan | Each tick drops the route. Eight headings gives diagonal legs and about 21 s Driving time on testdata 02, against about 41 s for four |

This list is also the demo script: place five obstacles live, Plan with both sources, Play,
point at Captured and the clock.

## 3. Questions for teammates

Status as of 2026-09-04: STM, CV and RPi are all still configuring, so none of these are
answered. Android can be answered from the `shuenwei-android` branch.

### RPi owner

1. What goes in `image_id`: the Android obstacle number (1 to 8) or something else? The planner
   accepts 1 to 40 and echoes it back.
2. Android sends obstacles as one grid cell (cx, cy) in 0 to 19, origin bottom-left. Do you
   convert to cm corners (10cx, 10cy) to (10cx+9, 10cy+9), or should the planner accept cells?
3. Does your HTTP client reject unknown JSON fields? Responses carry `unreachable`, and
   `seconds` per segment. Requests may carry `strategy` ("optimal" default, "greedy").
4. Does your client validate response enum values? If the eight-heading planner is ever
   switched on, a `path` vector can read `NORTHEAST` and an instruction can read
   `FORWARD_LEFT_45`. Requests are unaffected: they still take the four cardinals only.
5. Is port 5000 fine (Kushaan's branch says 8000)? Laptop IP on your hotspot, static?
6. For `ROBOT, x, y, d` to the tablet: do you want the robot's end pose per segment from me?
   Android expects the footprint centre in decimal cells and a heading letter or degrees.
7. Do you forward my instruction tokens to STM as-is, or translate? What exact string does STM
   accept? Would you rather I emit STM strings directly?
8. When CV reports a bull's-eye, do you want a re-plan endpoint (current pose, remaining
   obstacles, faces already checked), or will you handle it on the Pi?
9. Do you request the plan once at start? Planning takes under a second.

Two heads-ups, no answer needed:

- `segments[].path` is in driving order. It used to be an unordered cell set.
- Routes for the same arena differ from anything recorded before 3 Sep. A turn bug was fixed
  and the default order is now shortest-time.

### STM owner

0. **Can the car drive and stop a 45 degree turn accurately, and how many seconds does it
   take?** This decides whether section 5 is worth anything. If a 45 costs half a 90, it takes
   34 to 57 percent off the route time. If it costs the same as a 90, most of that is gone. If
   the turn cannot be driven cleanly, all of it is. Also: same steering lock and radius as a 90?
1. Four turning radii at competition speed (forward-left, forward-right, backward-left,
   backward-right): centre displacement dx, dy in cm after a 90 degree turn from a tape mark.
   Current values are another team's car (39/40/37/39).
2. Where is the turning pivot relative to the robot centre? The planner assumes the arc is
   traced by a point 12 cm behind the centre.
3. Does a turn command produce exactly 90 degrees? Any straight travel before or after, in cm?
4. Straight speed in cm/s, and seconds per 90 degree turn at competition speed. The optimiser
   ranks routes by `distance / speed + turns x turn_time`. Both are placeholders (30 cm/s, 3 s).
5. Chassis width and length including wheels and camera mount. The planner reserves 31 cm,
   which makes obstacles at the legal 30 cm spacing unreachable.
6. Smallest straight distance you can drive reliably: 1, 5 or 10 cm?
7. Are backward turns reliable? Different radii?

### CV owner

1. Best camera-to-obstacle distance in cm, and the acceptable band. The deck says 20, the
   checklist says 20 to 50. Measured from the lens or from the robot's front edge? The planner
   uses 25 to 30.
2. How far off-centre can the image be? The planner parks up to 10 cm off-centre to save turns.
3. Camera position: distance from the front edge, and from the centreline.
4. Is a bull's-eye its own class, separate from "nothing seen"?
5. Capture plus inference time in seconds. The simulator assumes 2 s.

### Android owner

From branch `shuenwei-android`: `ADD,B<id>,(<cx>,<cy>)`, faces N/E/S/W, `ROBOT,x,y,d` as centre
in decimal cells, ids 1 to 8. Two things to confirm:

1. Is that `ROBOT` format still current?
2. Do you want the planned path drawn on the tablet? I can supply it per cell.

## 4. Checklist status (items B.1 to B.3)

| Item | Status | What is left |
|---|---|---|
| B.1 Robot movement area simulator | Done | Demo it |
| B.2 Hamiltonian path simulator | Done | Demo it with five obstacles placed live |
| B.3 Shortest-time Hamiltonian path | Done | Demo the route source switch (manual test row 10) |

Also yours: the quiz (week 7 Friday 08:30) on the deck's algorithm material, video footage
(record the simulator now), and committing under your own name.

## 5. Eight headings, on branch `kejun-experimental-algo`

The planner uses four headings and 90 degree turns. That branch adds the four diagonals and a
45 degree turn, behind `config.DIAGONAL_HEADINGS`. It is **off by default**, so nothing changes
until someone turns it on.

Measured 2026-09-04 with the shortest-time planner, after the pricing fixes in section 1:

| Arena | Four headings | Eight headings | Change |
|---|---|---|---|
| `02-four-obstacles` | 41.50 s, 11 turns | 20.94 s, 11 turns | -50% |
| `04-five-obstacles` | 62.33 s, 17 turns | 26.98 s, 14 turns | -57% |
| `05-greedy-loses` | 30.33 s, 8 turns | 20.08 s, 10 turns | -34% |
| `01-single-obstacle` | 7.83 s, 2 turns | 6.24 s, 2 turns | -20% |

Planning takes 0.8 to 1.3 s with the diagonals on, 0.3 to 0.5 s with them off.

The first measurement said 22 to 34 percent. It was taken under two pricing bugs, both now
fixed. The search priced a diagonal cell at 1 when it covers 1.41, and it charged a 45 degree
turn a full `TURN_TIME_S` instead of half. The second bug is the big one: on `02` the route has
ten 45 degree turns and one 90, which is 33 s of turn charge under the old flat rate and 18 s
under the corrected one.

Three things to keep in mind:

1. **The size of the win depends on a 45 costing half a 90 in seconds.** Turns dominate the
   time model, at 3 s per turn against 30 cm/s of driving. If the STM has a fixed per-command
   overhead that makes a 45 cost the same as a 90, most of the table above disappears. This is
   STM question 0.
2. The greedy planner gets worse with more options on some arenas. That is normal for greedy
   and does not matter, because optimal is the default.
3. The five-obstacle result hits the re-plan cap. It is the best route tried, not a proven
   optimum.

To try it: tick **8 headings, 45 deg turns** in the simulator's Route panel and plan again. The
checkbox only affects that simulator process. It does not edit `config.py`, so the HTTP service
the RPi talks to keeps planning with whatever the file says. To change the service, edit
`DIAGONAL_HEADINGS` in `algorithm/config.py` and restart it.

**Blocked on STM question 0.** A 45 degree turn is modelled as the same steering lock held half
as long: same radius, half the arc, half the time. If the car cannot do that, the routes look
better on screen and are worse on the floor.

## 6. What I still owe you

1. **Config numbers, once teammates answer.** Footprint, clearance, standoff, lateral
   tolerance, turning radii, speed, turn time, dwell. Today an obstacle facing a wall within
   about 45 cm comes back unreachable, and that spacing is legal in the competition.
2. **Optional: a re-plan endpoint** from the current pose for the bull's-eye case, if the RPi
   owner wants it.
3. **Optional: a small Dubins implementation** as a quiz aid. Not graded as code.

## 7. Greedy vs shortest time

Greedy plans from wherever the robot is to the nearest unvisited obstacle by true path cost in
centimetres, then repeats.

Shortest time builds a table of estimated driving seconds between every pair of obstacles and
the start. It lists visiting orders in ascending table cost, re-plans each candidate order leg
by leg from the real arrival poses, and keeps the best one. Greedy's own route is always one of
the candidates, so shortest time never photographs fewer obstacles, and at an equal count it
never takes longer. It stops when the table proves no remaining order can win, which the log
reports as "proven optimal".

On `testdata/05` it is 14% faster than greedy. On `testdata/02` greedy was already optimal, and
the log says so.
