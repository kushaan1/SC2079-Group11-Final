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

`Config.OUTBOUND_TERMINATOR` is currently `""`. **The RPi needs `"\n"`.**

RFCOMM is a byte stream with no message boundaries, so a delimiter is required
for any peer that frames on newlines. AMD is not such a peer: on hardware it
compares each received chunk against its configured command strings verbatim,
so a trailing newline makes every token mismatch. AMD's own unmodified
`sendArena` token appeared in its RECEIVED TEXT panel and never matched in its
COMMAND LOG until the terminator was dropped.

With `""`, back-to-back sends concatenate on the wire. Harmless for AMD's
whole-chunk matching; wrong for anything else. **This is one line to change
before the first RPi session, and it is the highest-consequence open item in
the module.**

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

The robot is drawn anchored at its **bottom-left cell** with the 3×3 footprint
extending up and right. Whether `ROBOT,7,2` names that cell or the robot's
centre is still unconfirmed with the RPi owner; if it is the centre, every
drawn position is off by one cell diagonally.

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
