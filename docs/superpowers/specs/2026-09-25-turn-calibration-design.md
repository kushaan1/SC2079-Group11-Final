# Turn calibration and per-move poses — design

Date: 2026-09-25. Branch: `kejun-experimental-algo`, in place (the algo owner's call; the
handover asked for a new branch, he declined). Source: Shuen Wei's handover from the RPi/Android
side, plus the decisions taken with Kejun in the session that produced this document.

## 1. The problem

`turn.py` models a turn as the robot pivoting about a point `lead = south_length - 3 = 12` cm
behind its centre: that rear point rides a circle of radius R, and the centre is carried 12 cm
ahead of it. After a 90 the centre has therefore moved `R + 12` sideways and `R - 12` forward
(forward turns) or `R - 12` sideways and `R + 12` backward (backward turns).

`config.TURN_RADIUS_CM` and `config.TURN_45_DISPLACEMENT_CM` were tape measurements of the
**straight-line distance between the centre marks** before and after one command, read into the
model as R for a 90 and as `R * sin(45)` for a 45. A chord is `2 * sqrt(R^2 + L^2) * sin(theta / 2)`, not R, so every planned 90 ended
20–27 cm past the real car and every 45 about 4 cm past. Measured before this change, start
(100, 100) facing north, empty arena:

| command | planner centre delta | planner chord | measured chord | overshoot |
|---|---|---|---|---|
| FORWARD_LEFT | (-53, 29) | 60.4 | 40.5 | 20 |
| FORWARD_RIGHT | (72, 48) | 86.5 | 60.0 | 27 |
| BACKWARD_LEFT | (-28, -52) | 59.1 | 39.6 | 20 |
| BACKWARD_RIGHT | (44, -68) | 81.0 | 56.0 | 25 |
| FORWARD_LEFT_45 | (-17, 18) | 24.8 | 21.0 | 4 |
| FORWARD_RIGHT_45 | (22, 28) | 35.6 | 32.0 | 4 |
| BACKWARD_LEFT_45 | (-1, -28) | 28.0 | 24.0 | 4 |
| BACKWARD_RIGHT_45 | (6, -37) | 37.5 | 34.0 | 4 |

One number per command cannot fix this: the model has two parameters per command (R and L) and
a chord pins only `sqrt(R^2 + L^2)`.

## 2. The measurements (authoritative)

Taken 2026-09-25 by Kejun on our chassis at the competition speed setting, centre of the car
marked on the floor before and after one command, same mark both sessions, final heading
checked to be 90 / 45. One run each.

Axis convention, confirmed: **x is perpendicular to the start heading, y is along it.** Every
command moved toward the side the wheels were turned (BL 45 went left, BR 45 went right).

| command | across (toward steering side) | along start heading |
|---|---|---|
| TL 90 = FORWARD_LEFT | 37.0 | +15.5 |
| TR 90 = FORWARD_RIGHT | 47.0 | +28.0 |
| BL 90 = BACKWARD_LEFT | 21.5 | -41.0 |
| BR 90 = BACKWARD_RIGHT | 33.0 | -47.0 |
| TL 45 = FORWARD_LEFT_45 | 18.5 | +18.0 |
| TR 45 = FORWARD_RIGHT_45 | 21.0 | +22.0 |
| BL 45 = BACKWARD_LEFT_45 | 4.5 | -25.0 |
| BR 45 = BACKWARD_RIGHT_45 | 6.5 | -31.8 |

Earlier-session chords for cross-checking: TR90 60, TL90 40.5, BR90 56, BL90 39.6, TR45 32,
TL45 21, BR45 34, BL45 24. The pairs above reproduce five of them within 2 cm and three (TR90,
BL90, TL45) within 5–7 cm. That gap is run-to-run scatter of the car, not a model error, and
it is the floor on how exact any plan can be.

## 3. The model

A car at fixed steering lock rotates about one point on its rear-axle line (Ackermann). Per
command, with `theta` the commanded angle, `s = sin(theta)`, `c = 1 - cos(theta)`:

```
forward:   across = R*c + L*s        along  = R*s - L*c
backward:  across = R*c - L*s        -along = R*s + L*c
```

Two equations, two unknowns, solved per command (`det = s^2 + c^2`):

```
forward:   R = (across*c + along*s) / det      L = (across*s - along*c) / det
backward:  b = -along
           R = (across*c + b*s) / det          L = (b*c - across*s) / det
```

Fitted from the table above:

| command | R (cm) | L (cm) |
|---|---|---|
| FORWARD_LEFT | 26.3 | 10.8 |
| FORWARD_RIGHT | 37.5 | 9.5 |
| BACKWARD_LEFT | 31.3 | 9.8 |
| BACKWARD_RIGHT | 40.0 | 7.0 |
| FORWARD_LEFT_45 | 31.0 | 13.3 |
| FORWARD_RIGHT_45 | 37.1 | 14.3 |
| BACKWARD_LEFT_45 | 32.4 | 7.1 |
| BACKWARD_RIGHT_45 | 41.6 | 8.1 |

L is a property of the chassis and comes out 7–14 cm on all eight, mean about 10, against the
12 the planner assumed. That is the evidence the rear-pivot circle is the right idealisation;
the scatter in L is tape noise amplified on the 45s plus the steering transient. **Each command
keeps its own (R, L)**: that is what makes the end pose exact per command, and it absorbs
whatever the transient is. A 45 is NOT derived from a 90 or vice versa.

### What the planner does with it

- **End pose**: the measured `(across, along)` rotated into the start heading and rounded to the
  cm. Not read off the circle. The fit makes the two agree analytically; pinning to the tape
  means no rounding inside the arc can move where the car is planned to stop.
- **Rear-point arc** (the collision-checked cells): the circle of radius R about the
  instantaneous centre of rotation (ICR), sampled at half-cell steps and de-duplicated, from the
  start rear point through `theta`. Same form as today: rear arc checked, end pose appended and
  not checked. **The collision check is not made stricter or looser** (Kejun, 2026-09-25).
- **Centre arc** (new, for item 2): the circle of radius `sqrt(R^2 + L^2)` about the same ICR,
  sampled so consecutive points are at most `CENTRE_PATH_SPACING_CM` (5) apart, last point
  pinned to the exact end.
- **Arc length / distance cost**: `R * theta` on the rear point, as today.
- **Pivots** (off by default) alternate two locks; each stroke uses its lock's fitted R, and the
  whole pivot uses the mean of the two locks' L, because the centre is one physical point.
- **Cache keys** hold the `(across, along)` pair, not the robot extents: the pivot point is
  measured, so the arc no longer depends on the planning footprint.

## 4. Config

Replace `TURN_RADIUS_CM`, `TURN_45_DISPLACEMENT_CM` and `TURN_PIVOT_OFFSET_CM` with one table
of the raw tape pairs, `TURN_DISPLACEMENT_CM`, keyed by the full `TurnInstruction` value, with
the axis convention and the session recorded beside it. Add `CENTRE_PATH_SPACING_CM = 5`.

Other values Kejun set on 2026-09-25 (they change `end` values, not the response shape):

| constant | value | why |
|---|---|---|
| `STANDOFF_MIN_CM` | 12 | camera 15–40 cm from the face; camera-to-face = standoff + 3.5 with the lens ~11.5 cm ahead of the centre mark (assumed at the plate's front edge) |
| `STANDOFF_MAX_CM` | 36 | inclusive; the old comment saying "exclusive" was wrong |
| `LATERAL_TOLERANCE_CM` | 5 | |
| `ROBOT_SPEED_CM_S` | 25 | what origin holds; still not timed |
| `SERVER_PORT` | 5000 | matches the RPi's env.example |

## 5. Item 2: poses and centre_path (additive response fields, verbose only)

From the handover, unchanged:

- `poses`: one entry per entry of `instructions`, same order and length; the robot CENTRE after
  that instruction completes, `{"direction": <any of 8>, "x": <cm>, "y": <cm>}`; the entry for
  `CAPTURE_IMAGE` equals `end` whenever `end` is set; in a segment where the car does not move,
  `end` is null as before and the single pose is where it already stands. **Empty list when
  `verbose` is false** (today it is always sent; that changes).
- `centre_path`: the robot CENTRE in driving order through the whole segment, including inside
  turns, `[{"x": <cm>, "y": <cm>}, ...]`. Starts at the segment's start pose, passes through
  every entry of `poses` (each one is literally a point of it), points at most 5 cm apart along
  turns, straights as their two ends. Integers, cm. Empty when `verbose` is false and in stub
  mode. `path` is left exactly as it is.

Everything else in the response keeps its name and meaning: `obstacle_id`, `instructions`,
`end`, `seconds`, `cost`, `path`, `unreachable`. The request is untouched. The response with
`verbose: false` is byte-for-byte what it is today except that `poses` becomes `[]` and
`centre_path` is sent as `[]`.

## 6. Don'ts

- No change to the collision geometry beyond re-parameterising it (no extra checked cells).
- No renames, no change to the verbose-false response beyond `poses: []`.
- Nothing outside `algorithm/` except this spec and its plan. `docs/protocols/openapi.json`
  is generated from the controller and is left for Kejun to regenerate.
- **No commits.** Kejun's commits are GPG-signed and he commits by hand. Stage only.

## 7. Cross-check against the algorithms briefing (`docs/algarithms_briefing_25S2.pdf`)

Checked 2026-09-25. Nothing in the deck contradicts §3-§5; these are the points of contact.

- **Turning radius.** Slide 4: "a turning radius of about 25 cm but a larger radius if the robot
  moves faster"; slide 27: "the actual value you should use for r should be decided when you
  experiment with your robot." The fitted left-lock radii are 26.3 (FL) and 31.3 (BL) cm, right
  on the nominal; the right lock is 37.5-41.6 cm, which is this car's asymmetry. Under the old
  reading the "radii" were 41-60 cm, well outside the deck's figure. The fit is the
  experiment the deck asks for.
- **The motion model.** Slide 17 moves a point `(x, y)` by `delta` along its heading and turns
  the heading by `delta / r`: a point whose velocity is tangent to its path. On a car that point
  is the rear axle, not the centre - the centre also moves sideways at `L * omega`. The measured
  asymmetry (forward turns move the centre more across than along, backward turns the reverse)
  is exactly the deck's model applied at the rear axle with the centre `L` ahead of it, which is
  what §3 implements. Worth knowing for the quiz: the deck's `(x, y)` is the rear axle.
- **Standoff.** Slide 4 says the camera is best 20 cm from the obstacle. Slide 8 (option 1)
  targets the 30 cm robot's bottom-left at `(a-10, b-45)` for an image at `(a, b, S)`: the
  planning box's leading edge 15 cm from the face, centre 30 cm, camera about 18.5 cm if the
  lens is 11.5 cm ahead of the centre. Slide 10 (option 2, 10 cm cells) targets `(a-1, b-5)`:
  leading edge 20 cm, camera about 23.5 cm. So the deck's optimum is `STANDOFF` 15-20 in this
  config's units, camera 18-24 cm, and the two options agree once the 30 cm footprint is
  accounted for (this closes the "three inconsistent standoffs" item in AGENTS.md §3.1). The
  chosen band 12..36 contains it. **Caveat**: the planner takes the cheapest goal pose in the
  band, which is often the far end, so with 12..36 the car will frequently stop with the camera
  near 39 cm rather than near 20. If CV's sweet spot really is 20, narrow the top of the band
  (e.g. 12..22, camera 15.5-25.5 cm). Kejun's call; one config edit.
- **Lateral alignment.** Slides 8 and 10: "the centre of the robot does not have to be aligned
  exactly with the centre of the image." `LATERAL_TOLERANCE_CM = 5` is that allowance.
- **Clearance.** Slides 34-36: a straight path needs 30 cm between obstacles or to the
  boundary; treat the robot as a dot and inflate each obstacle to 40 x 40 (15 cm per side for
  a 30 cm robot). This planner inflates by 15 + `OBSTACLE_CLEARANCE_CM` (6) = 21 per side, a
  52 x 52 virtual obstacle, which is why arenas at the legal 30 cm spacing come back
  unreachable (README limitation 1). Out of scope here and unchanged by Kejun's instruction;
  with exact turn geometry the 6 cm margin is the next thing worth revisiting.
- **After recognition, reverse first** (slide 33); **nearest by true path cost, not Euclidean**
  (slides 41-42); **exhaustive search over the visiting order** (slide 16); **the simulator's
  four requirements** (slide 40): all already how the planner works, none touched by this plan.
- **Five obstacles, 15 images** (slides 3, 5): superseded by the general briefing's 4-8 and
  30; the planner is parameterised for both already.
- **Dubins paths** (slides 18-32): quiz material, not implemented, not part of this plan.

## 8. Report back (to Shuen Wei)

- Measured vs modelled displacement for all 8 commands, before (the table in §1) and after.
- What changed and why.
- A sample verbose response for `testdata/02-four-obstacles.json` showing `poses` and
  `centre_path`, saved under `algorithm/testdata/responses/`.
