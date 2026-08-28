# Design decisions

Why the Android controller is built the way it is. The code carries short
comments for anything that would cause a bug if changed; the longer reasoning —
what was tried, what broke, what the alternatives cost — lives here.

Read alongside [`checklist-demos.md`](checklist-demos.md), which is the runbook
for demonstrating each checklist item, and the artboards in
[`design/`](design/), which are the visual reference.

---

## 1. Protocol and the AMD tool

The app is developed against the **AMD debug tool** rather than the RPi,
because the RPi arrived late and AMD is the reference peer the checklist names.
That has consequences the RPi owner needs to know about.

### The outbound line terminator

`Config.OUTBOUND_TERMINATOR` is `"\n"`. RFCOMM is a byte stream with no message
boundaries of its own, so without a delimiter consecutive sends concatenate on
the wire - `ADD,B1,(5,5)` followed by `f` arrives as `ADD,B1,(5,5)f`, which a
newline-framing parser reads as one malformed line rather than two good ones.

It was `""` for most of development, because the **AMD debug tool** compares each
received chunk against its configured command strings verbatim: a trailing
newline makes every token mismatch. AMD's own unmodified `sendArena` token
appeared in its RECEIVED TEXT panel and never matched in its COMMAND LOG until
the terminator was dropped.

So the two peers want opposite values, and the RPi's is now the default.
**Set it back to `""` before any session that drives AMD**, or AMD will display
everything and act on nothing.

### Inbound framing and the idle flush

Inbound always splits on `"\n"`, whatever the outbound terminator is set to.
A message can legitimately span two reads, which is why `LineFramer` buffers
rather than emitting per read.

But AMD does not terminate what it sends, so a message from it would sit in the
buffer forever. `Config.INBOUND_FLUSH_IDLE_MS` (40 ms) flushes a pending line
after a short silence. `feed()` always takes priority over `flushPending()` —
more bytes arriving is proof the pending message was not finished. Too short a
value splits a genuinely-fragmented RPi message; too long and AMD feels laggy.
Tens of milliseconds is comfortably longer than the gap between two reads of
one message and comfortably shorter than a person notices.

### Movement tokens: the names disagree with the values on purpose

The car is **Ackermann**. It cannot strafe and it cannot turn on the spot. AMD
offers exactly six fixed movement slots named `f`, `r`, `tl`, `tr`, `sl`, `sr`,
and our six buttons map onto them: `tl`/`tr` carry the **forward** arcs and
`sl`/`sr` carry the **reverse** ones.

So `Config.MoveTokens` has field names describing the *motion* and values that
are AMD's *slot names*, and four of the seven disagree. Those fields were once
called `rotateLeft`/`strafeLeft`/etc. — which reads as a bug at a glance, and
is a trap for the robot side: anyone implementing against `strafeLeft` writes a
strafe, and the button then does nothing on this chassis.

**Still open for the chassis owner:** reversing with the wheels turned left
swings the front left and the *rear* right, so whether `sl` belongs under the
button labelled BL is a hardware convention this app cannot settle. If it is
backwards, swap those two values and the matching expectations in
`ControlPadTest`. Nothing else changes.

### FACE carries the coordinate

The checklist text requires "the target face **and** obstacle coordinate"; the
briefing slide's format omits it. We send the superset —
`FACE,B3,(14,15),E` — which needs agreeing with whoever writes the RPi parser,
since a parser written against the shorter form may reject every line.

### The decoder is deliberately tolerant

`decode()` is a **total function**: every input produces an `Inbound` and it
never throws. A parser exception on the I/O coroutine would kill the read loop,
which from the UI is indistinguishable from a disconnect.

The tolerances exist because the two source documents disagree — the checklist
writes `TARGET, <n>, <id>` with spaces, the slides write obstacle ids as `B2`
while the checklist uses a bare number, and the four-argument TARGET form
appears only in the slides. Target ids are **never range-checked**, because the
checklist's own example uses id 4, outside the 11–40 pool.

### Obstacles travel one way

Obstacles go tablet → robot. Dragging AMD's virtual obstacle emits
`AMDADD`/`AMDSUB`, which the decoder does not handle — they land in the raw log
as unparsed lines and never touch the arena. AMD's virtual *robot* drag is
different: it emits `ROBOT,<x>,<y>,<letter>`, which is understood.

### The robot travels both ways, under two different names

The robot is the one thing on the arena both sides can move, so it has a verb
each: inbound `ROBOT` for what the robot reports, outbound `MOVEROBOT` for what
the operator drags. Reusing one name would echo on any RPi that re-broadcasts
what it receives, and a log line would no longer say which side moved it.

An inbound `ROBOT` always wins — the robot knows where it is better than the
tablet does. `MOVEROBOT` is for setting a start pose or correcting a drawing
that has drifted, and it never starts motion.

### The pose is continuous, and anchored at the centre

The car is Ackermann — it cannot turn on the spot, so mid-arc it is genuinely
at 47° somewhere between two cells. An integer cell index plus four cardinal
letters cannot say that. `RobotPose` therefore carries **decimals and degrees**
(0 = north, clockwise, normalised to `[0,360)`), and the arrow is one triangle
rotated rather than four hardcoded paths.

**It counts in the same units an obstacle does.** `ROBOT,5,5` names the cell an
obstacle at `(5,5)` occupies; decimals interpolate between cell centres. An
earlier version measured the robot as a point from the arena corner instead,
which made `ROBOT,5,5` and `ADD,B1,(5,5)` half a cell apart — 5 cm, diagonal,
and entirely plausible on screen. `Grid.centreOf(i,j)` and the continuous
conversion at `(i,j)` are now the same point, and a test asserts it across all
400 cells.

The coordinate names the footprint's **centre**, not a corner. Three reasons,
in order of weight:

1. Continuous odometry naturally produces the robot's centre or axle midpoint.
   Asking the RPi for a footprint corner is asking for a conversion it has no
   reason to compute.
2. A non-square body — and the real chassis is ~18.7 × 23 cm — must rotate with
   the heading, and a corner anchor swings the whole body as it turns while a
   centre anchor holds it still.
3. It decouples the drawn footprint size from position. Under a corner anchor,
   `Config.ROBOT_SIZE_CELLS`, AMD's *Robot size* setting and the AMD script's
   own constant all had to agree or every position shifted. Now a mismatch only
   changes how big the box looks.

The legacy `ROBOT,7,2,N` form still parses, because AMD's virtual-robot drag
emits it and that is the only way to demonstrate the arena without hardware.
**Both forms mean the centre** — the anchor is a property of the message, not
of the number format. Had they differed, the same robot in the same place would
draw a cell and a half apart depending on which form arrived.

### The start pose, and what the shaded square means

Nothing specifies where in the start zone the robot begins or which way it
faces. §4.1 of the briefing notes says only that it starts "in the 40×40 cm
start zone", and Task 2's starting orientation is listed as an open item.

So the app parks it on **cell (1, 1)** — its 3-cell body covering cells 0–2 on
both axes, flush into the arena's bottom-left corner, which is also
`moveRobot`'s clamp floor. Still a choice rather than a specified position, but
a corner is at least a definite one.

The shaded square is labelled `T1 START`. It is Task 1's
40 cm zone specifically; Task 2 starts in a 60 cm carpark whose position in the
arena is **never given** — its layout is defined relative to the goal
obstacles, at a distance unknown until the run. There is no defensible place to
draw it, so the app draws nothing and says which task the square belongs to.

### Local moves clamp; reported poses do not

`Arena.moveRobot` clamps the centre to cells 1–18, one cell in from the
outermost, which keeps the *axis-aligned* footprint on the board. The body is
drawn rotated to the heading, so at a diagonal its corners reach 1.5 × √2 and
can overhang — left alone, because a real car nosed into a corner at an angle
overhangs too, and clamping for the worst case would stop it short of walls it
can actually reach. `Arena.applyPose` ignores an
out-of-range coordinate outright rather than clamping it, and checks only the
centre — a robot genuinely half off the board is drawn half off the board. The
asymmetry is deliberate and worth keeping.

A finger dragged past the edge means "as far as it goes", so stopping against
the wall is the honest reading. A malformed `ROBOT,25,25` means something is
wrong upstream, and clamping it to (17,17) would draw a plausible-looking
position that hides the bug — where a robot that visibly refuses to move does
not. Same reasoning as C.10's demo step: an unmoved robot is obviously wrong,
which is the point.

The robot is also **not** collision-checked against obstacles, in either
direction, unlike `Arena.place`. Obstacle placement is a layout being authored,
so the app validates it; the robot's position is a physical fact being stated,
and the app has no standing to refuse it.

---

## 2. Coordinate conventions

Four systems are in play, and mixing them mirrors the grid:

| System | Origin | y axis |
|---|---|---|
| Arena (ours, and the protocol's) | bottom-left | up |
| Android canvas | top-left | down |
| AMD tool | top-left, degrees, N = 0 clockwise | down |
| Algorithms briefing | bottom-left, radians, E = 0 | up |

`Grid.kt` is the **only** place the arena↔canvas flip happens, and
`toCanvasRow` is its own inverse. Everything else stays in arena space.

The robot is positioned by the cell its footprint is **centred** on, decimals
allowed, and the 3 × 3 box is drawn around that centre. Note that 3 × 3 is the
algorithms deck's 30 cm *planning* footprint, not the car — the real chassis is
~18.7 × 23 cm, so the box on screen is about 60% wider than the thing it
represents. Under centre anchoring that is purely cosmetic and can be corrected
locally whenever someone measures the car.

---

## 3. The link layer

`ConnectionRepository` and `BluetoothSppTransport` absorbed more bug-fixing than
the rest of the app combined, and nearly every fault was a variant of one thing:
**a stale attempt publishing over, or tearing down, a newer live session.**

### The failure that motivates all the guards

A real `BluetoothSocket.connect()` can block for 12–35 seconds. That is long
enough that an operator taps again, so two overlapping connects are ordinary
rather than exotic. Left unguarded:

- The older attempt's socket calls fail (two attempts contend for one adapter),
  and the transport reports that as `Result.failure`, **not** a cancellation —
  so it writes `Failed` over a live `Connected`, and the UI shows a
  disconnected banner while traffic is flowing.
- A stale read loop parked in a blocking `read()` wakes up when RFCOMM finally
  times out and clears `connected` on the *new*, healthy link.

Hence three separate mechanisms, which are not redundant:

- **`epoch`** (transport, `AtomicInteger`) — bumped on every teardown, so a
  connect blocked in a slow socket call can tell it has been superseded. Atomic
  rather than volatile because teardown runs concurrently from `close()` and
  from a fresh `connect()`, and a bare `++` can lose an increment.
- **`connectGeneration`** (repository) — stamped per call, so only the newest
  attempt publishes state.
- **`connectsInFlight`** (repository) — a *count*, so overlapping calls do not
  clear each other's guard. It blocks an automatic retry from starting
  underneath a deliberate connect. Released the instant the suspension ends and
  deliberately not held across the follow-up work, because holding it longer
  swallows a drop that lands in that window.

### Why a drop must be noticed without a send

During an exploration run the robot drives itself and the operator sends
nothing for minutes. "We will find out on the next send" is not recovery. So
`transport.connected` is a `StateFlow` the repository watches, and every exit
path from the read loop clears it — guarded by an identity check, so a stale
reader cannot clear a newer session's state.

### Automatic retry never promotes a link that never came up

`beginReconnect()` returns unless the state is already `Connected` or
`Reconnecting`. Arena edits are deliberately not gated on the link — you lay
obstacles out before connecting — so without that guard, any send attempted
while the bar reads FAILED would start a retry loop and replace the RETRY
button, which is the operator's only way back, with a spinner that masks a real
fault.

### Threading

`MdpApplication` uses `Dispatchers.Main.immediate`, **not** `Dispatchers.IO`.
The repository's job handles and counters are plain, non-volatile vars: sound
under a single-threaded confined dispatcher, unsound under a multi-threaded
one. Nothing there needs IO — the transport wraps its own blocking calls.

---

## 4. Android platform behaviour worth knowing

**Bluetooth broadcasts are cross-app on Android 13+.** The stack runs as its own
APEX app, so `ACTION_FOUND`, `ACTION_DISCOVERY_FINISHED` and
`ACTION_BOND_STATE_CHANGED` must be received with `RECEIVER_EXPORTED`. A
`NOT_EXPORTED` receiver gets nothing, silently: registration succeeds,
`startDiscovery()` returns true, the radio really does scan, and the app hears
nothing at all. This cost a full debugging session; do not tighten it back.

**Discovery degrades RFCOMM.** They contend for the same radio, which is why
`connect()` calls `cancelDiscovery()` and why closing the picker stops the scan.

**`cancelDiscovery()` is asynchronous.** Its `ACTION_DISCOVERY_FINISHED` lands
after a new receiver is registered, so `BluetoothScanner` tracks whether the
finish broadcast belongs to its own scan — without that, a scan tears itself
down immediately after starting.

**Classic discovery only reports discoverable devices.** An idle laptop is
invisible to it. That is the most common reason a scan finds nothing, and it is
not a fault — hence the raw sightings counter, which separates "heard nothing"
from "heard plenty and filtered it".

**Edge-to-edge is mandatory from Android 15** at `targetSdk 36`, so the app
opts in on every version and pads itself back out of the system bars, keeping
one behaviour across versions.

**`preferencesDataStore` caches per name, not per Context**, and never
re-consults the Context after the first creation. Harmless for the single
instance a running app makes, fatal for test isolation — which is why
`ArenaStore` is an interface with an in-memory fake behind it.

---

## 5. The visual layer

The design is a flat, printed look: paper and cream grounds, near-black ink
borders on everything, hard offset shadows with **zero blur**, and saturated
colour used semantically rather than decoratively.

**Material 3 components are kept and re-skinned, not replaced.** Buttons,
dialogs, the bottom sheet, the text field and the progress indicator are all
Google's, so ripples, touch slop, focus and accessibility semantics come for
free. What changed is the theme.

Three things could not be done through theming:

- **A complete `ColorScheme`.** Material fills any unset role with stock
  purple-grey, and the components that matter do not read the obvious roles:
  `Card` defaults to `surfaceContainerLow`, not `surface`, and `OutlinedButton`
  to `outline` + `surface`. Setting eight roles and leaving the rest is why an
  early build rendered half the screen in M3 lavender.
- **Button shape.** `Button` resolves its shape from the `CornerFull` token,
  which maps to `CircleShape` unconditionally and never consults
  `MaterialTheme.shapes`. Shape has to be passed per call site, which is what
  `MdpButton` exists for. Any stray stock `Button(` will render as a pill.
- **The surface treatment.** `Modifier.shadow` draws a *blurred* elevation
  shadow, which is precisely the idiom this design rejects, so
  `Modifier.hardSurface()` draws the border and the offset block by hand.
  `Card` is not used anywhere for the same reason.

**Typefaces are bundled, not downloaded.** Downloadable Fonts would save
~500 KB, but needs Play Services and a network round-trip the first time a
glyph is drawn — and this runs on a lab tablet that may be in aeroplane mode
during a timed assessment. Bricolage Grotesque is a variable font with `wght`
pinned per weight; DM Mono ships only the two weights the design uses. Licences
are in [`licenses/`](licenses/).

### The two face bars are different colours

`Obstacle.imageFace` (what the operator annotated, outbound) draws **yellow**;
`Target.face` (what the robot reported alongside an image id, inbound) draws
**green**. They are deliberately separate fields in the model, and drawing both
in one colour made a block claim an agreement it might not have — when the two
disagree, the operator now sees it at a glance rather than by opening the
compass. If both name the same face, green lands on top: once the robot has
reported, its own reading is the one that matters.

---

## 6. Layout

**The screen is one surface, and nothing on it scrolls** except the raw log. A
control that has to be scrolled back into view is missing at the moment it is
needed, and STOP is on this screen.

**The right-hand side is two columns.** As one stack, its fixed children sum to
more than a landscape tablet's height, so the raw log was allocated no space at
all and the status card was clipped off the bottom. Both panels exist for
graded items, so neither may be the thing that gives; splitting them spends
horizontal room, which that side has.

**The arena is sized by height, not by a share of the width.** A cell is only
~4.7 mm against Material's 7.6 mm touch minimum, so every pixel of grid is
touch precision. Its column takes exactly the grid's side — measured from the
available height minus the toolbar — rather than a square of the full height,
which would leave a toolbar's worth of blank margin either side.

**Panels sit inboard and controls outboard**, because on a tablet held in two
hands the outer edge is what a thumb reaches without regripping.

**Touch targets are 56 dp, not Material's 48 dp minimum.** These are operated
under a clock.

---

## 7. What is not covered by tests

The JVM suite covers the arena model, the protocol codec, the framer, the run
timer and the repository's state machine against a fake transport.

It **cannot** reach:

- `BluetoothSppTransport` and `BluetoothScanner`, which need a real adapter and
  Context. The receiver-lifecycle bug that killed discovery lived here.
- `PreferencesArenaStore`, for the same reason.
- **Any Compose UI at all** — there is no instrumentation test harness in this
  project. Every gesture, dialog, layout and style is verified by a human
  following [`checklist-demos.md`](checklist-demos.md) on the real tablet.

A passing test run says nothing about the parts of the app a supervisor
actually looks at. Run the demo script.
