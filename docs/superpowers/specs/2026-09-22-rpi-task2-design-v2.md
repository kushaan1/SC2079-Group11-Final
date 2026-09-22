# RPi program — Task 2 (fastest car) design (v2, rules-checked)

**Date:** 2026-09-22 (revision of shuenwei's 2026-09-18 original, itself revised the same day
after review)
**Status:** revised against the official MDP rules (`docs/rules/rules.md`, `docs/rules/`), which did not
exist when the original was written. Sections marked **[RULE DELTA]** are new or changed from the
original; everything else carries the original's content forward unchanged. The STM command names
in §3.1 remain a proposal awaiting the STM team's reply to `docs/rpi-stm-handover.md` §5.
**Extends:** `2026-09-22-rpi-task1-design-v2.md` — everything there stands; this document only adds.

---

## 0. Rule deltas vs. the 2026-09-18 original (added 2026-09-22)

Three gaps, found by checking the original design against `docs/rules/rules.md`:

| # | Rules say | Original design | What changes |
|---|---|---|---|
| 1 | Obstacle 2's dimension (10cm wide, 30cm+ long) is **revealed only after the 2-minute prep, just before the run** (`docs/rules/rules.md` Task 2 layout paragraph) | §3.1's `ROUND 2` v1 is "a fixed loop with obstacle 2's width as an **STM constant (measured on the day)**"; the build order (§9) puts this fixed loop before the IR-terminated v2 | A number handed to the team minutes before their run cannot be a firmware constant "measured on the day" in the sense the original meant (measured once, in advance, and flashed). It must be a fast runtime/config value the team can set during the 2-minute prep or between the STM handshake and `beginFastest`, and the IR-terminated loop (v2) — which needs no measured width at all — becomes the safer default to prioritise, not a v2 refinement. See §3.1 and §9 below |
| 2 | Hitting the **carpark wall is an outright disqualification**; hitting a **goal obstacle is a +10s penalty** (`docs/rules/rules.md` Task 2 rule 6, FAQ 6–7) | §7's error table (additions to Task 1 §7) doesn't distinguish carpark-wall contact from obstacle contact | `HOME`'s design intent must explicitly favour a safe, centred approach into the carpark over a fast one — see §3.1's `HOME` row and the new §7 row below |
| 3 | Task 2 also requires the **RAW captured images with bounding boxes**, for images on goal obstacles, shown at the end of the run (`docs/rules/rules.md` Task 2 rule 8, FAQ 16) | §3.2's on-Pi TFLite arrow source makes the left/right decision locally and never hands a frame to the PC server; only the HTTP source's frames reach it | Every arrow-read frame — regardless of which source decided the direction — must still be persisted where it can be shown, the same way Task 1's captures are. See §3.2 below |

None of these change the run's state machine (§6) or the STM command shapes (§3.1) themselves —
they change what value feeds `ROUND 2`, how cautious `HOME` is designed to be, and where arrow-read
frames go. The rest of this document is shuenwei's original, with these points folded into the
relevant sections (§3.1, §3.2, §7, §9) rather than left as a separate patch.

---

## 1. What this is

The Task 2 run on the Raspberry Pi: from the tablet's `beginFastest`, drive
to obstacle 1, read its arrow, go round it on that side, do the same at
obstacle 2, loop behind it, and come home into the carpark — narrating to the
tablet and stopping on STOP, exactly as the Task 1 run does.

**The course** (`docs/rules/rules.md` Task 2 section, and its layout figure):

- The carpark is a **60 × 60 cm U** with walls on three sides, open toward
  the course. The car starts inside it and must finish inside it, which
  means it must come home **centred** — the opening is 60 cm and the car is
  19 cm wide.
- Obstacle 1 is 60–150 cm from the carpark and obstacle 2 another 60–150 cm on,
  both on the carpark's centre line. Obstacle 2 is the bigger block: 10cm
  wide, length from a minimum of 30cm up to some maximum, **and its exact
  dimension is disclosed only after the 2-minute prep, right before the
  run** (`docs/rules/rules.md`) — not something the team can pre-measure, unlike
  the original design's phrasing suggested.
- Each obstacle carries a left (image id 39) or right (id 38) arrow at the
  centre of the face toward the carpark. Bullseyes sit on the carpark's outer
  corners and the obstacles' sides (not used in v1).
- There may be a wall or obstacle beyond obstacle 2's sides, but never
  closer than **50 cm from obstacle 2's edge** — so the loop always has that
  much floor.
- The approach **must be sensor-driven** (rules allow camera, IR or
  ultrasonic). 3-minute cap, **+10 s per obstacle contact** — but **hitting
  the carpark wall is a disqualification, not a time penalty**
  (`docs/rules/rules.md` FAQ 6–7) — and bulldozing disqualifies outright. A
  misread arrow or a wrong side voids the run. One retry, shared with Task 1.
  Correctness first; then it is a stopwatch.
- **[RULE DELTA]** The robot must stay inside the carpark zone for the
  whole 2-minute prep; moving it out during prep-time calibration is an
  automatic disqualification (`docs/rules/rules.md` FAQ 9). None of the pre-flight
  checks in §6 below move the robot, so this is a constraint on future
  changes, not on anything currently designed.

**The path, which is not symmetric:** out along the centre line; round
obstacle 1 on its arrow side and back to the centre line; round obstacle 2 on
its arrow side, loop behind it, and come back on the **far** side of it —
that is a lane offset from the centre line; stay on that lane past
obstacle 1 (which is on the centre line), then re-centre and enter the
carpark. The home leg is a lane, a re-centre and a stop, never a straight
line down the middle.

**Division of labour.** The Pi runs the sequence and reads the arrows. The
STM owns every manoeuvre, every sensor and its own odometer, because the
calibration lives where the wheels are. The planner is not involved. The
tablet needs nothing new.

## 2. Scope

### In v1

1. `FastestRun` — the state machine in §6, started by `beginFastest`, stopped
   by `s`, narrated with `MSG`.
2. Arrow reading from a **pluggable source**: the PC server's `/detect` (the
   Task 1 model's arrow classes) or an **on-Pi TFLite** detector once the
   arrow model exists, with a frame vote above both and a nudge-and-retry
   loop when the vote does not land. **[RULE DELTA] Both sources still send
   every read frame to the PC server for storage (§3.2), regardless of which
   one decides the direction.**
3. The STM commands of §3.1 in the driver, with fakes so the whole run
   executes on a laptop, and a `--fake-arrows` flag so the STM team can
   rehearse the full sequence on the real car with no camera and no WiFi.
4. `RANGE` at each stop as a sanity check that the sensor sees the obstacle.

### Contingency, decided by a date

**[RULE DELTA]** Given obstacle 2's length is unknown until minutes before
the run (§0 #1), this "contingency" is now closer to the *default* plan for
`ROUND 2` than a fallback — a fixed-loop constant baked in ahead of time
cannot be correct for a length disclosed after prep. If the STM manoeuvres
are not driveable by the agreed date (§9 item 7), the
Pi composes `ROUND 1`, `ROUND 2` and `HOME` from `FW/BW/TL/TR/BL/BR` with
the lane widths and loop length as Pi config — which has the advantage that
the loop length is then a config value the team can set during prep or
between the STM handshake and start, not a firmware rebuild. It is slower
(each arc is a separate command with a full stop) and moves the tuning to
the Pi, but it needs only `BW` and `SEEK` from the firmware. The run's state
machine is the same; only the four "manoeuvre" calls change implementation.

### Not in v1

- A camera-driven approach (creep and measure the arrow's apparent size)
  for a car with no working range sensor.
- IR-terminated loop round obstacle 2 (§3.1 stages it as v2 on the STM,
  **though §0 #1 above means this should be pulled forward, not left last —
  see §9**).
- Recovery beyond nudge-and-retry: "stop and say why" for everything else.
- Tablet changes. `FASTEST` and its clock already exist.

## 3. Contracts

### 3.1 STM — proposed in the handover, to be confirmed

All with the confirmed reply model: `ACK,<verb>` on receipt within 1 s,
`DONE,<verb>[,data]` on completion, any `ERR,` ends the run. The Pi matches
the verb on the first token, so `ROUND 2 R` is answered by `ACK,ROUND`.

| Pi sends | STM replies | Meaning | Pi deadline for `DONE` |
|---|---|---|---|
| `RANGE` | `RANGE,<cm>` | one forward ultrasonic reading, any time | 1 s (data line) |
| `SEEK <cm>` | `ACK,SEEK` … `DONE,SEEK,<travelled_cm>` | forward at Task 2 speed until the ultrasonic reads ≤ `<cm>` on **three consecutive readings**, then stop; reply `DONE,SEEK,0` at once if already inside; `ERR,TIMEOUT` past a cap of ~200 cm. The travelled distance is for the Pi's log only. | `STM_SEEK_DEADLINE_S` (20) |
| `ROUND 1 <L\|R>` | `ACK,ROUND` … `DONE,ROUND` | round obstacle 1 on that side and end back on the centre line heading onward. **Forward budget:** it must end less than `60 − T2_STOP2_CM − sensor offset` cm past obstacle 1's rear face, or obstacle 2 at its closest is already inside `SEEK`'s threshold; from a 30 cm standoff it likely starts with a short reverse (`BW` is therefore a Task 2 blocker too). | `STM_ROUTE_DEADLINE_S` (25) |
| `ROUND 2 <L\|R>` | `ACK,ROUND` … `DONE,ROUND` | go round obstacle 2 on that side, loop behind it, come back on the far side and end on the return lane heading home. **[RULE DELTA] Its loop distance can no longer be a value "measured on the day" and flashed ahead of time — obstacle 2's length is disclosed only after prep, minutes before the run (§0 #1).** Two options, re-ordered from the original's v1/v2 split: **(a) IR-terminated** — the side IR ends the along-the-block leg with no length input needed at all, which is why §9's build order now puts this first, not last; **(b) fixed loop with the length as a fast runtime parameter** — settable during the 2-minute prep or immediately before `beginFastest` (e.g. via the STM console, §5.11 of the Task 1 doc, or a new short serial command), never a compile-time constant. | `STM_ROUTE_DEADLINE_S` (25) |
| `HOME` | `ACK,HOME` … `DONE,HOME` | drive the return lane, re-centre once past obstacle 1, stop inside the carpark. Distances from the STM's own odometer, reset at the first `SEEK`; no argument. **[RULE DELTA] Because touching the carpark wall disqualifies the run outright (§0 #2) while touching a goal obstacle only costs 10s, `HOME`'s calibration should be biased toward a centred, conservative entry over a fast one** — the asymmetry in penalty (disqualification vs. 10s) should be reflected in the asymmetry of caution during tuning. | `STM_HOME_DEADLINE_S` (40) |
| `S` | as today | stop anything, including any manoeuvre mid-way | — |

The Pi carries no course distances. `DONE,SEEK,<cm>` is parsed leniently
(`int(float(x))`, `None` on anything else) and only narrated; a missing
number is a log line, never a failure.

Hardware, from the component list: HC-SR04 forward (mounted below the 15 cm
obstacle top, level; its offset from the front edge reported to the Pi);
two Sharp GP2Y0A21YK IR rangers on the sides for the IR-terminated loop (a
block beside the car reads 25–35 cm; the "block present" threshold must be
~35 cm, since a wall 50 cm away still returns a reading); hall encoders for
the odometer. All read by the STM (handover §5.1).

### 3.2 Arrow recognition

Two sources, one interface (§5.1):

- **HTTP:** `POST {VISION_URL}/detect` as in Task 1, through its **own**
  `VisionClient` with `ARROW_HTTP_TIMEOUT_S` (2 s) — not Task 1's 10 s, which
  is longer than a whole read attempt. A `target` with `competition_id` 38
  or 39 is an arrow; anything else is "no arrow". Before the car moves, the
  run does a 1 s `GET /health`; if it fails the run is refused with
  `MSG,Vision server unreachable`, which turns a voided run into a
  fix-and-restart.
- **On-Pi TFLite:** `best_arrows.tflite` and `arrow-labels.json` from
  `image-rec/training/export_int8.py`, run with `tflite-runtime 2.5.0`
  (Buster/3.7/armv7l wheel from the Coral index) and OpenCV from apt.
  Jerick's `image-rec/rpi/inference/tflite_detector.py` is the reference
  implementation; it is **adapted into `rpi/arrow.py` with attribution**
  rather than imported, because his package is also named `rpi` and two
  top-level `rpi` packages cannot coexist in one interpreter. Strictly
  optional behind `configured` (model file present, `tflite_runtime`
  importable).

**[RULE DELTA §0 #3] Every read frame reaches the PC server, whichever
source decides.** `docs/rules/rules.md` Task 2 rule 8 and FAQ 16 require the RAW
image with its bounding box for each goal obstacle's recognised arrow, shown
on Android or PC at the end of the run — the same requirement Task 1 has for
its captures, and not satisfying it means the team does not qualify for
Task 2 at all, even if the run itself was flawless. The original design's
HTTP source already gets this for free, because `/detect` is the same
endpoint Task 1 uses and `pc_server/storage.py` persists every accepted
frame. The TFLite source does not: it decides locally and never talks to the
PC server. To close this, `ArrowSource.sightings()` gains a side effect: the
frame is always also handed to a `record(jpeg, object_id)` call that POSTs
it to `{VISION_URL}/detect` **for storage only** — fire-and-forget, not
awaited for the arrow decision, and its result (if any) is discarded, since
the decision still comes from whichever source is configured. This costs
one extra HTTP call per frame when running TFLite, off the decision's
critical path; a failed `record()` is logged and never fails the read. This
follows the existing pattern of `pc_server/storage.py` already writing
`raw/` and `annotated/` per accepted frame — no change needed there, only in
what calls it.

**Model gate, both sources.** `image-rec/training/train.py` passes no
`fliplr`, so Ultralytics' default of 0.5 mirrors half the left arrows into
right arrows (and vice versa) during training, for the Task 1 model and the
arrow model alike; validation does not catch it because the validation set
is not flipped. Both models must be trained with `fliplr: 0`, and released
only after a left/right confusion run at `T2_STOP_CM` (≥100 frames per
direction, ±15° yaw, lab and outdoor backgrounds) shows zero cross-errors at
the confidence floor. §9 items 4 and 5. **[RULE DELTA]** A misread arrow is
not merely a scoring loss here — `docs/rules/rules.md` FAQ 10 makes a wrong image
or wrong turn an **automatic disqualification** for Task 2, the same
severity as bulldozing. This raises the cost of the fliplr bug specifically
for Task 2 above what it already was for Task 1 (where a wrong ID is only
−10, not disqualification).

### 3.3 Tablet

Unchanged. Inbound `beginFastest` (now starts the run instead of being
forwarded) and `s`. Outbound `MSG` only — Task 2 has no obstacles or targets
on the tablet.

## 4. Architecture

New: `rpi/arrow.py` (sources + consensus + the read loop), `FastestRun` in
`rpi/run.py`, five encodings and four driver calls in `rpi/stm_driver.py`,
config keys, `fastest_factory` in `rpi/main.py`, a `--fake-arrows` CLI flag.
The dispatcher's `BeginFastest` branch starts the run when a factory is wired
and falls back to today's passthrough when it is not, so the manual-drive
milestone is unchanged.

Threads as before: the run thread executes; the STM reader feeds replies; the
camera is read synchronously on the run thread during the arrow read (the
vision worker is not used — Task 2 needs the verdict before moving). The
abort event is checked before every STM command and between frames; a
single frame is bounded by `ARROW_HTTP_TIMEOUT_S` or one TFLite inference,
so STOP is noticed within ~2 s worst case (the wheels stop sooner: the
controller sends `S` from the Bluetooth thread, as in Task 1).

## 5. Module specs

### 5.1 `rpi/arrow.py`

```python
@dataclass(frozen=True)
class Sighting:            # one arrow seen in one frame
    direction: str         # "left" | "right"
    confidence: float

class ArrowSource(ABC):
    def sightings(self, jpeg: bytes) -> List[Sighting]: ...   # never raises; [] on any failure
    def check(self) -> Optional[str]: ...   # None if usable now, else the reason (pre-flight)
    configured: bool
    describe: str          # "http http://10.0.0.2:4000" | "tflite rpi/models/best_arrows.tflite"

class HttpArrowSource(ArrowSource):      # own VisionClient at ARROW_HTTP_TIMEOUT_S; check() = GET /health
class TfliteArrowSource(ArrowSource):    # lazy-imports tflite_runtime, cv2, numpy; adapted from image-rec;
                                         # cv2.imdecode turns the JPEG into the BGR array the model wants
                                         # [RULE DELTA] also POSTs every frame to VISION_URL/detect for
                                         # storage (§3.2), fire-and-forget, independent of its own decision
class FakeArrowSource(ArrowSource):      # a scripted list of directions, one per read; tests and --fake-arrows

class Consensus:
    def __init__(self, required: int = 3, window: int = 5, min_confidence: float = 0.75)
    def observe(self, sightings: List[Sighting]) -> Optional[str]
        # the frame's best sighting (highest confidence >= min_confidence) or None;
        # keep the last `window` frames; decide a direction only when it appears
        # >= `required` times AND the other direction appears 0 times in the window
        # (a confident dissent blocks; it slides out within `window` frames)
    def reset(self) -> None

def read_arrow(camera, source, consensus, timeout_s, abort) -> Optional[str]
    # settle, then capture -> sightings -> observe, until a decision, the timeout or abort
```

`ARROW_IDS = {38: "right", 39: "left"}`, in one place.

### 5.2 `rpi/stm_driver.py` additions

- Encodings: `encode_seek(cm) -> "SEEK <cm>"`, `encode_round(n, side) -> "ROUND n L" | "ROUND n R"`,
  `encode_home() -> "HOME"`, `"RANGE"`. `is_motion` gains `SEEK ROUND HOME`.
- `StmDriver` gains `seek(cm, abort) -> Optional[int]` (travelled cm parsed
  leniently from `DONE,SEEK,<n>`; `None` if absent or malformed),
  `round(n, side, abort) -> None`, `home(abort) -> None`,
  `range_cm(abort) -> Optional[int]` (`RANGE`, awaited with
  `expect=("RANGE,", "ERR,")`; `None` on no reply — never fatal).
- **[RULE DELTA]** If the fixed-loop option (§3.1's `ROUND 2` row, option b)
  is used, `round(2, side, obstacle2_length_cm, abort)` gains an optional
  length parameter, encoded as a fourth token (`ROUND 2 R 45`) or sent as a
  preceding one-shot config command — exact shape is an open item for the
  STM team (§9 item 1), since it's new relative to the original proposal.
- `_deadline` maps by verb: `SEEK` → `STM_SEEK_DEADLINE_S`, `ROUND` →
  `STM_ROUTE_DEADLINE_S`, `HOME` → `STM_HOME_DEADLINE_S`. (`ROUND 2 R` has a
  digit as its second token; the mapping is by verb so it never falls into
  the straight formula.)
- `FakeStmDriver` gains `seek_distances: List[int]` (scripted, popped per
  seek; `0` models "already in range") and `range_readings: List[int]`;
  records lines as today; timed like the rest.

### 5.3 `rpi/config.py` additions

| Key | Default | |
|---|---|---|
| `ARROW_SOURCE` | `http` | `http` or `tflite` |
| `ARROW_HTTP_TIMEOUT_S` | `2` | per frame; the arrow source's own client |
| `ARROW_MODEL_PATH` / `ARROW_LABELS_PATH` | `rpi/models/best_arrows.tflite` / `rpi/models/arrow-labels.json` | tflite only |
| `ARROW_MIN_CONFIDENCE` | `0.75` | Jerick's default |
| `ARROW_REQUIRED` / `ARROW_WINDOW` | `3` / `5` | the vote |
| `ARROW_ATTEMPT_S` | `8` | one read attempt before a nudge |
| `ARROW_BUDGET_S` | `45` | all attempts for one arrow, then the run stops |
| `ARROW_NUDGE_CM` | `10` | the `BW` (or `FW`) between attempts |
| `T2_STOP1_CM` / `T2_STOP2_CM` | `30` / `30` | the `SEEK` arguments |
| `STM_SEEK_DEADLINE_S` / `STM_ROUTE_DEADLINE_S` / `STM_HOME_DEADLINE_S` | `20` / `25` / `40` | |
| **`T2_OBSTACLE2_LENGTH_CM`** **[RULE DELTA §0 #1]** | none — required if the fixed-loop `ROUND 2` option is used | **set right before `beginFastest`, from what the supervisor discloses after prep; never a value chosen before competition day** |

### 5.4 `FastestRun` (`rpi/run.py`)

`FastestRun(message: BeginFastest, stm, camera, send, source, consensus,
stop_cm: Tuple[int, int], attempt_s, budget_s, nudge_cm, settle_s)` — a
`BaseRun`, not a `_DrivingRun` (no planner pose to report). It reports its
own elapsed time from the start line as "Pi clock"; the tablet's clock and
the graders' are separate.

## 6. The run, step by step

Every line below is what the tablet sees.

```
RX  MSG,Fastest: arrow source http http://10.0.0.2:4000
                                  pre-flight: source.check(); stm.available
RX  MSG,Seeking obstacle 1
                                  > SEEK 30 ... < DONE,SEEK,87
RX  MSG,Obstacle 1 at 87 cm       (RANGE afterwards: logged; a MSG only if it disagrees, below)
RX  MSG,Reading arrow 1
                                  settle; capture / detect / vote until 3 agree with no dissent
RX  MSG,Arrow 1: LEFT
                                  > ROUND 1 L ... < DONE,ROUND
RX  MSG,Seeking obstacle 2
                                  > SEEK 30 ... < DONE,SEEK,0
RX  MSG,Obstacle 2 already in range
RX  MSG,Reading arrow 2
RX  MSG,Arrow 2: RIGHT
                                  > ROUND 2 R ... < DONE,ROUND
RX  MSG,Returning
                                  > HOME ... < DONE,HOME
RX  MSG,Parked in 41.3 s (Pi clock)
```

Rules applied at each step:

- **Pre-flight, before anything moves:** the source's `check()` (for HTTP, a
  1 s `/health`) and `stm.available`. Failure: `MSG,Vision server
  unreachable` / `MSG,Arrow source not configured` / `MSG,STM unavailable`,
  nothing sent to the STM. **[RULE DELTA] Pre-flight never drives the wheels
  — this matters more now than in the original, because moving the robot
  outside the carpark during prep-time calibration is an automatic
  disqualification (`docs/rules/rules.md` FAQ 9); confirming this stays true is
  worth a one-line test assertion (§8).**
- **Abort check** before every STM command and between frames; on STOP the
  run sends `MSG,Stopped` and ends (the controller has already sent `S`).
- **Arrow not decided within `ARROW_ATTEMPT_S`:** nudge and try again —
  `BW 10` normally, `FW 5` if `RANGE` reads more than `stop_cm + 10` — then
  reset the vote and read again, until `ARROW_BUDGET_S` is spent; then
  `MSG,Arrow 1 not readable - stopped` and the run ends. Waiting is cheaper
  than guessing; a guess voids the run and the retry is shared with Task 1.
  **[RULE DELTA] A wrong turn is an automatic disqualification here
  (`docs/rules/rules.md` FAQ 10), not just an invalid run as the original phrased
  it — the same conclusion, stated with the rules' own severity.**
  Each nudge is narrated: `MSG,Arrow 1: no vote, nudging back 10 cm`.
- **`DONE,SEEK,0`:** narrated as "already in range", not "at 0 cm".
- **A short seek followed by no arrow** (`travelled < 50`): the first nudge
  is forward, and the message adds "possible false stop".
- **`RANGE` disagrees with the stop distance** (reading > `stop_cm + 15`, or
  no reading): `MSG,Warning: sensor reads 52 cm`; the run continues — the
  arrow read decides whether it was really in front of the obstacle.
- **STM `ERR,*` or silence:** as Task 1, `MSG,Aborted at SEEK 30: ERR,TIMEOUT`.
- **Camera failure mid-read:** counts as a frame with no sighting; the
  attempt timer decides.

## 7. Error table (additions to Task 1 §7)

| Condition | Who notices | STM action | Tablet sees |
|---|---|---|---|
| vision server down at start | run pre-flight | none | `Vision server unreachable` |
| arrow source not configured | run pre-flight | none | `Arrow source not configured` |
| STM link down at start | run pre-flight | none | `STM unavailable` |
| no vote in one attempt | run | `BW 10` / `FW 5` | `Arrow n: no vote, nudging back 10 cm` |
| no vote within the budget | run | none | `Arrow n not readable - stopped` |
| `DONE,SEEK` lacks a distance | driver | none | nothing (logged) |
| `RANGE` far from `stop_cm` | run | none | `Warning: sensor reads N cm`, continues |
| STOP during any command | controller | `S`, resync | `Stopped` |
| STM `ERR`/silence | driver | `S`, resync | `Aborted at <cmd>: <reply>` |
| camera failure mid-read | run | none | counts as an empty frame |
| **[RULE DELTA] contact with a goal obstacle** | judged, not software-detected | — | **+10s penalty per distinct contact — the run continues** (`docs/rules/rules.md` FAQ 5, 7) |
| **[RULE DELTA] contact with the carpark wall** | judged, not software-detected | — | **disqualification — not a timing penalty** (`docs/rules/rules.md` rule 6, FAQ 6). No software change follows from this row directly; it's the reason `HOME`'s tuning (§3.1) should trade a little speed for certainty near the carpark, more than any other manoeuvre in this run |
| **[RULE DELTA] wrong arrow read or wrong turn taken** | judged, not software-detected | — | **automatic disqualification** (`docs/rules/rules.md` FAQ 10) — the reason the nudge-and-retry loop above waits rather than guesses |

## 8. Testing

Unit, no hardware, as Task 1:

- `test_arrow.py`: id mapping; consensus (3 in the window with no dissent
  decides; one confident dissent blocks; it slides out; threshold; reset);
  `read_arrow` decides / times out / aborts; a **blocking** fake source
  proves abort is honoured within one frame and no frame outlives
  `ARROW_HTTP_TIMEOUT_S`; the HTTP source maps 38/39, swallows errors and
  reports `check()` from `/health`; the TFLite source reports unconfigured
  when the model file is missing (the detector itself is exercised only
  when `tflite_runtime` is importable — skipped otherwise). **[RULE DELTA]
  the TFLite source's `record()` call is exercised with a stubbed session:
  every frame it reads is also POSTed for storage, independent of its own
  decision, and a failed `record()` never raises or blocks the read.**
- `test_stm_driver.py` / `test_stm_serial.py`: the five encodings;
  `DONE,SEEK,87`, `DONE,SEEK,0`, `DONE,SEEK,abc`, `DONE,SEEK`; `RANGE`
  awaited by its own prefix, reply and no-reply; `SEEK` → `ERR,TIMEOUT`;
  `_deadline("ROUND 2 R")` is the route deadline.
- `test_fastest_run.py`: the §6 transcript line by line with scripted
  distances and arrows; each row of §7; the nudge loop (no vote → `BW 10` →
  vote lands; budget exhausted → stopped; short seek → forward nudge);
  **[RULE DELTA] pre-flight never calls a driving method on the fake STM —
  assert `FakeStmDriver.sent` is empty until the first `SEEK`, so a future
  change can't accidentally move the robot during what must stay
  carpark-safe prep-time behaviour.**
- `test_dispatcher.py`: `beginFastest` starts the run when the factory is
  wired, passes through when it is not.
- `test_main.py`: `build()` wires the factory; `http` is the default source;
  `--fake-arrows left,right` installs a `FakeArrowSource`.

On the Pi, in this order: `RANGE` and `SEEK 30` by hand over CoolTerm; the
full sequence with `--fake-arrows` on the real car (no camera, no WiFi —
this is the STM team's rehearsal); the run with the real camera against the
PC server, an arrow printout in front of the car; the on-Pi source once the
model passes its gate. Record the confusion run in `image-rec/docs/calibration.md`.

## 9. Open items

| # | Item | Owner | Blocks |
|---|---|---|---|
| 1 | Confirm `RANGE / SEEK / ROUND / HOME`, the `SEEK` semantics (3-reading debounce, `DONE,SEEK,0`, ~200 cm cap) and bare `HOME` on the STM odometer. **[RULE DELTA] Also confirm how `ROUND 2`'s obstacle-2 length is set at runtime if the fixed-loop option is used (§3.1, §5.2) — a new question, since the original assumed a pre-measured constant** | STM | driver encodings |
| 2 | `BW <cm>` — also a Task 2 blocker (`ROUND 1` from a 30 cm standoff, the nudge) | STM | everything after the first read |
| 3 | Sensor mounting: ultrasonic forward, below 15 cm, offset reported; IRs sideways **[RULE DELTA] elevated from "v2" to first-priority, since the IR-terminated loop needs no obstacle-2 length input at all (§0 #1, §3.1)** | STM | nothing on the Pi |
| 4 | `best.pt` for the PC server, trained with `fliplr: 0`, past the confusion gate | CV | any real arrow read |
| 5 | `best_arrows.tflite` + labels under the same gate, or the decision to skip the separate model | CV | the on-Pi source |
| 6 | Obstacle 2's width (measure the prop at setup); the return-lane offset that clears obstacle 1 and still lets `HOME` re-centre into the 60 cm opening. **[RULE DELTA] "measure the prop at setup" now reads as "read the dimension the supervisor discloses after prep" — see §0 #1** | STM + course staff | `ROUND 2`, `HOME` |
| 7 | Decision date for the contingency (§2): if the STM manoeuvres are not driveable by then, the Pi composes them from primitives. **[RULE DELTA] Given #1 and #3 above, this decision should also settle whether `ROUND 2` ships as IR-terminated (needs no length) or fixed-loop-with-runtime-parameter (needs the STM's answer to open item 1) before the competition, not after** | all | which implementation of the four manoeuvre calls ships |
