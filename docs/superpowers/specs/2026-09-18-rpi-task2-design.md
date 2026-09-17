# RPi program — Task 2 (fastest car) design

**Date:** 2026-09-18
**Status:** draft for review; the STM command names in §3.1 are a proposal
awaiting the STM team's reply to `docs/rpi-stm-handover.md` §5
**Extends:** `2026-09-17-rpi-task1-design.md` — everything there stands;
this document only adds.

---

## 1. What this is

The Task 2 run on the Raspberry Pi: from the tablet's `beginFastest`, drive
to obstacle 1, read its arrow, go round it on that side, do the same at
obstacle 2, loop behind it, and come home to the carpark — narrating to the
tablet and stopping on STOP, exactly as the Task 1 run does.

**Rules that shape it** (briefing pp. 19–22): carpark 60 × 60; obstacle 1 at
60–150 cm, obstacle 2 (the bigger block) another 60–150 cm on, both directly
ahead; each carries a left (image id 39) or right (id 38) arrow facing the
carpark; there may be a wall beyond obstacle 2. The approach **must be
sensor-driven** (camera, IR or ultrasonic allowed). 3-minute cap, +10 s per
obstacle contact, bulldozing disqualifies, a misread arrow or a wrong side
voids the run. Correctness first; then it is a stopwatch.

**Division of labour.** The Pi runs the sequence and reads the arrows. The
STM owns every manoeuvre and every sensor, because the calibration lives
where the wheels are. The planner is not involved. The tablet needs nothing
new.

## 2. Scope

### In v1

1. `FastestRun` — the state machine below, started by `beginFastest`, stopped
   by `s`, narrated with `MSG`.
2. Arrow reading from a **pluggable source**: the PC server's `/detect` (the
   Task 1 model's arrow classes; works today) or an **on-Pi TFLite** detector
   (no WiFi on the critical path) once the arrow model exists. A frame-vote
   consensus above both.
3. The STM commands of §3.1 in the driver, with fakes so the whole run
   executes on a laptop.
4. `RANGE` at each stop as a sanity check that the sensor sees the obstacle.

### Not in v1

- A camera-driven approach (creep and measure the arrow's apparent size)
  for a car with no working range sensor. The seek is one method on the run;
  this would be a second implementation of it.
- Re-reading after a wrong turn, or any recovery beyond "stop and say why".
- Tablet changes. `FASTEST` and its clock already exist.

## 3. Contracts

### 3.1 STM — proposed in the handover, to be confirmed

All with the confirmed reply model: `ACK,<verb>` on receipt within 1 s,
`DONE,<verb>[,data]` on completion, any `ERR,` ends the run.

| Pi sends | STM replies | Meaning | Pi deadline for `DONE` |
|---|---|---|---|
| `RANGE` | `RANGE,<cm>` | one forward ultrasonic reading, any time | 1 s (data line) |
| `SEEK <cm>` | `ACK,SEEK` … `DONE,SEEK,<travelled_cm>` | forward at Task 2 speed until the ultrasonic reads ≤ `<cm>`; report encoder distance travelled | `STM_SEEK_DEADLINE_S` (20) |
| `ROUND <n> <L\|R>` | `ACK,ROUND` … `DONE,ROUND` | round obstacle `n` (1 or 2) on the left or right, ending on the centre line: heading onward for 1, heading home for 2 (the side IR marks the end of the block) | `STM_ROUTE_DEADLINE_S` (25) |
| `HOME <cm>` | `ACK,HOME` … `DONE,HOME` | drive `<cm>` toward the carpark and stop inside it | `cm / 10 + 5` (the straight formula) |
| `S` | as today | stop anything | — |

Fixed numbers the STM team supplies and the Pi keeps in config:
`T2_AROUND1_NET_CM`, `T2_AROUND2_NET_CM` — the net displacement along the
course of each manoeuvre — so the distance home is
`travelled_1 + travelled_2 + T2_AROUND1_NET_CM + T2_AROUND2_NET_CM`.
If they would rather the STM keep its own odometer and `HOME` take no
argument, that is a one-line change in `encode` and this formula goes.

Hardware, from the component list: HC-SR04 forward; two Sharp GP2Y0A21YK
IR rangers on the sides; hall encoders. All read by the STM (handover §5.1).

### 3.2 Arrow recognition

Two sources, one interface (§5.1):

- **HTTP:** `POST {VISION_URL}/detect` as in Task 1. A `target` with
  `competition_id` 38 or 39 is an arrow; anything else is "no arrow". Uses
  the existing `VisionClient`.
- **On-Pi TFLite:** the exported `best_arrows.tflite` and `arrow-labels.json`
  from `image-rec/training/export_int8.py`, run with `tflite-runtime 2.5.0`
  (Buster/3.7/armv7l wheel from the Coral index) and OpenCV from apt.
  Jerick's `image-rec/rpi/inference/tflite_detector.py` is the reference
  implementation; it is **adapted into `rpi/arrow.py` with attribution**
  rather than imported, because his package is also named `rpi` and two
  top-level `rpi` packages cannot coexist in one interpreter.

Class order for the model: `arrow-labels.json` (Up, Down, Right, Left);
only Right and Left are arrows we act on.

### 3.3 Tablet

Unchanged. Inbound `beginFastest` (§4.3 of the Task 1 spec: now starts the
run instead of being forwarded) and `s`. Outbound `MSG` only — Task 2 has no
obstacles or targets on the tablet.

## 4. Architecture

New: `rpi/arrow.py` (sources + consensus), `FastestRun` in `rpi/run.py`,
five encodings and four driver calls in `rpi/stm_driver.py`, config keys,
`fastest_factory` in `rpi/main.py`. The dispatcher's `BeginFastest` branch
starts the run when a factory is wired and falls back to today's passthrough
when it is not (so the manual-drive milestone is unchanged).

Threads as before: the run thread executes; the STM reader feeds replies; the
camera is read synchronously on the run thread during the arrow read (the
vision worker is not used — Task 2 needs the verdict before moving).

## 5. Module specs

### 5.1 `rpi/arrow.py`

```python
@dataclass(frozen=True)
class Sighting:            # one arrow seen in one frame
    direction: str         # "left" | "right"
    confidence: float

class ArrowSource(ABC):
    def sightings(self, jpeg: bytes) -> List[Sighting]: ...   # never raises; [] on any failure
    configured: bool

class HttpArrowSource(ArrowSource):      # wraps VisionClient.detect; 38 -> right, 39 -> left
class TfliteArrowSource(ArrowSource):    # lazy-imports tflite_runtime, cv2, numpy; adapted from image-rec;
                                         # cv2.imdecode turns the JPEG into the BGR array the model wants
class FakeArrowSource(ArrowSource):      # scripted list of frame results, for tests

class Consensus:
    def __init__(self, required: int = 3, window: int = 5, min_confidence: float = 0.75)
    def observe(self, sightings: List[Sighting]) -> Optional[str]
        # best sighting of the frame (highest confidence >= min_confidence) or None;
        # keep the last `window` frames; return the direction that appears
        # >= `required` times with no tie, else None
    def reset(self) -> None

def read_arrow(camera, source, consensus, timeout_s, abort) -> Optional[str]
    # capture -> sightings -> observe, until a decision, the timeout or abort
```

`ARROW_IDS = {38: "right", 39: "left"}`, in one place.

### 5.2 `rpi/stm_driver.py` additions

- Encodings: `encode_seek(cm) -> "SEEK <cm>"`, `encode_round(n, side) -> "ROUND n L" | "ROUND n R"`,
  `encode_home(cm) -> "HOME <cm>"`, `"RANGE"`. `is_motion` gains `SEEK ROUND HOME`.
- `StmDriver` gains `seek(cm, abort) -> Optional[int]` (travelled cm parsed from
  `DONE,SEEK,<n>`; `None` if absent), `round(n, side, abort) -> None`,
  `home(cm, abort) -> None`, `range_cm() -> Optional[int]` (`RANGE`; `None` on
  no reply — never fatal).
- `_deadline` maps `SEEK` → `STM_SEEK_DEADLINE_S`, `ROUND` → `STM_ROUTE_DEADLINE_S`,
  `HOME` → straight formula. DONE parsing: `DONE,SEEK,87` → 87. The verb
  match is on the first token, so `ROUND 2 R` is acknowledged by `ACK,ROUND`.
- `FakeStmDriver` gains `seek_distances: List[int]` (scripted, popped per seek)
  and `range_readings: List[int]`; records lines as today; timed like the rest.

### 5.3 `rpi/config.py` additions

| Key | Default | |
|---|---|---|
| `ARROW_SOURCE` | `http` | `http` or `tflite` |
| `ARROW_MODEL_PATH` / `ARROW_LABELS_PATH` | `rpi/models/best_arrows.tflite` / `rpi/models/arrow-labels.json` | tflite only |
| `ARROW_MIN_CONFIDENCE` | `0.75` | Jerick's default |
| `ARROW_REQUIRED` / `ARROW_WINDOW` | `3` / `5` | the vote |
| `ARROW_TIMEOUT_S` | `8` | per arrow, then the run stops |
| `T2_STOP_CM` | `30` | the `SEEK` argument; where the arrow is read from |
| `T2_AROUND1_NET_CM` / `T2_AROUND2_NET_CM` | `0` / `0` | from the STM team |
| `STM_SEEK_DEADLINE_S` / `STM_ROUTE_DEADLINE_S` | `20` / `25` | |

### 5.4 `FastestRun` (`rpi/run.py`)

`FastestRun(message: BeginFastest, stm, camera, send, source, consensus, stop_cm,
around_net, arrow_timeout_s)` — a `BaseRun`, not a `_DrivingRun` (no planner
pose to report).

## 6. The run, step by step

Every line below is what the tablet sees. `t` is the Pi's own clock from
the start line, for the log; the tablet keeps the official one.

```
RX  MSG,Fastest: seeking obstacle 1
                                  > SEEK 30 ... < DONE,SEEK,87
RX  MSG,Obstacle 1 at 87 cm       (then RANGE: the reading is logged; a MSG only if it disagrees, see below)
RX  MSG,Reading arrow 1
                                  capture / detect / vote until 3 of 5 agree
RX  MSG,Arrow 1: LEFT
                                  > ROUND 1 L ... < DONE,ROUND
RX  MSG,Seeking obstacle 2
                                  > SEEK 30 ... < DONE,SEEK,112
RX  MSG,Obstacle 2 at 112 cm
RX  MSG,Reading arrow 2
RX  MSG,Arrow 2: RIGHT
                                  > ROUND 2 R ... < DONE,ROUND
RX  MSG,Returning 259 cm          (87 + 112 + around1 + around2)
                                  > HOME 259 ... < DONE,HOME
RX  MSG,Parked in 41.3 s
```

Rules applied at each step:

- **Abort check** before every STM command and inside the arrow loop; on
  STOP: `stm.stop()` (the controller does this), the run sends `MSG,Stopped`
  and ends.
- **Arrow not decided within `ARROW_TIMEOUT_S`:** `MSG,Arrow 1 not readable -
  stopped`. The run ends without moving — a guess would void the run; the
  operator can reposition and press FASTEST again.
- **`DONE,SEEK` without a distance:** `MSG,STM gave no distance - cannot return`
  and the run ends there, not at the end: it cannot finish without the
  number, and finding that out after the arrows wastes the attempt.
- **STM `ERR,*` or silence:** as Task 1, `MSG,Aborted at SEEK 30: ERR,TIMEOUT`.
- **`RANGE` disagrees badly with the stop distance** (reading > `stop_cm` + 15 or
  no reading): `MSG,Warning: sensor reads 52 cm`; the run continues — the
  arrow read decides whether it was really in front of the obstacle.
- **Arrow source not configured** (`http` with no `VISION_URL`, or `tflite`
  with no model file): refused at start, `MSG,Arrow source not configured`,
  nothing sent to the STM.

## 7. Error table (additions to Task 1 §7)

| Condition | Who notices | STM action | Tablet sees |
|---|---|---|---|
| no arrow consensus in time | run | none | `Arrow n not readable - stopped` |
| `DONE,SEEK` lacks a distance | driver → run | none | `STM gave no distance - cannot return` |
| `RANGE` far from `stop_cm` | run | none | `Warning: sensor reads N cm`, continues |
| STOP during a seek/route/home | controller | `S`, resync | `Stopped` |
| STM `ERR`/silence | driver | `S`, resync | `Aborted at <cmd>: <reply>` |
| arrow source unavailable | run start | none | `Arrow source not configured` |
| camera failure mid-read | run | none | counts as a frame with no sighting; the timeout decides |

## 8. Testing

Unit, no hardware, as Task 1:

- `test_arrow.py`: id mapping; consensus (3 of 5, ties, threshold, window
  sliding, reset); `read_arrow` decides / times out / aborts; HTTP source
  maps 38/39 and swallows errors; TFLite source reports unconfigured when
  the model file is missing (the detector itself is only exercised when
  `tflite_runtime` is importable — skipped otherwise).
- `test_stm_driver.py` / `test_stm_serial.py`: the five encodings; `DONE,SEEK,87`
  parsing; `DONE,SEEK` without a number; `RANGE` reply and no-reply; deadlines.
- `test_fastest_run.py`: the full run line by line with scripted distances
  and arrows (the transcript in §6 is the assertion); each row of §7.
- `test_dispatcher.py`: `beginFastest` starts the run when the factory is
  wired, passes through when it is not.
- `test_main.py`: `build()` wires the factory; the `http` source is chosen
  by default.

On the Pi, in this order: `RANGE` and `SEEK 30` by hand over CoolTerm; the run
with `--fake-stm` and the real camera against the PC server, an arrow
printout held in front of the car (proves the read and the narration); the
run with the real STM on a two-obstacle course; then the on-Pi source once
the model exists. `FakeArrowSource` is for the unit tests only and is not
selectable from config.

## 9. Open items (each blocks a step, none blocks the spec)

| # | Item | Owner | Blocks |
|---|---|---|---|
| 1 | Confirm `RANGE / SEEK / ROUND / HOME` and the `DONE,SEEK,<cm>` payload | STM | driver encodings |
| 2 | `T2_AROUND1_NET_CM`, `T2_AROUND2_NET_CM`, or bare `HOME` | STM | the return |
| 3 | Sensor mounting: ultrasonic forward, IRs sideways | STM | nothing on the Pi |
| 4 | `best.pt` for the PC server (arrows via the Task 1 classes) | CV | any real arrow read |
| 5 | `best_arrows.tflite` + labels, or the decision to skip the separate model | CV | the on-Pi source |
| 6 | The stop distance at which the arrow is reliably read (`T2_STOP_CM`) | CV + STM | tuning only |
