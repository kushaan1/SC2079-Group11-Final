# RPi program — Task 1 and A.5 design

**Date:** 2026-09-17
**Status:** approved in discussion; awaiting written review
**Scope:** the Raspberry Pi's program: manual drive, the Task 1
run, and the A.5 face-search demo. Task 2 is a hook only.

This document is the authority for `rpi/`. Where it disagrees with the
conversation that produced it, this document wins.

---

## 1. What this is

The RPi is the coordinator between four things that already exist:

| Component | Owner | Talks over | Contract |
|---|---|---|---|
| Android tablet | this branch | Bluetooth SPP, `/dev/rfcomm0` | [`docs/protocol.md`](../../protocol.md) |
| STM32 | STM team | USB serial `/dev/ttyACM0`, 115200 | STM handover doc (§3.2 below restates the parts used) |
| Path planner | `origin/kejun-experimental-algo` → `algorithm/` | HTTP, laptop port 5000 | `docs/protocols/algorithm-service.md` on that branch |
| Image recognition | `origin/jerick-cv` → `image-rec/pc_server/` | HTTP, laptop port 4000 | `POST /detect`, `vision/contracts.py` on that branch |

Today's RPi code (`rpi/android_rpi_stm_bridge_quiet_v2.py`) relays every
tablet line to the STM and one reply back. This program replaces it. The
bridge's line framing, raw-mode rfcomm handling and reconnect loop survive as
modules; its single blocking loop does not.

**Originality.** Everything in `rpi/` is written from the four contracts
above. Another group's RPi code was read during design to understand their
approach to A.5 and to see a working STM vocabulary; nothing from it —
code, structure or naming — is copied. The two `image-rec/rpi/` adapters on
the CV branch are not reused either: they speak JSON protocols that neither
the tablet nor the STM implement.

---

## 2. Scope

### In v1

1. **Manual drive** — the tablet's seven movement tokens go to the STM.
2. **No arena state.** Every run start carries the whole layout *and* the
   robot's pose, so the RPi keeps nothing between messages. `ADD`, `SUB`,
   `FACE`, `MOVEROBOT` and SEND ARENA are logged and otherwise ignored.
3. **Task 1** — on the tablet's image-rec start: plan, drive, photograph, report.
4. **A.5 face search** — on a separate tablet trigger: drive to the declared
   face, and if the camera sees the bullseye marker, go round the obstacle face
   by face until an image is found.
5. **Fakes** for the STM and the camera, so everything above the two hardware
   links runs and is tested on a laptop.

### Not in v1 (all additive later)

- Task 2. `beginFastest` is forwarded to the STM as a bare token and nothing else.
- A `picamera2` backend. The Pi runs **Raspberry Pi OS Buster (v10)**, so the
  legacy `picamera` stack is the real one.
- Position correction from the CV bounding box.
- A hard-coded A.5 manoeuvre. A.5 uses the planner (§6.3).

---

## 3. Environment and contracts

### 3.1 Runtime

- Raspberry Pi OS **Buster**, CPython **3.7**. Code must be 3.7-compatible:
  no walrus, no `match`, no PEP 585 generics, `typing.Optional`/`List` style.
- Dependencies: `pyserial`, `requests`. On the Pi only: `picamera` (apt,
  `python3-picamera`), so the venv is created with `--system-site-packages`.
- Bluetooth: an SPP record and `rfcomm watch /dev/rfcomm0 <channel>` running
  outside this program (a shell script or systemd unit). `watch` re-listens
  after a disconnect; `listen` does not, which is why the bridge had to be
  restarted by hand.
- The planner and the image server run on a laptop on the same WiFi. The RPi
  needs two URLs.

### 3.2 STM contract — the parts this program uses

From the STM handover doc. Plain text, `\n`-terminated, one reply line per
command. Max 31 bytes per line.

| RPi sends | STM replies | Notes |
|---|---|---|
| `PING` | `PONG` | link check and resync |
| `F` / `B` | `ACK,F` / `ACK,B` | 500 ms jog; replies on receipt; queues if busy |
| `S` | `ACK,S` | stops anything in progress; accepted any time |
| `FW <cm>` | `ACK,FW` or `ERR,…` | encoder closed-loop straight |
| `BW <cm>` | `ACK,BW` or `ERR,…` | **not in the handover doc — requested** |
| `TL <deg>` `TR <deg>` `BL <deg>` `BR <deg>` | `ACK,TL` … or `ERR,…` | gyro-timed arcs, 45–360 |
| `MA <pct>` `MB <pct>` `AS <n>` | `ACK,…` | motor trim and steering lock, not persisted across reboot |

Errors: `ERR,RANGE`, `ERR,GYRO`, `ERR,TIMEOUT`, `ERR,UNKNOWN`. Measured
commands sent while the STM is busy are **silently dropped** (their known
issue), so the driver never sends one until the previous has replied.

**Open with the STM team** — the program is written assuming the answers in
bold, and `stm_driver.py` is the only file that changes if they differ:

| # | Question | Assumed |
|---|---|---|
| S1 | `BW <cm>` exists | **yes** — Task 1 cannot run without it: every segment after the first starts with a reverse |
| S2 | `FW` range | **1–200** (handover says 80–120, which is the A.3 test range) |
| S3 | `ACK,FW` / `ACK,TL` timing | **on completion** of the motion (implied by `ERR,TIMEOUT`) |
| S4 | After `S` interrupts a move, does the interrupted move also reply? | **unknown** — the driver drains and resyncs after every stop, so either answer works |

### 3.3 Planner contract — the parts used

`POST {PLANNER_URL}/pathfinding/`, JSON. Request: `robot` (heading as
`NORTH`/`EAST`/`SOUTH`/`WEST`, footprint as inclusive cm corners), `obstacles`
(each `image_id` 1–40 unique, `direction` = the image face, cm corners),
optional `strategy` (`optimal` default, or `greedy`). Response: `segments`
in visit order, each with `image_id`, `instructions`, `path`; and
`unreachable`. Instructions are `{"move":"FORWARD"|"BACKWARD","amount":<cm>}`,
the four arc tokens `FORWARD_LEFT` … `BACKWARD_RIGHT` (plus `_45` variants when
the planner's diagonal mode is on), and `CAPTURE_IMAGE`, which ends every
segment. 422 on a bad request.

**Verified from the planner's code** (branch `kejun-experimental-algo`):

| # | Fact | Where |
|---|---|---|
| P1 | Any `robot` pose inside the grid, with any subset of obstacles (≥ 1), is a valid request. Nothing assumes the start zone or the full layout. | `pathfinding_controller.py` `_construct_world` |
| P2 | `segments[].path[-1]` is the robot's **centre** in cm, facing the obstacle, 25–30 cm from its face. Straights include their endpoint; turns append the post-turn centre pose last. | `search/search.py` `Segment.compress`, `search/straight.py`, `search/turn.py`, `config.STANDOFF_*_CM` |
| — | The grid is 200 × 200 with a 1 cm cell; every corner must satisfy `0 ≤ v < 200`. A 30 cm robot is planned as a 31-cell footprint, so a centre above 184 cm on either axis is a 422. | `config.GRID_SIZE`, `world/world.py` `Robot.planned`, `World.__inside` |
| — | Straights are multiples of 5 cm. Turn radii are per direction and currently the prior year's: FL 39, FR 40, BL 37, BR 39. | `config.STRAIGHT_CHUNK_CELLS`, `config.TURN_RADIUS_CM` |

**Open with the algorithm owner:**

| # | Ask |
|---|---|
| P3 | Replace `TURN_RADIUS_CM` with values measured on this car at the STM's actual `AS` steering lock. Joint with the STM team. Needed for accuracy, not for this code. |

### 3.4 Image-recognition contract — the parts used

`POST {VISION_URL}/detect`, multipart: `image` (JPEG), `object_id` (string).
200 response: `status` ∈ `target` / `bullseye` / `no_detection` / `error`;
`detection` = the server's chosen card or `null`, with `competition_id`
(11–40) and `confidence`. Non-200: `{"error": "…"}`. Nothing is requested
from the CV owner.

### 3.5 Tablet contract — additions

Two changes to what the tablet sends, both on this branch, both to be added
to `protocol.md` §1.4. Nothing inbound changes.

**A `robot` object in the image-rec start.** `protocol.md` already offers
it ("the tablet knows it and can add a `robot` object if the planner wants
it"). The RPi wants it: with it, a run start is a complete snapshot and the
RPi needs no state from earlier messages.

```
{"command":"imageRec","algorithm":"greedy",
 "robot":{"x":1.0,"y":1.0,"heading":0.0},
 "obstacles":[{"id":1,"x":10,"y":6,"face":"N"}]}
```

`robot.x`/`y` are the same decimal cell indices `MOVEROBOT` uses (the
footprint's centre); `heading` is degrees clockwise from north. It is
whatever the tablet currently draws — the operator's last drag, or the last
`ROBOT` line the RPi sent.

**A new `faceSearch` message**, same shape, different `command`, no
`algorithm`:

```
{"command":"faceSearch",
 "robot":{"x":1.0,"y":1.0,"heading":0.0},
 "obstacles":[{"id":1,"x":10,"y":6,"face":"S"}]}
```

Sent from a new trigger on the tablet (a fourth option in the IMAGE REC
long-press picker, or a small button — UI choice deferred to the Android
work).

**Compatibility.** A start message without `robot` (an older tablet build)
is accepted with the start pose `(1.0, 1.0, 0°)` and a
`MSG,No robot pose in start - assuming start zone`.

The tablet's `algorithm` value `turnInPlace` is not a planner strategy; the
RPi maps it to `optimal` and says so with a `MSG`.

---

## 4. Architecture

### 4.1 Modules

```
rpi/
├── __main__.py         python3 -m rpi [--fake-stm] [--fake-camera]
├── main.py             wiring; logging; the Bluetooth loop
├── dispatcher.py       tablet message → action (the table in §4.3)
├── model.py            value types: Obstacle, Pose, instructions, Segment, Plan, Verdict
├── config.py           every constant, env-overridable (RPI_*)
├── bt_link.py          /dev/rfcomm0 raw mode, framing, locked send, reconnect
├── protocol.py         tablet line → Inbound message; MSG/TARGET/ROBOT builders
├── arena.py            obstacles, robot pose, cells ⇄ cm, faces ⇄ directions
├── stm_driver.py       StmDriver interface; SerialStmDriver; FakeStmDriver
├── planner_client.py   request build, POST, response parse → Plan
├── vision_client.py    POST /detect → Verdict
├── vision_worker.py    queue + thread; 3 frames per obstacle; results + waiting
├── camera.py           Camera interface; PiCameraLegacy; FakeCamera
├── pose.py             dead reckoning from instructions; ROBOT formatting
├── run.py              RunController; Task1Run; FaceSearchRun
└── tests/
```

Each module has one job, is importable without hardware, and depends only on
modules above it in this list plus `config`. `main.py` is the only module that
knows about all of them.

### 4.2 Threads

| Thread | Owns | Blocks on |
|---|---|---|
| main | `bt_link` read, dispatcher | `select` on the rfcomm fd |
| stm-reader | serial read → line queue | `serial.readline` |
| run | the active `Task1Run` or `FaceSearchRun` | `stm_driver.execute` |
| vision-worker | frame queue → HTTP → results | queue get, HTTP |

`bt_link.send()` takes a lock: the main thread and the run thread both write.
`stm_driver` serialises commands with a lock and exposes `stop()` which
bypasses it. At most one run exists at a time (`RunController`).

### 4.3 Dispatcher (main thread)

| Tablet line | Action | While a run is active |
|---|---|---|
| `f` `b` `tl` `tr` `sl` `sr` | `stm_driver.manual(token)` | refused: `MSG,Run in progress - STOP first` |
| `s` | `run_controller.stop()` if a run is active, else `stm_driver.manual("s")` | stops the run |
| `ADD` `SUB` `FACE` `MOVEROBOT` SEND ARENA | logged only — the run start carries everything | allowed |
| `{"command":"imageRec"}` | `run_controller.start(Task1Run(...))` | refused with `MSG` |
| `{"command":"faceSearch"}` | `run_controller.start(FaceSearchRun(...))` | refused with `MSG` |
| `beginFastest` | `stm_driver.manual_raw("beginFastest")` — passthrough, Task 2 hook | refused with `MSG` |
| anything else | logged, `MSG,Unknown command: <line>` | — |

---

## 5. Module specifications

### 5.1 `config.py`

All constants with `RPI_`-prefixed environment overrides, read once at
import. No other module reads the environment.

| Name | Default | Meaning |
|---|---|---|
| `BT_PORT` | `/dev/rfcomm0` | |
| `STM_PORT` / `STM_BAUD` | `/dev/ttyACM0` / `115200` | |
| `PLANNER_URL` | none — required | laptop, e.g. `http://192.168.1.20:5000`; a run start without it → `MSG,Planner error: Planner URL not configured` |
| `VISION_URL` | none — required | laptop, e.g. `http://192.168.1.20:4000`; captures without it → `MSG,Vision URL not configured`, once |
| `RETRY_DELAY_S` | `3` | wait before reopening a lost Bluetooth or serial device |
| `PLANNER_TIMEOUT_S` | `5` | |
| `VISION_TIMEOUT_S` | `10` | per frame |
| `VISION_DRAIN_TIMEOUT_S` | `15` | how long `MSG,Done` waits for outstanding verdicts |
| `STM_STRAIGHT_DEADLINE_S(cm)` | `cm / 10 + 5` | reply deadline for `FW`/`BW` |
| `STM_TURN_DEADLINE_S` | `10` | reply deadline for arcs |
| `STM_STOP_DRAIN_S` | `0.5` | how long to discard replies after `S` |
| `MANUAL_TURN_DEG` | `45` | angle used for the four manual arc buttons |
| `MOTOR_A_PCT` / `MOTOR_B_PCT` / `STEER_STEPS` | unset | pushed to the STM at startup when set; unset = keep the firmware's defaults |
| `STM_COMPLETION` | `ACK` | `ACK`: the ACK line arrives when the motion ends (S3). `DONE`: ACK on receipt, a `DONE,<cmd>` line on completion, `ERR,BUSY` / `ERR,STOPPED` as errors — the model proposed to the STM team |
| `STM_ACK_DEADLINE_S` / `STM_PING_DEADLINE_S` | `1` / `2` | reply deadlines for non-motion commands and for `PING` |
| `TURN_RADIUS_CM` | `{FL: 39, FR: 40, BL: 37, BR: 39}` | dead-reckoning arc displacement per direction; mirrors the planner's `config.TURN_RADIUS_CM` and must change with it |
| `CAPTURE_SETTLE_S` | `0.3` | pause before the first frame |
| `CAPTURE_FRAMES` | `3` | frames per obstacle |
| `CAMERA_WIDTH/HEIGHT/ROTATION` | `640` / `480` / `0` | |
| `LOG_FILE` | `/home/pi/rpi.log` | rotating, 512 KiB × 3, plus stdout |
| `STRATEGY_FALLBACK` | `optimal` | what `turnInPlace` maps to |

### 5.2 `bt_link.py`

- Opens `BT_PORT` `r+b` unbuffered and puts it in raw mode (no echo, no CRLF
  translation). Reads with `select`, 0.5 s tick.
- Framing: accumulate; split on `\n`; strip one trailing `\r`; drop empty
  lines; deliver each complete line to a callback. A line may span reads.
- `send(line)`: appends `\n`, writes under a lock. Never raises to the caller:
  a failed write marks the link down and is logged.
- Reconnect: when the read returns EOF or the device node vanishes, the link
  closes, waits `RETRY_DELAY` (3 s), and reopens. The rest of the program keeps
  running; a run in progress is **not** stopped.
- On reconnect, calls an `on_reconnect` hook so the run can replay results
  (§6.1 step 8).

### 5.3 `protocol.py`

Pure functions, no I/O. Mirrors `protocol.md` exactly.

**Inbound** — `parse(line) -> Inbound`, one of:
`Manual(token)`, `Add(id, x, y)`, `Sub(id)`, `Face(id, x, y, face|None)`,
`MoveRobot(x, y, deg)`, `SendArena(obstacles)`,
`ImageRec(algorithm, robot|None, obstacles)`, `FaceSearch(robot|None, obstacles)`,
`BeginFastest`, `Unknown(line)`. JSON lines are distinguished by a leading
`{`; the `command` key selects `ImageRec` / `FaceSearch`, its absence means
`SendArena`. A missing `robot` parses as `None` (§3.5 compatibility). Never
raises.

**Outbound** — `msg(text)`, `target(obstacle_id, competition_id)`,
`robot(x_cells, y_cells, heading_deg)`. `msg` never lets a newline through.
`robot` formats with two decimals and a degree value in `[0, 360)`.

### 5.4 `arena.py`

Pure conversion functions and the `Obstacle(id, x, y, face)` and
`Pose(x_cells, y_cells, heading_deg)` value types. **Holds no state** — a
run start carries its own obstacles and robot pose (§3.5). `START_POSE =
Pose(1.0, 1.0, 0.0)` is the fallback when a start message has no `robot`.

Conversions (the only place these formulas live):

| From | To | Rule |
|---|---|---|
| obstacle cell `(x, y)` | planner corners | `south_west = (10x, 10y)`, `north_east = (10x + 9, 10y + 9)` |
| face `N/E/S/W` | planner direction | `NORTH/EAST/SOUTH/WEST` |
| robot cells `(x, y)` | centre cm | `cx = 10x + 5`, `cy = 10y + 5` |
| centre cm `(cx, cy)` | robot cells | `x = (cx - 5) / 10` |
| centre cm | planner robot corners | clamp `cx`, `cy` to `[15, 184]` (log if it moved), then `south_west = (cx - 15, cy - 15)`, `north_east = (cx + 15, cy + 15)` — the planner rejects any corner ≥ 200 |
| heading deg | planner direction | nearest of 0/90/180/270 → `NORTH/EAST/SOUTH/WEST` |
| planner direction | heading deg | `NORTH=0, EAST=90, SOUTH=180, WEST=270` |

Start pose `(1.0, 1.0, 0°)` → centre `(15, 15)` → corners `(0,0)-(30,30)`,
which matches the planner README's example.

`to_planner_request(obstacles, robot, strategy)` builds the request body
from whichever list and pose the caller passes (the start message's for a
run; a single obstacle and the current pose for a face search leg).

### 5.5 `stm_driver.py`

```python
class StmDriver:
    def start(self) -> None                 # open, PING/PONG, push trim
    def manual(self, token: str) -> None    # tablet token; waits for the reply
    def manual_raw(self, line: str) -> None # passthrough (beginFastest)
    def execute(self, instr: Instruction, abort=None) -> None  # blocks until ACK; raises StmError;
                                                          # raises StmAborted at once if `abort` (the run's event) is set
    def stop(self) -> None                  # S now; safe from any thread
    def close(self) -> None
```

**Encoding**

| Instruction / token | Line |
|---|---|
| `FORWARD n` / `BACKWARD n` | `FW n` / `BW n` |
| `FORWARD_LEFT` / `FORWARD_RIGHT` | `TL 90` / `TR 90` |
| `BACKWARD_LEFT` / `BACKWARD_RIGHT` | `BL 90` / `BR 90` |
| `*_45` | same verb, `45` |
| `f` / `b` / `s` | `F` / `B` / `S` |
| `tl` / `tr` / `sl` / `sr` | `TL d` / `TR d` / `BL d` / `BR d`, `d = MANUAL_TURN_DEG` |

**Reply matching.** A reader thread pushes every line from the STM into a
queue and logs it. `execute` and `manual` hold the command lock, write the
line, then take lines from the queue until one starts with `ACK,` or `ERR,`;
data lines (`ENC,` `MA,` …) are logged and skipped. `ERR,*` raises
`StmError(command, reply)`. If the deadline passes with no reply, the driver
sends `S`, resyncs (below), and raises `StmError(command, "no reply")`.
With `STM_COMPLETION=DONE`, a motion command first waits ≤ `STM_ACK_DEADLINE_S`
for its `ACK,` (proof it was not dropped), then up to the motion deadline for
`DONE,` or `ERR,`. Non-motion commands are one line under either model.

**Stop.** `stop()` writes `S` under the write lock only, sets an `aborted`
event that makes any in-progress `execute` return early with
`StmAborted`, then **resyncs**: discards queue lines for `STM_STOP_DRAIN_S`,
sends `PING`, and discards until `PONG`. This makes S4 irrelevant.

**Startup.** Opening and the handshake live in the reconnect thread (one code
path for connect, at startup and after a loss). `start()` waits a grace period
(two `PING` deadlines plus the drain window plus a second) for the first
successful `PING` → `PONG` and raises `StmUnavailable` otherwise, while the
thread keeps trying. After `PONG`: `MA`, `MB`, `AS` from config, each awaited.

**Serial loss.** If the port raises, the driver marks itself down; `manual`
and `execute` raise `StmUnavailable` immediately; a background retry reopens
the port every 3 s and re-runs startup. An `on_link_change(up)` hook fires
after every successful handshake and on every loss of a working link; `main`
turns it into `MSG,STM connected` / `MSG,STM disconnected` (§7).

**`FakeStmDriver`** — same interface. `execute` sleeps `amount / 30` s for
straights and `3` s for arcs, `stop()` cuts the sleep short. Records every
line it would have sent, for tests. Selectable with `--fake-stm`.

### 5.6 `planner_client.py`

`plan(request_body) -> Plan`. The request always carries `verbose: true`,
because `path` is omitted otherwise and `end_pose` comes from it. `Plan` =
`segments: List[Segment]`,
`unreachable: List[(image_id, reason)]`, and `Segment` = `image_id`,
`instructions: List[Instruction]`, `end_pose: Pose` (from `path[-1]`, via
§5.4). `Instruction` is a small typed value (`Straight(dir, cm)`, `Arc(kind,
deg)`, `Capture`). Unknown instruction tokens raise `PlannerError`, which is
better than driving a path with a hole in it. HTTP errors, timeouts and 422s
raise `PlannerError(reason)` with the server's message when there is one.
Asserts the `X-MDP-Stub` header is absent unless `ALLOW_STUB_PLANNER` is set,
so a forgotten `--stub` cannot pass for a plan.

### 5.7 `vision_client.py`

`detect(jpeg_bytes, object_id) -> Verdict` where `Verdict` = `status`,
`competition_id|None`, `confidence|None`. Non-200 or malformed → `Verdict(status="error")`.
Never raises; the worker decides what to do.

### 5.8 `vision_worker.py`

- `submit(obstacle_id, frames: List[bytes], quiet=False) -> bool` — enqueue;
  returns immediately; `False` when no vision URL is configured (frames dropped,
  one `MSG` ever), so a run can skip waiting for a verdict that cannot come. `quiet` suppresses the miss `MSG`s (the face search narrates
  misses itself); `TARGET` lines are always sent.
- Worker thread: per obstacle, POSTs each frame with `object_id = "B<id>"`;
  result = the `target` verdict with the highest confidence if any, else
  `bullseye` if any frame said so, else `no_detection` (or `error` if every
  frame errored).
- On a result: `TARGET,B<id>,<competition_id>` via `bt_link` for a target;
  otherwise a `MSG`: `B3: bullseye - wrong face?`, `B3: nothing recognised`,
  `B3: recogniser unreachable`. One line per obstacle, never per frame.
- `wait(obstacle_id, timeout) -> Result|None` — blocks until that obstacle's
  result exists. Used by `FaceSearchRun` and by `Task1Run`'s final drain.
- `results` — every result so far, for replay on reconnect.

### 5.9 `camera.py`

```python
class Camera:
    def start(self) -> None
    def capture_jpeg(self) -> bytes     # raises CameraError
    def close(self) -> None
```

`PiCameraLegacy` wraps `picamera.PiCamera` with the configured resolution and
rotation, warms up 2 s on `start()`, and captures to an in-memory JPEG.
`FakeCamera` returns a fixed JPEG from `rpi/fixtures/frame.jpg`. Selected by
`--fake-camera`. A `CameraError` on capture is reported and the run
continues (§7).

### 5.10 `pose.py`

Dead reckoning for the tablet's marker. `advance(pose, instruction) -> Pose`:

- `Straight`: move `cm` along the heading (backward = negative).
- `Arc`: with `R = TURN_RADIUS_CM[kind]` and the robot's frame (forward, left):
  `FORWARD_LEFT` → +R forward, +R left, heading −90;
  `FORWARD_RIGHT` → +R forward, −R left, heading +90;
  `BACKWARD_LEFT` → −R forward, +R left, heading +90;
  `BACKWARD_RIGHT` → −R forward, −R left, heading −90.
  45° variants: half the displacement, ±45.
- `Capture`: unchanged.

This is deliberately crude; the run **snaps** to `Segment.end_pose` after
each segment, so drift in the drawing never lasts longer than one segment.
The reverse-arc heading signs are the one thing here that must be checked
against the real car; if they're backwards, two literals swap.

### 5.11 `run.py`

`RunController` — holds at most one run; `start(run)` refuses if one is
active; `stop()` sets the run's `abort` event, then calls `stm_driver.stop()`.
That order, plus `execute(instr, abort=run.abort)` refusing to send once the
event is set, closes the window in which a STOP could be followed by one more
move.
The run thread notices the event, sends `MSG,Stopped`, and ends. The only
line the controller sends itself is `MSG,Run failed: <error>` when a run
raises — a bug in a run must never take the program down.

`Task1Run` and `FaceSearchRun` are specified in §6.

### 5.12 `main.py`

Builds everything from config and flags, starts the STM driver and the vision
worker, then runs the Bluetooth loop with the dispatcher from §4.3. On
`KeyboardInterrupt`: stop any run, `S` to the STM, close everything.

---

## 6. Runs

### 6.1 `Task1Run` — the image-rec start

Input: the tablet's `ImageRec(algorithm, robot, obstacles)`.

1. `MSG,Planning...`. Build the request from the message's obstacles and
   its `robot` pose (`START_POSE` with a `MSG` if absent). `algorithm`:
   `greedy`/`optimal` pass through;
   `turnInPlace` → `STRATEGY_FALLBACK` with `MSG,turnInPlace not supported by
   planner - using optimal`.
2. `plan()`. On `PlannerError`: `MSG,Planner error: <reason>`, run ends, robot
   never moved.
3. `MSG,Visiting <n> of <m>` and, if any, `MSG,Unreachable: B3, B5`.
4. For each segment, for each instruction, unless aborted:
   - `Capture` → step 5.
   - otherwise `stm_driver.execute(instr)`; on `StmError` → `stm_driver.stop()`,
     `MSG,Aborted at <cmd>: <reply>`, run ends; on `StmAborted` → the run
     thread sends `MSG,Stopped` and ends.
   - `pose = advance(pose, instr)`; `ROBOT,...` to the tablet.
   - After the segment's last instruction: `pose = segment.end_pose`;
     `ROBOT,...`.
5. `Capture`: `MSG,Capturing B3`; sleep `CAPTURE_SETTLE_S`; take
   `CAPTURE_FRAMES` frames as fast as the camera allows; `vision_worker.submit`;
   **continue immediately**. A `CameraError` → `MSG,B3: camera failed`, no
   frames submitted, continue.
6. After the last segment: wait up to `VISION_DRAIN_TIMEOUT_S` for every
   submitted obstacle to have a result.
7. `MSG,Done: <k> of <n> recognised` (or `MSG,Done: <k> of <n> recognised,
   verdicts pending` if the drain timed out). Run ends. The last `ROBOT` line
   sent is the pose the tablet will carry into the next start message.
8. On Bluetooth reconnect at any point: replay every `TARGET` result so far and
   the latest `ROBOT`, then `MSG,Reconnected - run in progress` or
   `MSG,Reconnected`.

Bullseye during Task 1 is **reported, never acted on** (§5.8). The face was
given by the supervisor; a bullseye means drift or a mis-keyed face, and the
operator should know which obstacle.

### 6.2 What the tablet sees during a run

```
TX  {"command":"imageRec","algorithm":"greedy","obstacles":[...]}
RX  MSG,Planning...
RX  MSG,Visiting 2 of 2
RX  ROBOT,1.00,4.50,0            after FW 35
RX  ROBOT,4.00,7.50,90           after TR 90
RX  MSG,Capturing B1
RX  ROBOT,4.00,7.50,90           snap to segment end
RX  TARGET,B1,16                 from the worker, while driving segment 2
RX  ROBOT,...
RX  MSG,Capturing B2
RX  TARGET,B2,31
RX  MSG,Done: 2 of 2 recognised
```

### 6.3 `FaceSearchRun` — the A.5 demo

Input: the tablet's `FaceSearch(robot, obstacles)` — normally one obstacle,
whose declared `face` is the side the supervisor put the bullseye on. If more
than one is sent, the first is searched and the rest are ignored with a
`MSG`.

1. `checked = set()`; `face = declared face`; `pose = robot` from the message
   (`START_POSE` with a `MSG` if absent).
2. Plan from `pose` to `obstacle` with `direction = face` (a normal
   `/pathfinding/` request with one obstacle). `unreachable` → treat as
   examined (`checked.add(face)`), go to 5.
3. Drive the segment exactly as §6.1 step 4, snapping to `end_pose`.
4. Capture as §6.1 step 5, then **`vision_worker.wait(obstacle, VISION_TIMEOUT_S × CAPTURE_FRAMES + 2)`**.
   - `target` → the worker already sent `TARGET`; `MSG,Found image on <face>
     face`; run ends.
   - anything else → `checked.add(face)`; `MSG,B1: bullseye on <face> face -
     searching`.
5. If `len(checked) == 4`: `MSG,No image found on B1`; run ends.
   Otherwise choose the next face: for each unchecked face, plan from the
   current pose (up to three requests); drop `unreachable` ones (they count
   as checked); pick the segment with the lowest `seconds` (or the fewest
   instructions if `seconds` is absent). Go to 3 with that plan.
6. Stop, errors and reconnect behave as in §6.1.

The order of faces is decided by the planner's cost, not hard-coded, so the
robot takes the short way round and respects walls and other obstacles.

---

## 7. Error handling

The rule: every failure produces a `MSG` the operator can read, the run ends
in a known state, and the Bluetooth link is never dropped by the program.

| Failure | Detected by | Robot | Tablet sees |
|---|---|---|---|
| Planner unreachable / 5xx / 422 / bad response | `planner_client` | never moves | `MSG,Planner error: <reason>` |
| Planner marks obstacles unreachable | response | visits the rest | `MSG,Unreachable: B3` |
| STM `ERR,*` | driver | `S` | `MSG,Aborted at FW 30: ERR,GYRO` — run ends |
| STM silent past deadline | driver | `S`, resync | `MSG,Aborted at TL 90: no reply` — run ends |
| STM port gone | reader thread | — | `MSG,STM disconnected`; manual refused with `MSG,STM unavailable` until it returns |
| Camera error | `camera` | keeps driving | `MSG,B3: camera failed` |
| CV server down / slow | worker | keeps driving | `MSG,B3: recogniser unreachable`, once per obstacle |
| STOP | main thread | `S` at once | `MSG,Stopped` |
| Tablet disconnects | `bt_link` | **keeps going** | on reconnect: replayed `TARGET`s, latest `ROBOT`, `MSG,Reconnected…` |
| Unknown tablet line | dispatcher | — | `MSG,Unknown command: …` |

STM errors stop the robot because after a failed move the pose is unknown and
continuing the plan from a wrong pose ends in an obstacle. Camera and CV
errors do not stop the robot because a lost photo costs one target, not the
run. A tablet disconnect does not stop the robot because in the graded run
the operator may not touch anything after pressing start.

---

## 8. Testing

Everything above the two hardware links is unit-tested on a laptop with
`pytest`. No test opens a serial port, a Bluetooth device or a camera.

| Module | Tests |
|---|---|
| `protocol` | every message in `protocol.md` §1 parses to the right value; malformed lines → `Unknown`, never an exception; outbound builders match §2 byte for byte |
| `arena` | every conversion in §5.4, both directions, including the start pose and the README example |
| `stm_driver` | with an in-memory serial stub: encoding table; reply matching skips data lines; `ERR,*` raises; deadline → `S` + resync; `stop()` interrupts a waiting `execute`; startup pushes trim |
| `planner_client` | with a stubbed `requests` session: request body for a known arena; parse of a sample response including `_45` tokens and `unreachable`; 422 and timeout → `PlannerError`; stub header refused |
| `vision_client` | 200 shapes for all four statuses; 400/500; malformed JSON |
| `vision_worker` | best-of-three selection; one `MSG` per obstacle; `wait` semantics |
| `pose` | each instruction's displacement and heading; 45° variants |
| `run` | `Task1Run` and `FaceSearchRun` end to end with `FakeStmDriver`, `FakeCamera`, a stubbed planner and a stubbed vision client: the exact sequence of lines the tablet receives for a two-obstacle plan; STOP mid-segment; STM error mid-segment; face search finds the image on face three |

**Laptop end-to-end**: `python3 -m rpi --fake-stm --fake-camera` with
`RPI_BT_PORT` pointed at a pty pair and the real planner running locally,
driven by hand from a serial terminal. This is the pre-Pi smoke test.

**On the Pi**, in order: `--fake-stm --fake-camera` with the real tablet;
then the real camera; then the real STM.

---

## 9. Deployment

- `git clone` on the Pi; `python3 -m venv --system-site-packages .venv`;
  `pip install pyserial requests`.
- `RPI_PLANNER_URL` and `RPI_VISION_URL` set per session — the laptop's IP
  changes. A `.env` example is provided; the program reads the environment only.
- Bluetooth via a `bluetooth.sh` that registers the SPP record and runs
  `rfcomm watch` (this branch's own script, not another group's).
- Start: `python3 -m rpi`. A systemd unit is optional and out of scope.
- `rpi/android_rpi_stm_bridge_quiet_v2.py` is superseded and removed when the
  package lands.

---

## 10. Build order

1. **Links + manual drive** — `config`, `bt_link`, `protocol`, `arena`,
   `stm_driver`, `main` with the dispatcher. Deployable immediately; replaces
   the bridge with something that speaks the STM's real vocabulary.
2. **Planner + executor** — `planner_client`, `pose`, `run.Task1Run` minus
   capture, on `FakeStmDriver`. The full Task 1 flow minus photos, on a laptop.
3. **Camera + vision** — `camera`, `vision_client`, `vision_worker`; capture
   in `Task1Run`. Task 1 complete.
4. **`FaceSearchRun`.**

Each step ends with its tests passing and a commit.

---

## 11. Decisions and their reasons

| Decision | Reason |
|---|---|
| Threads, not asyncio | Python 3.7 on Buster; `pyserial-asyncio` on armv7 is friction; teammates don't write async |
| `/dev/rfcomm0`, not a Python RFCOMM socket | it's what already works on this Pi; another group's working setup uses the same |
| No RPi-side arena state; the start message carries the pose | a start is then a complete snapshot; a Bluetooth drop before it can't leave stale state; the tablet already had the pose, so adding it costs one object |
| Take 3 frames and move on | keeps the CV round-trip off the critical path; the camera is idle while the robot drives anyway |
| Best-of-three by confidence, not first hit | costs nothing extra; catches the blurry first frame |
| Bullseye in Task 1 is reported, not acted on | the face is given; a detour in a timed run is a surprise, not a feature |
| A.5 is a separate trigger | Task 1 stays deterministic; the demo is explicit |
| A.5 uses the planner, not a hard-coded manoeuvre | the planner is needed for the first leg anyway, so a macro adds tuning and a wall limitation while removing no dependency; A.5 is demoed with Task 1, not before it |
| Manual commands refused during a run | keeps STM reply matching a simple in-order queue |
| STM errors stop the robot; camera/CV errors don't | pose unknown vs. one target lost |
| Tablet disconnect doesn't stop the robot | operator may not touch anything after start |
| Dead reckoning + snap, not walking `path` | `path` is documented as "good for drawing, not for driving"; snapping bounds the drift to one segment |
