# RPi → STM handover: what the RPi sends, what it expects, what it still needs

For the STM team, from the RPi side. Written against `rpi/stm_driver.py`, which
is the only file on the Pi that speaks to the board, and against your
"STM32 UART command reference". Sections 1–3 are what the Pi does today.
Section 4 is the list of things Task 1 still needs from the firmware. Section 5
is a **proposal** for Task 2 — nothing there is agreed yet; counter-propose
freely, the Pi side adapts to whatever names and shapes you pick.

---

## 1. Link and framing

| | |
|---|---|
| Port | `/dev/ttyACM0` (USB CDC), 115200 baud — `RPI_STM_PORT` / `RPI_STM_BAUD` if it moves |
| Direction Pi → STM | ASCII, one command per line, terminated `\n`, no padding, one space between verb and argument: `FW 30`, `TL 90` |
| Direction STM → Pi | ASCII lines, `\n` or `\r\n` terminated; blank lines ignored; anything the Pi is not waiting for is logged and skipped |
| Concurrency | **One command in flight at a time.** The Pi never sends a second motion command until the first has completed or errored. It does not need `ERR,BUSY` to avoid this — but see 4.4 for why it would still like it. |
| Startup | `PING` → `PONG`, then any configured trims (`MA <pct>`, `MB <pct>`, `AS <n>`), each awaited. The Pi waits up to 5.5 s for the first `PONG`; if it never comes it keeps retrying every 3 s in the background and the tablet sees `STM disconnected`. |
| Link loss | If the port disappears or a write fails, the Pi closes and reopens it every 3 s and re-runs the startup handshake. The tablet is told `STM connected` / `STM disconnected`. |

## 2. Reply model (confirmed 2026-09-17: ACK on receipt, DONE on completion)

For every **motion** command (`FW BW TL TR BL BR PL PR`, and the Task 2 ones
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
| `ACK,<verb>` | The verb echoed exactly as sent (`ACK,FW` for `FW 30`). Must arrive within **1 s** or the Pi treats the command as dropped (see "silence" below). |
| `DONE,<verb>` | Same verb. Deadline: straights **cm ÷ 10 + 5 s** (so `FW 30` gets 8 s, `FW 100` 15 s); arcs and pivots **10 s**. `DONE,FW 30` also matches — the Pi matches on the prefix `DONE,FW` — so you may append data after the verb if useful. A bare `DONE` does **not** match. |
| `ERR,...` on receipt | `ERR,RANGE`, `ERR,GYRO`, `ERR,BUSY`, `ERR,UNKNOWN` — the Pi stops the run and tells the tablet `Aborted at TL 90: ERR,GYRO`. |
| `ERR,...` instead of `DONE` | `ERR,TIMEOUT` (or any `ERR,`) after the `ACK` ends the run the same way. |
| Non-motion commands | `PING`, `F`, `B`, `S`, `MA/MB/AS <n>`: one reply line (`PONG` / `ACK,F` / `ACK,S` …) within 1 s (`PING`: 2 s). **Please do not send `DONE,F` / `DONE,B`** for the jogs; if you do, the Pi skips them harmlessly, but they clutter the log. |
| Data lines | `ENC,...`, `MA,<pct>` etc. are recognised as replies only when the Pi asked; unsolicited ones are logged and skipped. |
| Silence | No `ACK` within 1 s, or no `DONE` within the deadline: the Pi sends `S`, discards everything you say for 0.5 s, sends `PING` and waits 2 s for `PONG`, then reports the command as failed. It never assumes a silent command ran. |

**`S` (stop) is special.** The Pi may send it at any moment, from a different
thread, while a motion command is still in flight — that is the tablet's STOP
button or a run being aborted. After `S` the Pi does the same drain-and-`PING`
resync as above. So it does not matter what the interrupted move replies —
`DONE,FW`, `ERR,STOPPED`, or nothing — as long as `PING` still gets `PONG`
afterwards. What the Pi needs from `S` is that **the motors are off within a
few hundred milliseconds and the next motion command is accepted normally**.

## 3. Commands the Pi uses today

Everything below is already in your reference except `BW`, marked ★.

| Pi sends | When | Argument |
|---|---|---|
| `PING` | startup, after every stop, after every silence | — |
| `F` / `B` | tablet F / B buttons | — (500 ms jog) |
| `S` | tablet STOP, run abort, any silence | — |
| `TL d` `TR d` `BL d` `BR d` | tablet FL/FR/BL/BR buttons: `d` = 45. Planner arcs: `d` = 90 (45 if the planner's diagonal mode is ever switched on) | degrees |
| `FW cm` | planner straights | **5–200 in steps of 5** (planner output); most are 5–100 |
| `BW cm` ★ | planner reverse straights — **every Task 1 segment after the first starts with one** | as `FW` |
| `MA p` `MB p` `AS n` | startup only, and only if set in the Pi's config | as your reference |
| `PL d` `PR d` | not used yet — the planner's pivot mode is off, and the Pi will only learn to send them when it is switched on. Keep them. | degrees |

Tablet mapping, for reference: FL → `TL 45`, FR → `TR 45`, BL → `BL 45`,
BR → `BR 45`. Tell us if BL/BR come out mirrored on the real car; it is a
two-literal swap on the Pi.

## 4. Still needed for Task 1 (and the A.5 face search)

Numbered so you can answer by number.

1. **`BW <cm>`** — reverse straight, encoder closed-loop like `FW`, same reply
   model. Without it a Task 1 run stops at its first reverse. This is the
   blocker.
2. **`FW`/`BW` range 5–200** — the reference says 80–120 (the A.3 test band).
   The planner emits 5 cm multiples from 5 up; the trial runs produced `FW 5`,
   `FW 10`, `FW 85`. Anything outside your range must reply `ERR,RANGE` (it
   already does), never move a different distance.
3. **Exact completion strings** — please confirm the line is literally
   `DONE,<verb>` with the verb as sent (`DONE,FW`, `DONE,BL`, …). One real
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

7. **`US` → `US,<cm>`** — one forward ultrasonic reading, any time. The Pi
   would read it at every capture pose and nudge the car with a short
   `FW`/`BW` so the camera is at the trained range before photographing,
   instead of wherever dead reckoning left it. Please tell us the sensor's
   offset from the front edge of the car.
8. **Obstacle guard on `FW`/`BW`** — abort the move with `ERR,OBSTACLE` if the
   ultrasonic (or the IR, if it is a near-object switch) sees something
   closer than a threshold you pick (~8 cm). The Pi already treats any `ERR`
   as "stop the run", so this costs nothing on our side and turns a slipped
   wheel into an aborted run instead of a pushed obstacle.

## 5. Task 2 — proposal (nothing here is agreed yet)

### 5.1 What the rules require of the hardware

Obstacle 1 is 60–150 cm from the carpark and obstacle 2 another 60–150 cm on:
**the approach must be sensor-driven**. The rules allow camera, IR or
ultrasonic. The component list gives us one HC-SR04 ultrasonic (with the
1 kΩ / 2.2 kΩ pair for its Echo divider) and two Sharp GP2Y0A21YK IR rangers
(10–80 cm, analog, with brackets and the ADC cable); the firmware just does
not read them yet. The layout we are designing the Pi side around:

- **HC-SR04 facing forward** — the approach: it sees obstacle 1 from anywhere
  in the 60–150 cm band and tells you when to stop. SC2104/CE3002 Ex #1
  Practice #4 is the driver (Trig `B15`, Echo `C7`, timer pulse + input
  capture, distance = pulse × 343 m/s ÷ 2).
- **One IR on each side, facing outward** — while going round obstacle 2 (the
  big one), the side IR sees the block and then stops seeing it, which is
  when the car has cleared its end and can turn back. That makes the loop
  sensor-terminated instead of a guess about the block's width, and the
  same reading is a cheap "too close to something" guard.
- **Encoders** for the distance home (`ENC` already exists).

If you would rather mount them differently, say so — the commands in 5.3 are
the same either way.

If the sensors cannot be made to work in time, the Pi can fall back to a
camera-driven creep (short `FS` steps with a photo between each, stopping on
the arrow's apparent size). It needs nothing from you but is slow — 10 s or
more per approach on a task scored by time — so it is the fallback, not the
plan.

### 5.2 Split of work

The Pi would run the sequence and make the arrow decision; the STM would own
every manoeuvre, because that is where the calibration lives:

```
Pi: SK 30          STM: drive until obstacle ≤ 30 cm ahead, DONE,SK,<cm travelled>
Pi: (photograph, decide LEFT or RIGHT)
Pi: AL 1 / AR 1    STM: go round obstacle 1 on that side, back onto the centre line, DONE
Pi: SK 30          STM: as above, DONE,SK,<cm>
Pi: (photograph, decide)
Pi: AL 2 / AR 2    STM: round obstacle 2 on that side, loop behind it, come back
                        past it facing the carpark, DONE
Pi: HM <cm>        STM: drive <cm> back and stop inside the carpark, DONE
```

The alternative — the STM runs the whole thing after one start command and
asks the Pi for the arrow mid-run — needs the STM to send unsolicited lines
and the Pi to answer them, which neither side has today, and it takes STOP
and the tablet's narration away from the Pi. We would rather not.

### 5.3 Proposed commands

Names are placeholders chosen to avoid your existing `SL/SR/LL/RR/AS`. Any
two-letter verbs you prefer are fine; the `ACK`/`DONE` shape is what matters.

| Command | Reply | What it does |
|---|---|---|
| `US` | `US,<cm>` | One ultrasonic reading, any time, even mid-move (data line, like `ENC`). Lets the Pi sanity-check the sensor before a run. |
| `SK <cm>` | `ACK,SK` … `DONE,SK,<travelled_cm>` | Drive forward at Task 2 speed until the sensor reads ≤ `<cm>`, then stop. Report the distance actually travelled (encoders) after the verb — the Pi needs it to compute the way home. `ERR,TIMEOUT` if nothing is seen within some cap (say 250 cm). |
| `AL <n>` / `AR <n>` | `ACK,AL` … `DONE,AL` | Go round obstacle `n` (1 or 2) on the left / right. For 1: an S-curve that ends back on the centre line, heading forward, a known distance past the obstacle. For 2: round the side, loop behind, back past the obstacle on the far side, ending on the centre line heading toward the carpark. Both are fixed calibrated manoeuvres; the Pi never sends angles or speeds for them. |
| `HM <cm>` | `ACK,HM` … `DONE,HM` | Drive `<cm>` back toward the carpark and stop. The Pi computes `<cm>` from the two `SK` travel reports plus the net displacement of `AL/AR 1` and `AL/AR 2`, which you give us as constants. (Alternative: the STM keeps its own odometer since the first `SK` and `HM` takes no argument — say which you prefer.) |

Two things to keep in mind while calibrating: the arrow must be readable from
where `SK` stops (25–40 cm is where the Task 1 camera work sits; we will
confirm with the CV side), and every obstacle contact costs 10 s, so the
manoeuvres should trade a little time for clearance.

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
> FW 35
< ACK,FW
< DONE,FW
> TR 90
< ACK,TR
< DONE,TR
> BW 5
< ACK,BW
< DONE,BW
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
