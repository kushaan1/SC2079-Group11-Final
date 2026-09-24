# RPi → STM handover: what the RPi sends, what it expects, what it still needs

For the STM team, from the RPi side. Written against `rpi/stm_driver.py`, which
is the only file on the Pi that speaks to the board, and against your
"STM32 UART command reference". Sections 1–3 are what the Pi does today.
Section 4 is the list of things Task 1 still needs from the firmware. Section 5
is a **proposal** for Task 2 — nothing there is agreed yet; counter-propose
freely, the Pi side adapts to whatever names and shapes you pick.

**Pulled unchanged from `shuenwei-rpi` on 2026-09-25**, then corrected in two
places (marked inline) against the official rules and against `main.c` read
directly — see `docs/superpowers/specs/2026-09-22-rpi-task2-design-v2.md` §0
for the full reasoning if anything here still looks off.

---

## 1. Link and framing

| | |
|---|---|
| Port | `/dev/ttyACM0` (USB CDC), 115200 baud — `RPI_STM_PORT` / `RPI_STM_BAUD` if it moves |
| Direction Pi → STM | ASCII, one command per line, terminated `\n`, no padding, one space between verb and argument: `FS 30`, `TL 90` |
| Direction STM → Pi | ASCII lines, `\n` or `\r\n` terminated; blank lines ignored; anything the Pi is not waiting for is logged and skipped |
| Concurrency | **One command in flight at a time.** The Pi never sends a second motion command until the first has completed or errored. It does not need `ERR,BUSY` to avoid this — but see 4.4 for why it would still like it. |
| Startup | `PING` → `PONG`, then any configured trims (`MA <pct>`, `MB <pct>`, `AS <n>`), each awaited. The Pi waits up to 5.5 s for the first `PONG`; if it never comes it keeps retrying every 3 s in the background and the tablet sees `STM disconnected`. |
| Link loss | If the port disappears or a write fails, the Pi closes and reopens it every 3 s and re-runs the startup handshake. The tablet is told `STM connected` / `STM disconnected`. |

## 2. Reply model (confirmed 2026-09-17: ACK on receipt, DONE on completion)

For every **motion** command (`FS BS TL TR BL BR PL PR`, and the Task 2 ones
in §5), the Pi waits for exactly this sequence:

```
Pi  → STM   TL 90
STM → Pi    ACK,TL                within 1 s of the line arriving
            ... motion ...
STM → Pi    DONE,TL               when the wheels have stopped
Pi  → STM   <next command>
```

| Rule | Detail |
|---|---|
| `ACK,<verb>` | The verb echoed exactly as sent (`ACK,FS` for `FS 30`). Must arrive within **1 s** or the Pi treats the command as dropped (see "silence" below). |
| `DONE,<verb>` | Same verb. Deadline: straights **cm ÷ 10 + 5 s** (so `FS 30` gets 8 s, `FS 100` 15 s; the 10 cm/s is the Pi's `RPI_STM_STRAIGHT_CM_PER_S` — tell us the real `FS` speed and we set it); arcs and pivots **10 s**. `DONE,FS 30` also matches — the Pi matches on the prefix `DONE,FS` — so you may append data after the verb if useful. A bare `DONE` does **not** match. |
| `ERR,...` on receipt | `ERR,RANGE`, `ERR,GYRO`, `ERR,BUSY`, `ERR,UNKNOWN` — the Pi stops the run and tells the tablet `Aborted at TL 90: ERR,GYRO`. |
| `ERR,...` instead of `DONE` | `ERR,TIMEOUT` (or any `ERR,`) after the `ACK` ends the run the same way. |
| Non-motion commands | `PING`, `F`, `B`, `S`, `MA/MB/AS <n>`: one reply line (`PONG` / `ACK,F` / `ACK,S` …) within 1 s (`PING`: 2 s). **Please do not send `DONE,F` / `DONE,B`** for the jogs; if you do, the Pi skips them harmlessly, but they clutter the log. |
| Data lines | `ENC,...`, `MA,<pct>` etc. are recognised as replies only when the Pi asked; unsolicited ones are logged and skipped. |
| Silence | No `ACK` within 1 s, or no `DONE` within the deadline: the Pi sends `S`, discards everything you say for 0.5 s, sends `PING` and waits 2 s for `PONG`, then reports the command as failed. It never assumes a silent command ran. |

**`S` (stop) is special.** The Pi may send it at any moment, from a different
thread, while a motion command is still in flight — that is the tablet's STOP
button or a run being aborted. After `S` the Pi does the same drain-and-`PING`
resync as above. So it does not matter what the interrupted move replies —
`DONE,FS`, `ERR,STOPPED`, or nothing — as long as `PING` still gets `PONG`
afterwards. What the Pi needs from `S` is that **the motors are off within a
few hundred milliseconds and the next motion command is accepted normally**.

## 3. Commands the Pi uses today

Everything below is already in your reference except `BS`, marked ★.

| Pi sends | When | Argument |
|---|---|---|
| `PING` | startup, after every stop, after every silence | — |
| `F` / `B` | tablet F / B buttons | — (500 ms jog) |
| `S` | tablet STOP, run abort, any silence | — |
| `TL d` `TR d` `BL d` `BR d` | tablet FL/FR/BL/BR buttons: `d` = 45. Planner arcs: `d` = 90 (45 if the planner's diagonal mode is ever switched on) | degrees |
| `FS cm` | planner straights (the slow straight) | **5–200 in steps of 5** (planner output); most are 5–100 |
| `BS cm` ★ | planner reverse straights — **every Task 1 segment after the first starts with one** | as `FS` |
| `FW cm` `BW cm` | never sent by a run — only if someone types them in the Pi's STM console. Keep them. | as `FS` |
| `MA p` `MB p` `AS n` | startup only, and only if set in the Pi's config | as your reference |
| `PL d` `PR d` | not used yet — the planner's pivot mode is off, and the Pi will only learn to send them when it is switched on. Keep them. | degrees |

Tablet mapping, for reference: FL → `TL 45`, FR → `TR 45`, BL → `BL 45`,
BR → `BR 45`. Tell us if BL/BR come out mirrored on the real car; it is a
two-literal swap on the Pi.

## 4. Still needed for Task 1 (and the A.5 face search)

Numbered so you can answer by number.

1. ~~**`BS <cm>`** — reverse straight...~~ **Confirmed built, 2026-09-25** by
   reading `main.c` directly: `Drive_BackwardCm` exists with its own
   calibration (`BW_COUNTS_PER_100CM = 7418`, dated 2026-09-20, a 12-run
   tape-measure calibration). No longer a blocker.
2. **`FS`/`BS` range 5–200** — the reference says 80–120 (the A.3 test band).
   The planner emits 5 cm multiples from 5 up; the trial runs produced `FS 5`,
   `FS 10`, `FS 85`. Anything outside your range must reply `ERR,RANGE` (it
   already does), never move a different distance.
3. **Exact completion strings** — please confirm the line is literally
   `DONE,<verb>` with the verb as sent (`DONE,FS`, `DONE,BL`, …). One real
   transcript of a `TL 90` from your terminal, bytes as they come off the UART,
   would let us pin the driver test to your strings.
4. **`ERR,BUSY` instead of silence** when a motion command arrives mid-move.
   The Pi never does this deliberately, but if it ever happens (a stale line
   after a reconnect), a reply lets the Pi recover in 1 s instead of waiting
   out a 15 s deadline.
5. **After `S`** — optional, but say which you do: the interrupted command
   replies `ERR,STOPPED`, replies `DONE,<verb>`, or replies nothing. All three
   work (§2); we just want the log to be readable.
6. **Turn radii at the lock you actually use** — not a firmware item, but the
   planner's `TURN_RADIUS_CM` (FL 39, FR 40, BL 37, BR 39 cm, last year's car)
   needs measuring on this car at competition speed, per direction. Joint with
   Kejun.

Optional, but cheap and they make Task 1 recognitions more reliable — the car
already has the sensors, only the firmware has to expose them:

7. **`RANGE` → `RANGE,<cm>`** — one forward ultrasonic reading, any time. The Pi
   would read it at every capture pose and nudge the car with a short
   `FS`/`BS` so the camera is at the trained range before photographing,
   instead of wherever dead reckoning left it. Please tell us the sensor's
   offset from the front edge of the car.
8. **Obstacle guard on `FS`/`BS`** — abort the move with `ERR,OBSTACLE` if the
   ultrasonic (or the IR, if it is a near-object switch) sees something
   closer than a threshold you pick (~8 cm). The Pi already treats any `ERR`
   as "stop the run", so this costs nothing on our side and turns a slipped
   wheel into an aborted run instead of a pushed obstacle.

## 5. Task 2 — proposal (nothing here is agreed yet)

### 5.1 The course and the sensors

Obstacle 1 is 60–150 cm from the carpark and obstacle 2 (the bigger block)
another 60–150 cm on, both on the carpark's centre line. The carpark is a
60 × 60 cm U with walls on three sides, so the car must come home centred to
get in. Any wall beyond obstacle 2 is at least 50 cm from the block's edge.
**The approach must be sensor-driven** (rules allow camera, IR or
ultrasonic). The component list gives us one HC-SR04 ultrasonic (with the
1 kΩ / 2.2 kΩ pair for its Echo divider) and two Sharp GP2Y0A21YK IR rangers
(10–80 cm, analog, with brackets and the ADC cable); the firmware just does
not read them yet. The layout we are designing the Pi side around:

- **HC-SR04 facing forward, mounted below the 15 cm obstacle top, level.**
  The approach: it sees obstacle 1 from anywhere in the 60–150 cm band and
  tells you when to stop. SC2104/CE3002 Ex #1 Practice #4 is the driver
  (Trig `B15`, Echo `C7`, timer pulse + input capture, distance =
  pulse × 343 m/s ÷ 2). Please tell us its offset from the car's front edge.
- **Encoders** for the distances: keep them on the STM (5.3, `HOME`).
- **One IR on each side, facing outward — second stage, not first.** While
  going round obstacle 2, the side IR sees the block (25–35 cm) and then
  stops seeing it, which is when the car has cleared its end. Note a wall
  50 cm away still returns a reading, so "block present" must be a
  threshold around 35 cm, not "any reading". Build the loop with the block's
  width as a constant first (we measure the prop at setup); make it
  IR-terminated once the rest works.

If the sensors cannot be made to work in time, the Pi can fall back to a
camera-driven creep (short `FS` steps with a photo between each, stopping
on the arrow's apparent size). It needs nothing from you but is slow —
10 s or more per approach on a task scored by time — so it is the fallback,
not the plan.

### 5.2 Split of work

The Pi runs the sequence and makes the arrow decision; the STM owns every
manoeuvre, every sensor and the odometer, because that is where the
calibration lives:

```
Pi: SEEK 30        STM: drive until the ultrasonic reads ≤ 30 cm (3 readings in a row), stop,
                        DONE,SEEK,<cm travelled>
Pi: (photograph, decide LEFT or RIGHT; if no decision, BS 10 and try again)
Pi: ROUND 1 L/R    STM: round obstacle 1 on that side, back onto the centre line facing onward, DONE
Pi: SEEK 30        STM: as above — DONE,SEEK,0 straight away if already inside 30 cm
Pi: (photograph, decide)
Pi: ROUND 2 L/R    STM: round obstacle 2 on that side, loop behind it, come back on the far side
                        and end on the RETURN LANE (offset from the centre line, away from the
                        arrow side) facing home, DONE
Pi: HOME           STM: drive the lane past obstacle 1, re-centre, stop inside the carpark, DONE
```

**The home leg is not a straight line down the middle** — obstacle 1 sits on
the centre line. The car comes back on a lane offset to the side, passes
obstacle 1 on the outside, then re-centres to enter the 60 cm opening. To
clear a 10 cm obstacle with margin the lane must be ~25 cm off centre,
which is more than the carpark opening tolerates, so the re-centre is a
real manoeuvre timed from obstacle 1's position — which you know from your
encoders and we do not. That is why `HOME` takes no argument.

**`ROUND 1` has a forward budget.** Obstacle 2 can be as little as 60 cm
behind obstacle 1. A 25 cm lane change at this car's turn radius eats
35–55 cm of forward travel each way, so from a 30 cm standoff `ROUND 1`
probably needs to start with a short reverse, and it must end less than
(60 − 30 − ultrasonic offset) cm past obstacle 1's rear face, or `SEEK` for
obstacle 2 has nothing to do. This makes `BS` a Task 2 blocker as well as a
Task 1 one.

The alternative — the STM runs the whole thing after one start command and
asks the Pi for the arrow mid-run — needs the STM to send unsolicited lines
and the Pi to answer them, which neither side has today, and it takes STOP
and the tablet's narration away from the Pi. We would rather not.

### 5.3 Proposed commands

Verbs are words rather than two letters so nothing collides with your
existing `SL/SR/LL/RR/AS`; all fit the 31-byte line. `ROUND` takes two
arguments, which is new for your parser. The `ACK`/`DONE` shape is what
matters; respell freely.

| Command | Reply | What it does |
|---|---|---|
| `RANGE` | `RANGE,<cm>` | One ultrasonic reading, any time, even mid-move (data line, like `ENC`). Lets the Pi sanity-check the sensor before a run and after each stop. |
| `SEEK <cm>` | `ACK,SEEK` … `DONE,SEEK,<travelled_cm>` | Drive forward at Task 2 speed until the ultrasonic reads ≤ `<cm>` on **three consecutive readings** (one spurious echo must not stop the car), then stop. If already inside `<cm>`, reply `DONE,SEEK,0` at once. `ERR,TIMEOUT` if nothing is seen within ~200 cm. The travelled distance (encoders) after the verb is for our log; you keep the number that matters. |
| `ROUND 1 <L\|R>` | `ACK,ROUND` … `DONE,ROUND` | Go round obstacle 1 on the left (`L`) or right (`R`): an S-curve that ends back on the centre line, heading forward, within the budget above. Fixed and calibrated; the Pi never sends angles or speeds. |
| `ROUND 2 <L\|R>` | `ACK,ROUND` … `DONE,ROUND` | Go round obstacle 2 on that side, loop behind it, come back on the far side, and end on the return lane heading home. **[corrected 2026-09-25]** The official rules say obstacle 2's dimension is disclosed only after the 2-minute prep, right before the run — not something either of us can pre-measure and flash. So the block's width can't be a compiled-in constant. Either: the side IR ends the along-the-block leg (needs no width input at all — now our preferred first version), or the width is a fast runtime parameter set right before `beginFastest`. |
| `HOME` | `ACK,HOME` … `DONE,HOME` | Drive the return lane, re-centre once past obstacle 1, stop inside the carpark. Distances from your odometer, reset at the first `SEEK`. No argument. |

`S` must abort any of these mid-way, and the next command must be accepted
after the usual `PING`/`PONG` — we will test that first.

Two things to keep in mind while calibrating: the arrow must be readable
from where `SEEK` stops (25–40 cm is where the Task 1 camera work sits; we
will confirm with the CV side), and every obstacle contact costs 10 s, so
the manoeuvres should trade a little time for clearance.

**Suggested build order:** `BS` → ultrasonic + `RANGE` + `SEEK` → fixed
`ROUND 1`, `ROUND 2`, `HOME` (with the block's width as a constant) → side
IRs and the IR-terminated loop last. The Pi has a `--fake-arrows` mode so
you can rehearse the whole sequence on the real car with no camera and no
WiFi as soon as the commands exist.

### 5.4 `beginFastest`

Today the Pi forwards the tablet's `beginFastest` to you as a bare line, which
your firmware answers `ERR,UNKNOWN`. Once Task 2 exists on the Pi that line
stays on the Pi and the sequence in 5.2 is what you see. No firmware work
needed for it.

## 6. A session you can replay from CoolTerm

This is the Pi's Task 1 traffic for one segment, so you can check the
firmware against it by hand. `>` is the Pi, `<` is the STM.

```
> PING
< PONG
> FS 35
< ACK,FS
< DONE,FS
> TR 90
< ACK,TR
< DONE,TR
> BS 5
< ACK,BS
< DONE,BS
> TL 90
< ACK,TL
< DONE,TL
> S              (tablet STOP pressed mid-run)
< ACK,S
> PING           (0.5 s later)
< PONG
```

The Pi's own scripted version of this is `rpi/tests/test_stm_serial.py`; the
DONE-model exchange is `test_done_completion_model_waits_for_ack_then_done`.

## 7. Where things are

- Driver: `rpi/stm_driver.py` (`SerialStmDriver`). Timings: `rpi/config.py`
  (`RPI_STM_*` environment variables override them at runtime, so a slower
  motion does not need a code change on the Pi — just tell us).
- Spec for the whole Pi program: `docs/superpowers/specs/2026-09-17-rpi-task1-design.md`, §3.2 is your contract.
- Tablet ↔ Pi protocol, for the tokens behind F/B/FL/FR/BL/BR: `docs/protocol.md` §1.2.
