# Algorithm → RPi handover: measured turn model and per-move poses

For Shuen Wei, from the algorithms side. Written 2026-09-25 against `kejun-experimental-algo`
(the commit after `fddbd3c`). This answers your handover of the same date: item 1 (turns do not
reproduce the calibration) and item 2 (report the centre after every move).

Everything the planner sends you is unchanged in name and meaning. Two fields were added, both
only when `verbose` is true. Once you have them, the RPi can delete its turn radii and its dead
reckoning.

---

## 1. What changed in the planner

**Your finding was right, and the real error was bigger than 17 cm.** The two old tables
(`TURN_RADIUS_CM`, `TURN_45_DISPLACEMENT_CM`) held the tape-measured straight-line distance
between the centre marks before and after a command, and the planner read that chord as a
radius while also pivoting 12 cm behind the centre. Every planned 90 ended 20-27 cm past the
real car; every 45 about 4 cm past.

Kejun re-measured all eight commands as the centre's displacement across and along its start
heading. The planner now solves each pair for that command's own rear-pivot radius and lead,
and pins the end pose of the turn to the measurement. Planned end pose versus the tape, from
north at (100, 100):

| command | tape (x, y) | before | gap | after | gap |
|---|---|---|---|---|---|
| FORWARD_LEFT | (-37.0, +15.5) | (-53, +29) | 20.9 cm | (-37, +16) | 0.5 cm |
| FORWARD_RIGHT | (+47.0, +28.0) | (+72, +48) | 32.0 cm | (+47, +28) | 0.0 cm |
| BACKWARD_LEFT | (-21.5, -41.0) | (-28, -52) | 12.8 cm | (-22, -41) | 0.5 cm |
| BACKWARD_RIGHT | (+33.0, -47.0) | (+44, -68) | 23.7 cm | (+33, -47) | 0.0 cm |
| FORWARD_LEFT_45 | (-18.5, +18.0) | (-17, +18) | 1.5 cm | (-19, +18) | 0.5 cm |
| FORWARD_RIGHT_45 | (+21.0, +22.0) | (+22, +28) | 6.1 cm | (+21, +22) | 0.0 cm |
| BACKWARD_LEFT_45 | (-4.5, -25.0) | (-1, -28) | 4.6 cm | (-5, -25) | 0.5 cm |
| BACKWARD_RIGHT_45 | (+6.5, -31.8) | (+6, -37) | 5.2 cm | (+7, -32) | 0.5 cm |

The 0.5 cm is integer rounding. The same holds from all eight headings (pinned by
`algorithm/tests/test_turn_calibration.py`). What no model removes is the car's own scatter:
two of the 90s moved 5-7 cm between Kejun's two measuring sessions.

Fitted numbers, for your interest only (you no longer need them): rear-pivot radius 26 / 37.5 /
31 / 40 cm (FL / FR / BL / BR), lead 7-14 cm behind the centre. The single table
`config.TURN_DISPLACEMENT_CM` in `algorithm/config.py` is now the only place the calibration
lives.

Other constants Kejun set the same day: standoff band 12-36 cm from the planning box's leading
edge (camera 15.5-39.5 cm from the face, assuming the lens is 11.5 cm ahead of the centre
mark), lateral tolerance ±5 cm, time-model speed 25 cm/s, port 5000.

## 2. What you can delete on the RPi

- `rpi/config.py` `_radii()` / `TURN_RADIUS_CM` and the `RPI_TURN_RADIUS_*` environment
  variables.
- `rpi/pose.py` dead reckoning (`advance`). Report `poses` to the tablet instead.
- The snap-to-`end` at the end of each segment. `poses[-1]` is `end`.

Draw the tablet's route from `centre_path`, not from `path`. `path` is the collision check's
cells, which inside every turn are the rear pivot's, 7-14 cm behind the car.

## 3. The two new fields

Both are present only when the request has `"verbose": true` (you always send that). With
`verbose: false` both are `[]` and nothing else in the response differs from before. Both are
`[]` in stub mode.

### `segments[].poses`

One entry per entry of `instructions`, same order, same length. Each is the robot CENTRE after
that instruction completes, in the same shape as `end`:

```json
{"direction": "NORTHEAST", "x": 36, "y": 52}
```

- `x`, `y` in centimetres, integers, arena origin bottom-left, exactly like `end`.
- `direction` is any of the EIGHT headings: `NORTH`, `NORTHEAST`, `EAST`, `SOUTHEAST`,
  `SOUTH`, `SOUTHWEST`, `WEST`, `NORTHWEST`. After a `_45` turn the car is on a diagonal.
  Degrees clockwise from north: N 0, NE 45, E 90, SE 135, S 180, SW 225, W 270, NW 315.
  **Check your decoder maps all eight** - `end` only ever carries the four cardinals, so a
  four-way map that worked for `end` will raise on `poses`.
- The entry for `CAPTURE_IMAGE` repeats the pose before it, so `poses[-1] == end` whenever
  `end` is set.
- A straight that the planner split for `MAX_STRAIGHT_CM` (two `FORWARD`s in a row) has one
  pose per piece, interpolated on the line.

### `segments[].centre_path`

The robot centre in driving order through the whole segment, including inside every turn:

```json
[{"x": 15, "y": 15}, {"x": 15, "y": 30}, {"x": 16, "y": 33}, {"x": 18, "y": 36}, ...]
```

- Integers, centimetres.
- Starts at the segment's start pose (the previous segment's `end`, or the request's `robot`
  for the first segment) and ends at `end`.
- Every entry of `poses` is literally one of its points, in order, so "which point is the car
  at after instruction k" is a lookup, not a nearest-point search.
- Along a turn, consecutive points are at most 5 cm apart (measured worst case 4.24 cm).
  Straights may be just their two ends. No consecutive duplicates.

### Worked example

First segment of the shipped sample (`algorithm/testdata/responses/02-four-obstacles.verbose.json`),
from the start pose (15, 15) facing north:

| instruction | pose after |
|---|---|
| `FORWARD 15` | NORTH (15, 30) |
| `FORWARD_RIGHT_45` | NORTHEAST (36, 52) |
| `FORWARD 7` | NORTHEAST (41, 57) |
| `FORWARD_RIGHT_45` | EAST (71, 58) |
| `CAPTURE_IMAGE` | EAST (71, 58) = `end` |

`centre_path` for that segment has 21 points: (15,15), (15,30), then nine points through the
first arc to (36,52), then (41,57), then eight points through the second arc to (71,58).

## 4. What did not change

`obstacle_id`, `instructions` (including the `_45` tokens), `end`, `seconds`, `cost`, `path`,
`unreachable`, the request shape, the `X-MDP-Stub` header, port 5000, and every 422 shape. Your
`planner_client.py` and `arena.py` keep working as they are; only `pose.py` becomes redundant.

## 5. Edge cases and gotchas

1. **`end` is `null` in a segment where the car does not move** (it was already standing on a
   goal pose for the next obstacle, e.g. a mid-run re-plan from a shared pose). That was
   always so. In that segment `instructions == ["CAPTURE_IMAGE"]`, `poses` has one entry (where
   the car stands) and `centre_path` that one point. Take the position from `poses`, not
   `end`, and you need no special case.
2. **Diagonal straight amounts are not multiples of 5.** A straight driven on a diagonal
   heading is reported as ground distance: 5 cells = 7 cm, 10 = 14, 15 = 21, 25 = 35. The
   shipped sample contains `FORWARD 7`, `14` and `35`. Your STM handover says `FS`/`BS` take
   5-200 in steps of 5 and reply `ERR,RANGE` outside that. **Confirm what the firmware does
   with `FS 7`.** If it must be a multiple of 5, say so and the planner will snap - do not
   round on the Pi, because `poses` would then disagree with the car. This has been true since
   the eight headings went live on 2026-09-18, so it may already be handled.
3. **Where the car stops is further from the face than your spec says.** Your Task 1 spec (P2)
   says `end` is 25-30 cm from the face. With the new band the centre is 27-51 cm from the face
   and the camera 15.5-39.5 cm. The planner takes the cheapest pose in the band, which is often
   the far end, so expect the camera near 39 cm more often than near 20. If CV wants it
   closer, Kejun lowers `STANDOFF_MAX_CM`; the ultrasonic nudge before capture that you
   proposed to the STM side would also cover it.
4. **The car may be up to about 10 cm off the image centre** (lateral tolerance ±5 cm beyond
   the face's edges). Also unchanged in kind, only the number moved from 10 to 5.
5. **`seconds` is now priced at 25 cm/s.** It is still a route-ranking estimate, not a clock.
   Your `RPI_STM_STRAIGHT_CM_PER_S` deadline is a separate number and is unaffected.
6. **The JSON key order changed** (`centre_path` sorts first). Nothing should depend on it.

## 6. How to test against it

- Parse the shipped sample first, offline:
  `algorithm/testdata/responses/02-four-obstacles.verbose.json` (four segments, all four
  turn kinds, diagonal headings, split straights absent - the cap is 100 cm and no straight
  reaches it there).
- Then the live service, from `algorithm/`: `./.venv/bin/python app.py`, and POST
  `testdata/02-four-obstacles.json` with `"verbose": true` (the file says `false`; flip it).
  `docs/rpi-test-algo-server.md` still describes the two-part laptop/RPi check and is current
  apart from not mentioning the new fields.
- The regenerated `docs/protocols/openapi.json` and the protocol doc paragraph for the two
  fields are Kejun's next commit. The served schema at `/openapi/openapi.json` is already
  correct if you generate a client from the running service.

## 7. What I would like from you

1. The `FS 7` / `FS 14` question above (item 2 in §5).
2. Confirm your decoder accepts the eight `direction` values in `poses`.
3. Once `poses` drives the tablet marker, tell us how far the drawn car ends up from the real
   one after a segment. That number is the planner's scatter floor now, and it is the one that
   decides whether the standoff band can be narrowed.
4. If you want `poses` and `centre_path` in `verbose: false` responses as well, say so; it is a
   one-line change. They are verbose-only because your handover asked for that.

## 8. Where the details are

- `algorithm/PROVENANCE.md`, "The turn model is fitted per command" and "The response carries
  the centre after every instruction" - the reasoning and the numbers.
- `algorithm/README.md`, "Hit it with curl" and "Known limitations" 2-3.
- `algorithm/pathfinding_controller.py` module docstring, departures 8 and 9.
- `docs/superpowers/specs/2026-09-25-turn-calibration-design.md` - the measurements, the
  model, and a cross-check against the algorithms briefing.
- Tests: `algorithm/tests/test_turn_calibration.py` (every turn ends on the tape),
  `algorithm/tests/test_poses.py` (the two fields, in four-heading, eight-heading and
  eight-plus-pivots modes).
