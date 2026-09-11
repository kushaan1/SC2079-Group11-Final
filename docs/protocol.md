# Bluetooth protocol — tablet ↔ RPi

Every message the Android controller sends, and every message it understands.
Generated from the implementation, not from the briefing slides: the authority
for outbound formats is
[`protocol/Encoder.kt`](../android/app/src/main/java/com/mdp/grp11/protocol/Encoder.kt),
for inbound
[`protocol/Decoder.kt`](../android/app/src/main/java/com/mdp/grp11/protocol/Decoder.kt),
and for the token vocabulary
[`config/Config.kt`](../android/app/src/main/java/com/mdp/grp11/config/Config.kt).

Background on why the formats are what they are is in
[`design-decisions.md`](design-decisions.md).

---

## 0. Link and framing

| | |
|---|---|
| Profile | Bluetooth Classic **SPP / RFCOMM** |
| Service UUID | `00001101-0000-1000-8000-00805F9B34FB` |
| Service name (when the tablet listens) | `MDP-GRP11` |
| Roles | Tablet connects **out** to the RPi (RPi runs `rfcomm listen`), or **waits** for an inbound connection (used by the AMD tool) |
| Encoding | UTF-8 |
| Inbound framing | Split on `\n`; a trailing `\r` is stripped, and empty lines are discarded |
| Outbound framing | Every line ends with `\n` |

**Every message the tablet sends is newline-terminated.** Split on `\n` and
you get exactly one command per line, with no partial or glued-together lines
to unpick.

Terminate what the RPi sends the same way. Inbound framing splits on `\n`,
strips a trailing `\r` and discards empty lines, so `\r\n` is safe too. A
message may legitimately span two reads; the tablet buffers until the newline
arrives rather than acting on a fragment.

> Setting `Config.OUTBOUND_TERMINATOR` back to `""` is what drives the **AMD
> debug tool**, which matches each received chunk verbatim and so recognises
> nothing with a newline attached. That is the only reason to change it, and it
> is an AMD-only setting.

---

## 1. Tablet → RPi

Fourteen distinct messages in four groups: three arena verbs, one robot verb,
seven movement tokens and three task commands. Everything is plain ASCII with
no spaces around the commas.

### 1.1 Arena editing

| Message | Format | Example | Sent when |
|---|---|---|---|
| Add / move obstacle | `ADD,B<id>,(<x>,<y>)` | `ADD,B3,(14,15)` | A block is placed by tap, **or** a drag ends on a different cell |
| Remove obstacle | `SUB,B<id>` | `SUB,B3` | A block is dragged off the grid, or the arena is reset, or a layout is loaded |
| Set / clear image face | `FACE,B<id>,(<x>,<y>),<face>` | `FACE,B3,(14,15),E` | A face is chosen on the compass |
| Clear image face | `FACE,B<id>,(<x>,<y>),NONE` | `FACE,B3,(14,15),NONE` | The already-active face is tapped again |

- `<id>` is **1–8**, always prefixed `B`.
- `<x>,<y>` are arena cells **0–19** — see [§3](#3-coordinates).
- `<face>` is one of `N`, `E`, `S`, `W`, or the literal `NONE`.

**`ADD` is an upsert, not an insert.** The same id is re-sent with new
coordinates whenever the block moves; it never removes anything. Only `SUB`
removes.

**`ADD` is sent on finger-lift only**, never during a drag, so one drag across
ten cells produces exactly one message.

**Two `ADD`s for one block is normal.** Tapping a block into place sends one,
and later dragging it sends another. Those are two completed positionings, not
a duplicate.

**`FACE` carries the coordinate, which the briefing slide's format omits.** The
checklist text asks for "target face and obstacle coordinate", so we send the
superset. **If your parser is written against the shorter three-field form,
this is the field to add.**

### 1.2 Movement

Sent as a **bare token with no verb and no arguments**, one per button press.

| Button | Token | Motion |
|---|---|---|
| F | `f` | Forward |
| B | `r` | Reverse |
| FL | `tl` | Forward-left arc |
| FR | `tr` | Forward-right arc |
| BL | `sl` | Reverse-left arc |
| BR | `sr` | Reverse-right arc |
| STOP | `s` | Stop |

**The token names come from the AMD tool's fixed slot names, and four of them
lie about the motion.** AMD's vocabulary has no forward-arc, so its ROTATE
slots (`tl`/`tr`) carry our forward arcs and its STRAFE slots (`sl`/`sr`) carry
our reverse arcs. The car is Ackermann — **it cannot strafe and it cannot turn
on the spot.** Implement `sl` as a *reverse-left arc*, not a strafe.

> **Open question for the chassis owner.** Reversing with the wheels turned left
> swings the front left and the **rear right**. Whether `sl` belongs under the
> button labelled BL or BR is a hardware convention the app cannot settle. If
> it is backwards on the real robot, tell us and we swap two string literals.

### 1.3 Robot position

| Message | Format | Example | Sent when |
|---|---|---|---|
| Move / turn the robot | `MOVEROBOT,<x>,<y>,<degrees>` | `MOVEROBOT,7.5,2.25,20.0` | The operator drags the robot, or picks a heading on the compass |

**This is the tablet telling the robot where it is, not asking it to drive
there.** It is how an operator sets the starting pose before a run, or corrects
a drawing that has drifted from reality. Nothing about it starts motion.

- `<x>,<y>` are **cell indices, decimals allowed**, naming the cell the robot's
  footprint is **centred** on - the same units and the same anchor inbound
  `ROBOT` uses.
- They are clamped to **1-18**, one cell in from the outermost cell, so a
  coordinate that would hang the robot's axis-aligned footprint off the board
  never reaches the wire. (The body is drawn rotated, so at a diagonal heading
  its corners can overhang slightly - as a real car would.)
- `<degrees>` is **0 = north, increasing clockwise**, in `[0,360)`. Never
  absent - a robot always faces somewhere. The compass sends only
  `0.0`/`90.0`/`180.0`/`270.0`, since an operator has four keys.
- Written by `Float.toString`, so always a `.`-decimal and never a locale comma.

**Deliberately not called `ROBOT`.** One verb in both directions would echo back
on any RPi that re-broadcasts what it receives, and the two would then be
indistinguishable in the log.

**Sent on finger-lift only**, never during a drag, and only when the position
actually changed - the same rule `ADD` follows. A heading pick sends
immediately, since nothing follows a tap. Re-picking the heading already
active sends nothing.

Also sent after a **layout load** and after an **arena reset**, both of which
move the robot on screen with no gesture behind them for the RPi to infer it
from. Reset sends `MOVEROBOT,1.0,1.0,0.0` - the start pose, which is the robot
flush into the arena's bottom-left corner.

### 1.4 Task control

| Command | Token | Meaning |
|---|---|---|
| Start image recognition | `beginExplore` | Begin Task 1. The tablet starts its own clock in the same action. |
| Start fastest car | `beginFastest` | Begin Task 2, same. |
| Send arena | `sendArena` | Re-transmit the whole layout / signal that the arena is final. |

**There is no end-run command.** Ending a run stops the tablet's clock and
sends nothing, because the AMD tool has no slot for it. Say if the RPi needs
one and we will add it.

**`sendArena` currently sends only the token**, not the layout — the obstacles
were already streamed as `ADD` lines as they were placed.

---

## 2. RPi → tablet

Three messages are understood. Everything else is displayed in the raw log and
otherwise ignored — it is never an error, and it never breaks the link.

### 2.1 `MSG` — status text

```
MSG,[<text>]
MSG,<text>
```

| Example | Shown as |
|---|---|
| `MSG,[Scanning obstacle 2]` | `Scanning obstacle 2` |
| `MSG,Ready` | `Ready` |

Brackets are stripped if present. **The payload may contain commas** — it is
taken as everything after the first comma, not split on them. An empty payload
is ignored.

This is what appears on the operator's status panel, so it is the RPi's channel
for anything a human should read.

### 2.2 `TARGET` — image recognised

```
TARGET,<obstacle>,<targetId>
TARGET,<obstacle>,<targetId>,<face>
```

| Example | Effect |
|---|---|
| `TARGET,B2,11` | Block 2 shows target id 11 |
| `TARGET,B2,11,N` | …and marks its north face |
| `TARGET, 2, 11` | Same as the first — `B` optional, spaces tolerated |

- `<obstacle>` accepts `B2`, `b2` or `2`.
- `<targetId>` is **not range-checked** — the checklist's own example uses id 4,
  outside the 11–40 pool, so any integer is accepted and rendered.
- `<face>`, if present, must be `N`/`E`/`S`/`W`; anything else makes the whole
  line unparsed.

The numeric id is drawn on the block. The tablet also looks the id up in the
image pool ([§4](#4-image-pool)) and writes e.g.
`Target 11 · digit 1 · at B2` under the status line.

### 2.3 `ROBOT` — position and heading

Overrides whatever the operator last dragged. The robot's own report always
wins over the tablet's picture of it.

```
ROBOT,<x>,<y>,<heading>
```

Exactly four fields, in **either** of two forms — both accepted, and each field
decides for itself, so mixing them is fine too.

| Example | Effect |
|---|---|
| `ROBOT,5.55,6.55,20` | Centred between cells, heading 20° — **prefer this** |
| `ROBOT,1,1,N` | Legacy integers-and-a-letter. Still works |
| `ROBOT,7.5,2,N` | Mixed. Also fine |
| `ROBOT, 7, 2, w` | Spaces and lower case both fine |

- `<x>,<y>` are **cell indices, decimals allowed** — the same units an
  obstacle uses, so `ROBOT,5,5` names the cell an obstacle at `(5,5)` occupies.
  **They name the robot's CENTRE.** The anchor is a property of the message,
  not of the number format: if the two forms disagreed on it, the same robot in
  the same place would draw a cell and a half apart depending on which arrived.
- `<heading>` is either one of `N`/`E`/`S`/`W` or an angle in **degrees, 0 =
  north, increasing clockwise**. Angles are normalised, so `450` is `90` and
  `-90` is `270` — a heading is periodic and neither is an error.
- `NaN` and `Infinity` are rejected. Everything else non-numeric is too.

**Send decimals and degrees.** The car is Ackermann — it cannot turn on the
spot, so mid-arc it is genuinely at 47°, and rounding that to `N` or `E` puts
an arrow on screen pointing somewhere the robot is not.

**A reported pose always overrides one the operator dragged.** Out-of-range
coordinates are ignored, never clamped. The footprint is deliberately *not* checked, only the
centre — a robot genuinely half off the board is drawn half off the board.

Send these continuously during a run — the tablet redraws on every message and
there is no rate limit.

### 2.4 Anything else

Unrecognised lines become `Unknown` and appear **only** in the raw Bluetooth
log. Decoding never throws, so a malformed line cannot kill the read loop or
drop the connection.

Not implemented, for the avoidance of doubt: `AMDADD` / `AMDSUB` (the AMD
tool's own obstacle-drag messages) are ignored. **Obstacles travel
tablet → robot only.**

---

## 3. Coordinates

| | |
|---|---|
| Grid | 20 × 20 cells of 10 cm — a 200 × 200 cm arena |
| Origin | **Bottom-left** |
| y | counts **upward** |
| Task 1 start zone | the 4 × 4 block of cells `(0,0)`–`(3,3)` |
| Task 2 carpark | 60 cm, **position never specified** — defined relative to the goal obstacles, so it has no arena coordinate and the tablet does not draw it |

### One coordinate system, for obstacles and the robot alike

Both count in **cell indices**. `5` means cell 5 in `ADD,B1,(5,5)` and it means
cell 5 in `ROBOT,5,5,N`. The only difference is that the robot's may carry
decimals, which interpolate between cell centres.

| | Used by | Range | Decimals |
|---|---|---|---|
| Obstacle | `ADD`, `SUB`, `FACE` | integers **0–19** | no — a block occupies one whole cell |
| Robot | `ROBOT`, `MOVEROBOT` | **0–19**, decimals allowed | yes — the cell its 3 × 3 footprint is centred on |

So a robot parked exactly on obstacle B1's cell `(5,5)` reports **`ROBOT,5,5`**.
The same numbers mean the same place in both directions, which is the point.

(The drawn 3 × 3 is the *planning* footprint; the real chassis is ~18.7 × 23 cm,
so the box on screen is wider than the car.)

Two consequences worth stating outright:

- **Centimetres**: `cm = (x + 0.5) × 10`, measured to the cell's centre. `x = 0`
  is 5 cm from the left edge — the middle of the first cell — and `x = 19` is
  195 cm.
- **A robot flush into the bottom-left corner is at `(1, 1)`.** Its 3-cell body
  covers cells 0, 1 and 2, so the centre is cell 1. That is also `MOVEROBOT`'s
  clamp floor, and the tablet's own start pose.

The tablet flips to screen coordinates internally and nothing else in the app
or the protocol sees that flip.

**Guarantees the tablet enforces before anything reaches the wire**, so the RPi
does not need to re-check them:

- an `ADD` coordinate is always an integer cell index inside 0–19 on both axes;
- it is never inside the start zone;
- two obstacles never share a cell;
- ids never exceed 8, and a freed id is reused before a new one is allocated.

`ROBOT` is **not** validated beyond its centre being within 0–19 — the tablet
draws whatever it is sent, including a robot half off the edge.

Note this differs from the AMD tool (top-left origin, y downward) and from the
algorithms briefing (radians, east = 0). If a value looks mirrored, this is the
first thing to check.

---

## 4. Image pool

`<targetId>` values and what the tablet displays for each. Ids **11–40**; the
letters deliberately skip I through R.

| Id | Meaning | Id | Meaning | Id | Meaning |
|---|---|---|---|---|---|
| 11 | digit 1 | 21 | letter B | 31 | letter V |
| 12 | digit 2 | 22 | letter C | 32 | letter W |
| 13 | digit 3 | 23 | letter D | 33 | letter X |
| 14 | digit 4 | 24 | letter E | 34 | letter Y |
| 15 | digit 5 | 25 | letter F | 35 | letter Z |
| 16 | digit 6 | 26 | letter G | 36 | up arrow |
| 17 | digit 7 | 27 | letter H | 37 | down arrow |
| 18 | digit 8 | 28 | letter S | 38 | right arrow |
| 19 | digit 9 | 29 | letter T | 39 | left arrow |
| 20 | letter A | 30 | letter U | 40 | stop |

An id outside this table still displays on the block; the status line reads
"unrecognised id".

---

## 5. A worked session

Tablet lines are `TX`, robot lines `RX`, exactly as the raw log shows them.

```
TX  ADD,B1,(5,5)              operator taps a cell
TX  ADD,B2,(10,11)
TX  MOVEROBOT,1.0,1.0,0.0     operator re-parks it in the corner it starts at
                              (cell 1 is the clamp floor - one cell in)
TX  FACE,B2,(10,11),E         operator sets B2's image face
TX  ADD,B2,(12,11)            B2 dragged two cells right
TX  MOVEROBOT,1.0,1.0,90.0    operator turns it east on the compass -
                              a heading pick re-sends the CURRENT position
TX  sendArena                 layout is final
TX  beginExplore              run starts, tablet clock starts
RX  MSG,[Moving to obstacle 1]
RX  ROBOT,1,1,90              robot confirms the pose it was placed at
RX  ROBOT,1.62,2.40,14        mid-arc: neither cell-aligned nor cardinal
RX  TARGET,B1,16,S            block 1 now shows 16
RX  MSG,[Scanning obstacle 2]
RX  ROBOT,12.05,11.30,271
RX  TARGET,B2,11,E
RX  MSG,[Done]
TX  s                         operator stops the robot
```

---

## 6. Open items for the RPi owner

Two answers are needed. Both are cheap to fix now and expensive to find on
demo day, because each fails *plausibly* rather than loudly.

**Settled, for the record:** the robot's coordinate names its **centre**, in
decimal cells, with the heading in degrees clockwise from north. Both the
legacy and continuous inbound forms are accepted. The RPi team is matching
these, so they are decisions rather than questions.

1. **`FACE` format.** Does your parser accept the four-field form with the
   coordinate, or does it need the three-field one?
2. **`sl` / `sr`.** Which of the two is the reverse-**left** arc on the real
   chassis?

And one thing nobody has asked yet, flagged because it is larger than either:
**the entire outbound vocabulary above comes from the AMD debug tool's fixed
slot names**, not from the RPi. `f`/`r`/`tl`/`tr`/`sl`/`sr`, `beginExplore`,
`beginFastest` and `sendArena` were taken from AMD's Commands screen. Confirm
the RPi parser actually speaks them, rather than assuming it does.

Anything the RPi wants to send that is not `MSG`, `TARGET` or `ROBOT` needs a
decoder change on our side — send the format and we will add it.
