# SC2079 Multi-Disciplinary Design Project — Agent Brief

> **Read this first.** This file is the single source of truth for what we are building, what the
> graders actually measure, and which numbers are real. It is written for a coding agent working in
> this repository. Everything here is derived from the official NTU SC2079 briefing decks
> (MDP general briefing + Algorithms briefing by Huang Shell Ying) plus an analysis of a
> prior-year reference implementation.
>
> **Where the two official briefings disagree, the general MDP briefing wins.** See
> [§3.3 Contradictions](#33-contradictions-between-the-two-briefings).

---

## 1. The mission in one paragraph

Build a robotic system that autonomously explores a known arena, drives up to obstacles, recognises
images pasted on them, avoids collisions using bull's-eye visual markers, exchanges control and
status messages with an Android tablet over Bluetooth, and simulates the robot and its algorithms in
software. The system is graded on two live competitive runs plus a functionality checklist, a video,
peer review, and an individual quiz.

---

## 2. System architecture

Four subsystems. Assume all four exist and must interoperate; do not design anything that assumes a
monolith.

| Subsystem | Hardware / stack | Responsibility |
|---|---|---|
| **Robot / STM** | STM32F407VET6 controller board, 4-wheel Ackermann-style chassis, servo steering, motor encoders, IR + ultrasonic sensors | Executes low-level motion primitives, closed-loop distance/angle control, obstacle proximity sensing |
| **RPi** | Raspberry Pi + Pi Camera (ribbon-mounted at front centre) | Central hub. Bridges Android ⇄ STM ⇄ algorithm service ⇄ image recognition. Captures frames, stitches result images |
| **Image recognition** | Python, CV model (reference year used YOLO) | Classifies captured frames into image IDs, rejects bull's-eyes, reports confidence |
| **Algorithms** | Path planner + simulator | Plans the visiting order and the trajectory between poses; emits motion instructions; visualises the run |
| **Android** | Android tablet app, Bluetooth SPP | Remote control, arena editor, live robot position display, status messages, stitched-image display |

### 2.1 Communication topology

```
Android tablet  <--Bluetooth SPP-->  RPi  <--Serial/USB-->  STM32
                                      |
                                      +--HTTP/REST (Wi-Fi or localhost)--> Algorithm service
                                      |
                                      +--local call / REST--> Image recognition
```

The RPi is the only component that talks to everyone. Keep every other subsystem's interface narrow
and testable in isolation.

### 2.2 Hard interface rule

Every cross-subsystem message must be a **documented, versioned, machine-checkable contract**
(OpenAPI for HTTP, a written string protocol for Bluetooth/serial). Integration is where MDP teams
lose the most time. Do not let two subsystems agree on a format verbally.

---

## 3. Physical constants and arena spec

### 3.1 Robot

| Property | Value | Source / notes |
|---|---|---|
| Actual chassis footprint | ~18.6–18.8 cm wide × 23 cm plate length | Measured photo in general briefing |
| Algorithms-briefing footprint | 20 cm × 21 cm | Algorithms deck §Robot's Environment |
| **Planning footprint (use this)** | **30 cm × 30 cm** | Deliberate safety margin recommended by the algorithms deck |
| Turning radius | ~25 cm nominal; **larger at higher speed** | Must be re-measured on our own car |
| Camera | Fixed, front centre, conical FOV | Best image recognition at **~20 cm** from obstacle face |
| Start zone | 40 cm × 40 cm at bottom-left of arena, origin (0,0) | |

> **Do not hardcode the nominal 25 cm.** Turning radius is direction-asymmetric on these cars
> (forward-left ≠ forward-right ≠ backward-left ≠ backward-right) and speed-dependent. Calibrate
> empirically and store the four measured radii in one config module. See §7.3.

> **Standoff distance is stated three ways in this document and they do not agree.** §3.1 gives the
> camera optimum as **~20 cm**; §7.5 recommends a goal band of **~25–30 cm**; and §7.2's two
> representations disagree with each other — Option 1's `(a−10, b−45)` puts a 30 cm robot's front
> edge **30 cm** from the face, while Option 2's `(a−1, b−5)` on 10 cm cells leaves **20 cm**. This
> may be an artefact of `(a, b)` denoting different things in the two options. **Confirm against the
> deck before coding**, then pick one number, put it in config, and reference it everywhere. See §10.

### 3.2 Arena and obstacles

| Property | Value |
|---|---|
| Arena | 200 cm × 200 cm square, **virtual** boundaries (no physical wall) |
| Obstacle footprint | 10 cm × 10 cm block |
| Obstacle orientation | Always axis-aligned with the arena sides |
| Image faces | Exactly **one** of four faces carries the target image; the other three carry a bull's-eye marker |
| Reachability guarantee | No image will be placed where the robot cannot reach it |
| Straight-line clearance | Needs **30 cm** between two obstacles, or between an obstacle and the boundary |
| Turning clearance | Turning between two obstacles needs their nearest corners ≥ 30 cm apart in *both* axes |
| Virtual obstacle inflation | 40 cm × 40 cm (10 cm obstacle + 15 cm each side) when treating the robot as a point |

### 3.3 Contradictions between the two briefings

These are real and the coding agent must not silently pick one.

| Topic | Algorithms deck | General MDP briefing | **What we build for** |
|---|---|---|---|
| Obstacle count | Exactly 5 | **4 to 8** | Accept `N` obstacles, `4 ≤ N ≤ 8`. Never hardcode 5 |
| Image set size | 15 images | **~30 images**, IDs 11–40 | Support the full ID 11–40 table |
| Arena | Fixed 200×200 lab arena | **NOT a fixed arena** — evaluation arena may be drawn anywhere in NTU | Never depend on floor texture, lighting, or lab landmarks |
| Background | Implicitly the lab floor | Explicitly **"background agnostic"** | Vision must be robust to arbitrary backgrounds |

**Consequences for the code:**

- Exhaustive-search path planning must scale to 8 obstacles (`8! = 40 320` orderings), not 5 (`120`).
  Either prune or fall back to a heuristic above a threshold.
- The vision model must be trained/augmented across varied backgrounds, floors, and lighting. A model
  fitted to one lab floor is the single most likely cause of a failed run.
- The Android arena editor must let the user place a variable number of obstacles.

### 3.4 Image ID table

| ID | Symbol | ID | Symbol | ID | Symbol |
|---|---|---|---|---|---|
| 11 | 1 | 21 | B | 31 | V |
| 12 | 2 | 22 | C | 32 | W |
| 13 | 3 | 23 | D | 33 | X |
| 14 | 4 | 24 | E | 34 | Y |
| 15 | 5 | 25 | F | 35 | Z |
| 16 | 6 | 26 | G | 36 | Up arrow |
| 17 | 7 | 27 | H | 37 | Down arrow |
| 18 | 8 | 28 | S | 38 | Right arrow |
| 19 | 9 | 29 | T | 39 | Left arrow |
| 20 | A | 30 | U | 40 | Stop (filled circle) |

Bull's-eye markers are **not** in this table. They are a distinct class and must be detected and
reported separately — the recovery logic in §7.8 depends on distinguishing "bull's-eye seen" from
"nothing seen".

---

## 4. Task 1 — Autonomous image recognition (12.5%)

### 4.1 What happens

The robot starts in the 40×40 cm start zone. Obstacle positions and image-face directions are given
in advance (entered via the Android app). The robot must autonomously visit every obstacle, position
itself to see the image face, recognise the image, and report the ID.

### 4.2 Rules

- **Timeout: 6 minutes.**
- Number of images varies **4 to 8**, drawn from the 30-image pool.
- Full marks for identifying **all** images within the timeout.
- Ties on recognition score are broken by **time**. Faster is strictly better.
- Teams below full recognition get a distributed score.
- **The stitched RAW camera images must be displayed as a single image** on Android or PC for
  verification. This is a hard requirement, not a nice-to-have — build the stitching pipeline early.
- One **retry** is allowed per team across Task 1 and Task 2 *combined*. A retry uses a different maze
  setup, the retry score replaces the original, and the team must quarantine its equipment throughout.

### 4.3 Implications for design

- Optimise for **completing all recognitions**, then for time. A run that recognises 8/8 in 5:50 beats
  one that recognises 7/8 in 2:00.
- Budget the 6 minutes: planning time counts. Plan once up-front if possible, and re-plan
  incrementally only on recovery.
- Every capture must be persisted (raw frame + annotation) so the stitched verification image can be
  assembled at the end.

---

## 5. Task 2 — Fastest car (12.5%)

### 5.1 Layout

- Robot starts inside a **carpark**: a 60 cm × 60 cm zone.
- Two **goal obstacles** are placed directly in front of the carpark, in a line.
- Spacing: carpark → obstacle 1 is **60–150 cm**; obstacle 1 → obstacle 2 is **60–150 cm**.
- Each goal obstacle carries a **left or right arrow** image **fixed at the centre of the face
  pointing back toward the carpark**. Bull's-eye markers are placed around the obstacles and carpark.
- Minimum clearance of **50 cm** above and below the obstacle line; beyond that there may be a wall or
  obstacle.

### 5.2 Run sequence

1. Start from the carpark.
2. Drive to goal obstacle 1, read its arrow.
3. Pass around obstacle 1 on the side the arrow indicates.
4. Drive to goal obstacle 2, read its arrow.
5. Pass around obstacle 2 on the side that arrow indicates.
6. Loop around and return, **stopping inside the carpark**.

Time is measured for the whole run.

### 5.3 Rules and penalties

| Rule | Effect |
|---|---|
| Timeout | **3 minutes** |
| Hitting an obstacle | **+10 s penalty per hit** |
| Bulldozing (pushing obstacles) | **Disqualified** |
| Arrow misread, or car goes the wrong way | **Run invalid** |
| Not stopping in the carpark | Run not complete |
| Retry (if not already used on Task 1) | Runs immediately after the first attempt |

### 5.4 Sensing

Permitted: camera (using the bull's-eyes around obstacles and carpark), IR sensor, ultrasonic sensor.
The distance to the first obstacle is unknown at start (60–150 cm), so **the approach must be
sensor-driven, not dead-reckoned**.

### 5.5 Implications for design

- Tasks 1 and 2 are **decoupled**. Task 2 does not need the global planner. It is closer to a reactive
  state machine: `SEEK → READ_ARROW → EXECUTE_S_CURVE → SEEK → READ_ARROW → EXECUTE_S_CURVE → RETURN → PARK`.
- Correctness gates everything — a misread arrow invalidates the run, so bias the arrow classifier
  toward high confidence and re-capture rather than guessing.
- Once correct, the whole game is speed. Tune motor speed vs. turning radius; remember radius grows
  with speed.
- 10 s per collision is severe against a run that should take well under a minute. Leave clearance.

---

## 6. Assessment, deadlines and hard gates

### 6.1 Breakdown

| Component | Weight | When |
|---|---|---|
| **Group — system functionality checklist** | 20% | Friday 5:00 pm, **Week 7** |
| **Group — video presentation** | 15% | End of **Week 10** |
| **Task 1 — image recognition** | 12.5% | Week 8 |
| **Task 2 — fastest car** | 12.5% | Week 9 |
| **Individual — early peer review** | 5% | Week 5 |
| **Individual — final peer review** | 15% | Week 10 |
| **Individual — quiz** | 20% | Friday, Week 7, 08:30–09:30 |

### 6.2 Hard gates

- **Attendance ≥ 80% across weeks 1–9 is required to pass**, regardless of team performance. Late >15
  min = LATE; late >30 min = ABSENT; 2 LATE = 1 ABSENT. Failing this means retaking MDP.
- **Week 7 is 40% of the module in a single day.** The quiz (20%) runs Friday 08:30–09:30 and the
  functionality checklist (20%) is due Friday 5:00 pm — the *same* Friday. Nothing can be allowed to
  slip into that week. Work backwards: every checklist item must be *demonstrable* by the end of
  Week 6, not started in Week 7.
- Peer review: a PE2 score below 50% of the rest of the team can heavily reduce an individual grade.
  **Keep a per-person contribution record** — git history, checklist contributor names, and a running
  log all serve this purpose.

### 6.3 Functionality checklist (20%)

Separate checklists exist for: **Robot hardware**, **RPi communication and image processing**,
**Algorithms**, **Android remote controller**. Each item must be *demonstrated* to a supervisor, who
signs it. **Student contributor names must be written in for each component.**

Example of the required standard (Android module, items C.1–C.4):

- **C.1** — App transmits and receives text strings over the Bluetooth serial link (bi-directional).
- **C.2** — Functional GUI that scans for, selects, and connects to a Bluetooth device.
- **C.3** — Functional GUI giving interactive control of robot movement over Bluetooth (buttons,
  gestures, or tilt). *Typing raw command strings into a text box does not satisfy this.*
- **C.4** — Functional GUI showing remote status updates (e.g. "ready to start", "looking for target
  2") via a selective TextView — **not** a raw dump of the whole serial stream.

**Plan the codebase so each checklist item is independently demonstrable**, ideally behind a debug
screen or a CLI flag. Do not build a system that can only be shown working end-to-end.

### 6.4 Video (15%)

Max **5 minutes**; anything from 5:01 onward is not graded. Replaces the written report and live
presentation. Judged on novelty, creativity, presentation, teamwork. Capture footage *as you go* —
successful runs, simulator visualisations, and debugging moments cannot be re-shot in week 10.

### 6.5 Subsystem contacts (course staff)

These are the module's supervising staff for each subsystem — not our team's owners.

| Area | Course contact |
|---|---|
| Robot & STM32F407VET6 | Loke Yuan Ren |
| RPi & image processing | Oh Hong Lye |
| Algorithms | Huang Shell Ying |
| Android | Goh Wooi Boon |

---

## 7. Algorithms reference

### 7.1 Problems to solve

1. Represent the arena, robot, obstacles, and image positions.
2. Find a (shortest/fastest) **Hamiltonian path** from START through all obstacle-viewing poses.
3. Plan a feasible trajectory between two robot configurations.
4. Avoid obstacles and the boundary.
5. Recover when the image is not where expected.
6. Simulate all of the above.

### 7.2 Representation

Two sanctioned options:

**Option 1 — continuous coordinates.** 200×200 cm area; robot pose `(x, y, θ)` with `−π < θ ≤ π`,
East = 0. Obstacle identified by its bottom-left corner `(h, k)`; image identified by `(h, k, F)`
where `F ∈ {E, N, W, S}`. For an image at `(a, b, S)`, target the robot at `(a−10, b−45, π/2)`.

**Option 2 — grid.** 20×20 grid of 10×10 cm cells (or 40×40 of 5×5 cm). Robot = 3×3 cells, obstacle =
1×1 cell. For an image at `(a, b, S)`, target the robot's bottom-left cell at `(a−1, b−5, π/2)`.

In both cases: **the robot centre need not be exactly aligned with the image centre.** Exploit this —
see §7.5.

### 7.3 Motion model

Discrete-time approximation of car dynamics:

```
x_new = x_prev + Δ·cos(θ)
y_new = y_prev + Δ·sin(θ)
θ_new = θ_prev + Δ/r
```

where `Δ` is the straight-line distance per time step and `r` the turning radius.

**Calibration requirement:** measure `r` separately for forward-left, forward-right, backward-left,
and backward-right, at the actual competition speed. Store them in one config module and nowhere
else. The reference implementation used 39 / 40 / 37 / 39 cm — proof that the asymmetry is real and
large, but those are *their* numbers, not ours.

### 7.4 Dubins paths (option A for trajectory planning)

Dubins (1957): every shortest path for a forward-only car with a minimum turning radius is at most
three segments, of type **CSC** or **CCC** — i.e. `rsr`, `rsl`, `lsr`, `lsl`, `rlr`, `lrl`, where `C`
is an arc of the minimum-radius circle and `S` a straight line.

**CSC construction (rsr shown):** with turning-circle centres `p1`, `p2`,

```
l  = √((p2x−p1x)² + (p2y−p1y)²)
V1 = (p2x−p1x, p2y−p1y)
V2 = rotate V1 CCW by π/2 = (−V1y, V1x)
pt1 = p1 + (r/l)·V2
pt2 = pt1 + V1
```

**rsl construction:**

```
d  = √((p2x−p1x)² + (p2y−p1y)²)
l  = √(d² − (2r)²)
δ  = arccos(2r / d)
V1 = (p2x−p1x, p2y−p1y)
V2 = rotate V1 CCW by δ
pt1 = p1 + (r/d)·V2
V3 = −V2
pt2 = p2 + (r/d)·V3
```

**CCC (rlr) construction:** find the third circle centre `p3`. `q` = midpoint of `p1p2`;
`|p1p3| = |p2p3| = 2r`; distance from `p3` to `q` is `√((2r)² − (d/2)²)`; `p3 = q + that·V2/‖V2‖`
where `V2` is `V1` rotated by ±π/2. Transition points `pt1`, `pt2` are the midpoints of `p1p3` and
`p2p3`. **CCC is only useful when `d < 4r`**; otherwise CSC is shorter.

**Arc length:**

```
V1 = p − p1        (centre → source)
V2 = pt1 − p1      (centre → target)
α  = atan2(V2y, V2x) − atan2(V1y, V1x)
if α < 0 and turning left:  α += 2π
if α > 0 and turning right: α -= 2π
arc_length = |α · r|
```

Total path length = sum of two arcs + straight (CSC), or three arcs (CCC).

Vector helpers: CCW π/2 → `(−y, x)`; CW π/2 → `(y, −x)`; reverse → `(−x, −y)`; CCW by θ →
`(x cosθ − y sinθ, x sinθ + y cosθ)`.

### 7.5 Path planning (option B — recommended, see §8.3)

Grid search over the state space `(x, y, facing)` with motion primitives as edges. This sidesteps
Dubins entirely and handles reversing naturally, which Dubins does not.

- Neighbours: `FORWARD_LEFT`, `FORWARD_RIGHT`, `BACKWARD_LEFT`, `BACKWARD_RIGHT` (precomputed arcs),
  plus straight forward/backward in fixed-length chunks.
- **Generate a *set* of acceptable goal poses per obstacle**, not a single point — a band of standoff
  distances (~25–30 cm from the face) crossed with a lateral alignment tolerance (±10 cm). The search
  terminates on whichever member is cheapest to reach. This is the single highest-value idea in this
  document.
- Make all remaining obstacles' goal poses simultaneous goal states in one search. "Nearest unvisited
  obstacle" then falls out of the frontier for free, measured in true path cost rather than Euclidean
  distance.

### 7.6 Visiting order

- **Greedy nearest-neighbour**: from START, repeatedly go to the nearest unvisited obstacle.
- **Improvement**: 2-opt style pairwise swaps on the resulting order; and skip Dubins computation for
  any candidate whose Euclidean distance already exceeds the current best path length.
- **Exhaustive search**: viable at 5 obstacles (120 orderings). At 8 obstacles it is 40 320 orderings
  — feasible only if the per-leg cost is cached in a precomputed matrix. **Compute the all-pairs leg
  cost matrix once, then search orderings over the matrix.** Never re-run path search inside the
  permutation loop.
- Euclidean nearest-neighbour is inaccurate; prefer BFS/true-path distance for the "nearest" decision.

### 7.7 Obstacle avoidance

- After recognising an image the robot is nose-to-obstacle and **must reverse first**.
- Simplest correct approach: inflate obstacles to **40 cm × 40 cm virtual obstacles** and treat the
  robot as a point at its centre. The planned path must never enter a virtual obstacle.
- Also inflate the arena boundary so the robot body cannot cross it.

### 7.8 Recovery — when the image is not found

Real motion diverges from the plan. Two failure modes, both must be handled:

**(a) Bull's-eye detected instead of the image.** The image is most likely on a neighbouring face.
Reverse, move around the obstacle, re-capture. Once found, continue to the next obstacle.

**(b) No obstacle where one was expected.** First reverse and re-check — the robot may have
overshot. Otherwise abandon the planned path, roam systematically, and go to any obstacle it sees.

### 7.9 Simulator requirements

Explicitly required by the brief and by the checklist:

- Display the 200×200 cm area with the start zone.
- Display obstacles and image positions.
- Display robot position in **real time**, time-stepped (a square or marker is acceptable).
- Report images as they are recognised.

### 7.10 Task 2 — reactive control (no global planner)

Task 2 shares no planning code with Task 1. There is no Hamiltonian path and no visiting order: the
arena is a corridor with two goal obstacles in a line. Model it as an explicit state machine.

```
PARKED ─▶ SEEK_1 ─▶ READ_1 ─▶ ROUND_1 ─▶ SEEK_2 ─▶ READ_2 ─▶ ROUND_2 ─▶ RETURN ─▶ PARK
                      │                              │
                      └──── low confidence ─▶ RECAPTURE ───┘
```

**SEEK — the distance is unknown.** The carpark→obstacle gap is 60–150 cm (§5.1), so the approach
must close the loop on the IR/ultrasonic reading and never dead-reckon. Drive until the sensor
crosses a standoff threshold, then stop. Their firmware exposed a dedicated *drive-until-threshold*
command rather than a distance command (§8.5, flags `W`/`w`) — the concept is worth copying.

**READ — correctness gates the entire run.** A misread arrow invalidates the attempt outright
(§5.3), so this is the one place where waiting is cheaper than guessing. Require a confidence floor
plus N-of-M agreement across consecutive frames; on failure re-approach and re-capture rather than
committing. The 3-minute timeout is generous against a run that should finish well under a minute —
spend the surplus here.

**ROUND — the S-curve is a calibrated manoeuvre, not a planned path.** Passing on the arrow's side
is a fixed shape parameterised by the measured turning radii (§7.3). Precompute both mirror-image
variants once, calibrate them physically, and store them in config (§9.2 rule 1). The 50 cm
clearance above and below the obstacle line (§5.1) bounds how wide the curve may swing — and radius
grows with speed.

**PARK — the run is not complete until the robot stops inside the carpark** (§5.3). Give the return
leg and the park their own states with their own sensor checks; do not append them to ROUND_2.

**Collision budget.** +10 s per hit (§5.3) against a sub-minute run is enormous — roughly a 20% time
penalty per touch — and bulldozing disqualifies outright. Tune for clearance first, speed second.

---

## 8. Reference implementation notes

> **This repository *is* that reference implementation.** We cloned `Pante/SC2079` (AY2023 Sem 2,
> Group 14) with all 312 of its commits and re-pointed `origin` at our own repo. Everything in
> `service/`, `RPi/`, `robot/`, `android/`, `image rec/` and `simulator-client/` is **their** code,
> not ours.
>
> **Stance: read, do not import.** Study these modules for API shape, geometry and hard-won
> constants, then write our own subsystems in new directories (§9.1). Do not import from their
> packages, subclass their types, or edit their files in place — a half-migrated tree is the worst
> of both worlds. Their history stays as provenance; our work lands alongside it.

Their `service/` module is a Flask + `flask-openapi3` pathfinding microservice (Python 3.12, pipenv,
Swagger at `/openapi/swagger`).

### 8.1 Their API shape (worth mirroring)

`POST /pathfinding/` →

```jsonc
// request
{
  "verbose": true,
  "robot":   { "direction": "NORTH",
               "south_west": {"x": 0, "y": 0},
               "north_east": {"x": 29, "y": 29} },
  "obstacles": [
    { "image_id": 11, "direction": "SOUTH",
      "south_west": {"x": 50, "y": 90}, "north_east": {"x": 59, "y": 99} }
  ]
}

// response
{
  "segments": [
    { "image_id": 11,
      "cost": 142,
      "instructions": [
        {"move": "FORWARD", "amount": 40},
        "FORWARD_LEFT",
        {"move": "FORWARD", "amount": 15},
        "CAPTURE_IMAGE"
      ],
      "path": [ {"direction": "NORTH", "x": 15, "y": 15} ]
    }
  ]
}
```

One segment per obstacle; `cost` and `path` only when `verbose`. `CAPTURE_IMAGE` terminates each
segment. Consecutive same-direction moves are merged into a single instruction with a centimetre
amount.

### 8.2 What to adopt

- **Goal-pose *sets* per obstacle** (standoff band × lateral tolerance) rather than one exact pose.
- **Multi-goal single search** so nearest-next-obstacle emerges from the frontier.
- **Obstacle inflation precomputed into the grid** at world construction, so the search treats the
  robot as a point.
- **Measured, per-direction turning radii.**
- **Instruction compression** into `{move, amount_cm}` plus turn tokens — a clean STM-facing protocol.
- **Request replay capture**: dump every incoming planning request to a timestamped JSON file. Being
  able to replay the exact arena that failed at 2am is worth more than it costs.
- **ASCII grid dump** of the planned path to a text file for fast eyeballing.
- **OpenAPI contract** between RPi and the algorithm service, with a generated client for the
  simulator.

### 8.3 What to do differently

| Their choice | Problem | Our approach |
|---|---|---|
| Grid search *instead of* Dubins | Fine, and it handles reversing — but the assessed quiz covers Dubins | Implement grid search for the robot; still implement and document Dubins for the quiz and report |
| Greedy nearest ordering only | Can be materially worse than optimal | Precompute leg-cost matrix, then exhaustive/2-opt over orderings |
| Heuristic written but never wired in — effectively Dijkstra | Slower than necessary | Wire a real admissible heuristic, or accept Dijkstra knowingly and measure |
| Hardcoded server IP and port in `app.py` | Breaks on every network change | Config/env vars |
| `image_id` asserted `< 36`, world size hardcoded `200` | Won't accept IDs 36–40 (arrows, stop) | Support the full 11–40 image range, and accept 1–40 on the `image_id` field because it carries the tablet's obstacle number (1–8) |
| Fixed 5 obstacles assumed throughout | Our arena has 4–8 | Parameterise `N` |
| Vision trained on their lab floor | Our evaluation arena is background-agnostic and may be anywhere on campus | Augment aggressively across backgrounds/lighting |

### 8.4 Known defects in that reference (do not reproduce)

- `pathfinding/search/turn.py`: `__curve` is declared with 5 parameters but all 16 call sites pass 6,
  and the body references an undefined name `end`. **The code on their master branch does not run.**
  If porting, restore the `end: Vector` parameter.
- `pathfinding/search/turn.py`, the `(EAST, BACKWARD_RIGHT)` case: the robot-extent term is on the
  circle centre instead of the end pose, so that arc is collision-checked 12 cm off and the
  post-turn pose is wrong by 12 cm. The other 15 cases are consistent. Fixed in ours as Fix 6.
- `pathfinding/world/objective.py`: `offset += 2` sits *inside* the gap loop, so for boundary
  obstacles the lateral tolerance accumulates across iterations rather than being applied once.
- `pathfinding/search/segment.py`: `__heuristic` is defined but never called.
- `RPi/Communication/stm.py:9`:
  `sys.path.insert(1, "/home/raspberrypi/Desktop/MDP Group 14 Repo/SC2079/RPi")` — an absolute path
  hardcoded to their Pi's username *and* their folder name, which itself contains spaces. Import
  resolution must never depend on where the repository happens to be cloned.

### 8.5 Their RPi ⇄ STM wire protocol (reference)

Extracted from `RPi/Communication/stm.py`, `RPi/task1_rpi.py` and `RPi/task2_rpi.py`. Recorded here
because it is evidence of a protocol that actually drove a robot — **not** because we should adopt
it unchanged. Per §2.2, ours gets written to `/docs/protocols/` before either side is coded.

Serial link: `/dev/ttyUSB0` @ **115200** baud, UTF-8, newline-terminated
(`RPi/Communication/configuration.py`).

**RPi → STM** (`stm.py:53–59`):

```
<flag>[<speed>|<angle>|<val>]\n
```

Flags `S`, `D` and `M` are sent **bare**; every other flag carries the `speed|angle|val` suffix,
with angle and val rounded to 2 dp.

| Flag | Meaning | `val` |
|---|---|---|
| `T` / `t` | Drive forward / backward | distance in cm, or `90` for a turn |
| `W` / `w` | Drive forward / backward **until a sensor threshold is met** | the threshold |
| `S` | Stop — halt before image capture | — |
| `D` | Distance-tracking marker (semantics inferred — confirm against `robot/`) | — |
| `M` | Marker (semantics inferred — confirm against `robot/`) | — |

**Angle sign: negative = left, positive = right.** A turn is `angle = ±drive_angle`, `val = 90`; a
straight move is `angle = 0`, `val = distance`. Observed constants: `drive_angle = 25`;
`drive_speed` 40 outdoor / 55 indoor (Task 1) and 35–80 (Task 2) — *their* numbers, not ours (§9.2
rule 8).

**STM → RPi:**

| Message | Meaning |
|---|---|
| `fS` | Finished stopping; capture may begin |
| `f<cmd><speed>\|<angle>\|<distance>` | Command completed, echoing what ran |

Note the design worth keeping: every command is acknowledged, and the RPi blocks on `fS` before
capturing. The single-character flags and the `|`-delimited string are *not* worth keeping — a
JSON-line or length-prefixed frame is far easier to debug, log and version (§2.2).

---

## 9. Repository conventions for the agent

### 9.1 Layout: what exists vs. what we build

The repository already contains Pante's tree (§8). We do not edit it. Our subsystems go in new
directories beside it.

| Theirs (reference, read-only) | Ours (build here) | Notes |
|---|---|---|
| `service/` | `algorithm/` | Flask pathfinding service. Read for API shape (§8.1) |
| `simulator-client/` | `simulator/` | Visualisation (§7.9) |
| `openapi-simulator-client/` | — | Generated client — never hand-edit |
| `RPi/` | `rpi/` | Bluetooth, serial, orchestration |
| `image rec/` | `image-rec/` | ⚠️ Their directory name **contains a space** |
| `robot/` | `stm/` | STM32 firmware |
| `android/` | `android/` *(new module)* | Do not modify their app in place |
| `music/`, `yolov5/` | — | Leave alone |
| — | `docs/` | Protocols, calibration records, checklist evidence |

Two traps in their tree:

- **`image rec/` has a space in it.** Always quote it: `cd "image rec"`. Ours is `image-rec/` with a
  hyphen — never create a new path containing a space.
- **`yolov5/` is an empty, uninitialised submodule** pointing at `ultralytics/yolov5`
  (`.gitmodules`). Run `git submodule update --init` before any image-rec work or it stays empty.

### 9.2 Rules

1. **Never hardcode a physical constant inline.** Turning radii, robot footprint, standoff distance,
   arena size, obstacle count, camera offsets — all live in one config module per subsystem, and are
   documented in `/docs/calibration.md` with the date and conditions they were measured under.
2. **Never assume 5 obstacles or a 15-image set.** `4 ≤ N ≤ 8`, image IDs 11–40 — but the
   `image_id` request field accepts 1–40, because it carries the tablet's obstacle number (1–8).
3. **Never assume a fixed background or lighting.** The evaluation arena can be drawn anywhere.
4. **Every subsystem must be runnable and demonstrable standalone**, because that is how the
   checklist is graded.
5. **Log everything, and persist it.** Raw frames, planning requests, serial traffic. Two of the
   graded artifacts (stitched verification image, video) depend on captured evidence.
6. **Write the protocol down before implementing either side of it.** `/docs/protocols/`.
7. **Attribute work.** Checklist items require contributor names, and peer review scores depend on a
   demonstrable contribution record. Commit under your own identity.
8. **Prefer measured numbers to briefing numbers** where they conflict, and record the measurement.
9. **Never edit Pante's directories** (§9.1, left column). Read them, lift the ideas, write our
   version in our tree. If something of theirs must change to be usable, that is the signal to
   rewrite it in ours — not to patch theirs.

### 9.3 Definition of done for a run-critical feature

- Works standalone, from a documented command.
- Has a recorded successful demonstration (video or log) for checklist/report evidence.
- Its physical constants are in config, with calibration date noted.
- Its failure mode is defined — what the robot does when this component returns nothing or garbage.

---

## 10. Open items to confirm with supervisors

- Exact obstacle count range for our semester's Task 1 evaluation (briefing says 4–8; confirm).
- Whether the retry rule is one retry total across both tasks (briefing says combined) for our cohort.
- Whether the stitched verification image may be displayed on PC or must be on Android.
- Exact carpark dimensions and starting orientation for Task 2.
- Whether image IDs outside the 11–40 table can appear.
- **Which standoff distance is authoritative** — the ~20 cm camera optimum (§3.1), the 25–30 cm
  planning band (§7.5), or §7.2's two mutually inconsistent formulas. See the note in §3.1.
- Semantics of the reference firmware's bare `D` and `M` serial flags (§8.5), if we reuse any part
  of their STM firmware in `robot/`.
