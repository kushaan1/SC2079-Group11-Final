# Android Remote Controller — Design

**Date:** 2026-08-21
**Subsystem:** Android (SC2079 MDP, Group 11)
**Status:** Design approved, ready for implementation planning
**Hard deadline:** Project deliverable checklist — **Friday of week 7**

---

## 1. Purpose

An Android tablet app that acts as the remote controller for the robot: it connects over
Bluetooth SPP, drives robot movement, displays live arena state, lets the user lay out the
obstacle course by touch, and shows what the robot reports back.

Success is defined by the **ARCM deliverable checklist C.1–C.10** being demonstrated to and
signed off by a supervisor. Verification is against the **AMD tool**, not the RPi — the checklist
names it as the reference peer for C.1, C.3, C.4 and C.8.

### Scope

In scope: C.1–C.10, plus **two run timers** (one per graded task), **task-start commands**
(`beginExplore` / `beginFastest` / `sendArena`), **arena save / load / reset**, and an exportable
session log.

> **Scope amended 2026-08-21** after reviewing two prior-year implementations of this module.
> Both independently built task-start controls, two timers, and layout save/load. None of those
> are checklist items — they are what a competition run needs. The original scope had no way to
> tell the robot to begin a run at all. See the plan's AMENDMENT section.

Out of scope, deliberately:

- **Task 2 (fastest car) mode.** AGENTS.md §10 still lists the carpark dimensions as unconfirmed.
- **Stitched verification image display.** The general briefing says it may be shown "in android
  or PC". We are assuming PC. **If the team decides otherwise this lands on Android** — see §10.
- **Compose UI instrumentation tests.** See §9.

---

## 2. Constraints

| | |
|---|---|
| Device | Samsung Galaxy A7 Lite, 8.7", 1340×800, Android 14 |
| Physical screen | 19.0 cm × 11.3 cm landscape (~179 ppi) |
| `minSdk` / `targetSdk` / `compileSdk` | 31 / 36 / 36 |
| Language / build | Kotlin 2.x, AGP 9.1.x, Gradle version catalog, Compose Compiler Gradle plugin |
| UI | Jetpack Compose, Compose BOM `2026.08.00`, Material 3 **stable** |
| Location | New `android/` directory, per AGENTS.md §9.1. Pante's tree is read-only |

**Material 3 Expressive is deliberately avoided.** It is still on the `1.5.0-alpha` line; an alpha
API rename in week 8 is a self-inflicted wound on a fixed deadline.

**Aesthetics are graded.** The video report is 15% of the course, split into five equal criteria,
and the first is "Android UI Design — usability features and aesthetic appeal". Android is the only
module named in the video rubric. The visual direction is therefore a requirement, not polish.

---

## 3. Architecture

Single Gradle module. Boundaries enforced by package discipline, not by Gradle — multi-module was
considered and rejected as ceremony at this size.

```
com.mdp.grp11
├── transport/    Transport interface · BluetoothSppTransport · FakeTransport
├── connection/   ConnectionRepository — owns the transport, reconnect, ConnectionState
├── protocol/     Message types + codec           ← pure Kotlin, zero android imports
├── arena/        Arena · Obstacle · Cell · Grid  ← pure Kotlin, zero android imports
├── session/      run timer · event log · export
└── ui/
    ├── theme/  components/  arena/  control/  status/  devices/
```

Dependency direction is one-way: `ui → connection → transport`, `ui → arena`,
`connection → protocol`. Nothing points back up.

**The load-bearing rule:** `protocol/` and `arena/` contain no `android.*` imports, so the codec,
the coordinate maths, obstacle placement and face annotation are all JVM-unit-testable with no
device and no emulator.

**Navigation:** one Activity, one screen, device picker as a modal bottom sheet. No navigation
library — with two destinations it is pure overhead.

---

## 4. Transport and connection (C.1, C.2, C.8)

```kotlin
interface Transport {
    val incoming: Flow<String>                          // complete, framed messages only
    suspend fun send(line: String)
    suspend fun connect(target: Target): Result<Unit>   // Client(device) | Listen
    fun close()
}

sealed interface ConnectionState {
    data object Idle
    data class Connecting(val device: DeviceInfo)
    data class Connected(val device: DeviceInfo)
    data class Reconnecting(val device: DeviceInfo, val attempt: Int)
    data class Failed(val reason: String)
}
```

`ConnectionRepository` is Application-scoped, owns a `CoroutineScope(SupervisorJob() +
Dispatchers.IO)`, and exposes `StateFlow<ConnectionState>` plus a hot `SharedFlow<String>` of
inbound lines. Writes serialise behind a `Mutex`. The UI never touches a socket and never blocks —
which is precisely what C.8 tests.

### Framing

RFCOMM is a **byte stream, not a message stream**. A `read()` may return half a message or two
glued together. Accumulate into a buffer, split on `\n`, emit only complete lines.

**Clear the frame buffer on disconnect.** If the peer dies mid-write, a half-line left in the
buffer prepends to the first message after reconnect and corrupts it — a bug that only manifests
after a reconnect, which is the hardest condition to reproduce on purpose.

### Both roles run concurrently

This is not optional, and it is the crux of C.8:

- **Client** — for the RPi. `RPI-InfraSetup-v5` §D.4 configures the Pi as the RFCOMM *server*
  (`rfcomm listen`), so the tablet connects out.
- **Server** — for the AMD tool. AMD connects *to* the tablet ("CONNECTED TO Galaxy Tab S") and its
  Bluetooth menu offers **"Reconnect to last device"**. The peer initiates, so we must be listening.

First to establish wins; the loser is cancelled. On a drop, both restart. Client retries back off
1s → 2s → 4s → 5s and never give up.

### Permissions (API 31+, no legacy path)

```xml
<uses-permission android:name="android.permission.BLUETOOTH_CONNECT" />
<uses-permission android:name="android.permission.BLUETOOTH_SCAN"
                 android:usesPermissionFlags="neverForLocation" />
<uses-permission android:name="android.permission.BLUETOOTH_ADVERTISE" />
```

`neverForLocation` is what lets us skip `ACCESS_FINE_LOCATION` entirely. `ADVERTISE` is needed to
make the tablet discoverable so AMD can initiate.

Adapter comes from `getSystemService(BluetoothManager::class.java).adapter` —
`getDefaultAdapter()` is deprecated at this target. **Always `cancelDiscovery()` before
`connect()`**; discovery running during connect starves the radio and causes flaky connections.

### FakeTransport

Implements the same interface in-memory with a scriptable feed. Gives a working app when a teammate
has the AMD device, and makes the reconnect state machine deterministically testable.

---

## 5. Protocol codec

```kotlin
sealed interface Inbound {
    data class Status(val text: String)                                  // MSG,[Moving]
    data class TargetFound(val obstacle: Int, val targetId: Int, val face: Face?)
    data class RobotPose(val x: Int, val y: Int, val heading: Face)      // ROBOT,1,1,N
    data class Unknown(val raw: String)
}

sealed interface Outbound {
    data class AddObstacle(val id: Int, val x: Int, val y: Int)          // ADD,B1,(10,6)
    data class RemoveObstacle(val id: Int)                               // SUB,B1
    data class SetFace(val id: Int, val x: Int, val y: Int, val face: Face?)
    data class Move(val token: String)                                   // token from config
}

fun decode(line: String): Inbound       // TOTAL — never throws
fun encode(msg: Outbound): String
```

Formats follow the supervisor's own worked examples in `MDP ARCM Briefing Slides.pdf`. The checklist
says the outbound format is "free to devise"; matching the slides is free insurance.

**`decode` is total.** A parser exception thrown on the I/O coroutine kills the read loop, and from
the UI that is indistinguishable from a disconnect. Worst case returns `Unknown(raw)`.

### Tolerance rules, each traceable to a source disagreement

| Rule | Because |
|---|---|
| Trim whitespace after commas | Checklist writes `"TARGET, <n>, <id>"` with spaces |
| Accept `B2` **or** `2` as obstacle id | Slide says `B2`, checklist says "Obstacle Number" |
| `TARGET` takes **3 or 4** args | The 4-arg form appears only in the slides |
| **Any integer** target id accepted | C.9's own example uses ID 4, outside the 11–40 pool |
| Face case-insensitive; `NONE` clears | Our own toggle behaviour |
| Unknown verb → `Unknown`, never throws | Robustness |

**Never range-reject a target id.** The image pool is IDs 11–40, but the checklist demonstrates the
feature with `target ID of 4`. Strict validation would make the app ignore the supervisor's own
example and fail the item. Tolerant in, strict out.

`MSG,[Moving]` extracts the bracketed payload; the slide shows the tablet rendering just "Moving".

### `FACE` carries the coordinate

The slide shows `FACE,B2,N`. The checklist text requires "the target face **and obstacle
coordinate**". We send the superset: `FACE,B3,(14,15),E`. **This must be agreed with whoever writes
the RPi parser** — see §10.

---

## 6. Arena model

```kotlin
enum class Face { N, E, S, W }

data class Cell(val x: Int, val y: Int)              // 0..19, y-up, bottom-left origin
data class Target(val id: Int, val face: Face?)
data class Obstacle(
    val id: Int,
    val cell: Cell,
    val imageFace: Face? = null,   // C.7 — what WE annotated, outbound
    val target: Target? = null     // C.9 — what the ROBOT reported, inbound
)
data class RobotPose(val cell: Cell, val heading: Face)
data class Arena(val obstacles: List<Obstacle>, val robot: RobotPose?)
```

**`imageFace` and `target.face` are separate fields.** They render similarly and it is tempting to
collapse them, but they are different facts from different sources. Keeping them apart means an
inbound `TARGET` cannot silently erase the user's annotation, and lets the UI surface "you said N,
robot found it on E" — one of the few live signals distinguishing a bad arena setup from a bad
recognition.

**All coordinate conversion lives in one object**, unit-tested:

```kotlin
object Grid {
    const val CELLS = 20
    fun toCanvasY(cellY: Int) = CELLS - 1 - cellY
    fun cellAt(px: Float, py: Float, gridPx: Float): Cell
}
```

Four coordinate conventions coexist in this system. Any two meeting without an explicit conversion
is a bug:

| Party | Origin | Y | Heading |
|---|---|---|---|
| Arena / checklist | bottom-left | up | letters N/S/E/W |
| Android canvas | top-left | down | — |
| AMD tool | top-left | down | degrees, North = 0, clockwise |
| Algorithms briefing | bottom-left | up | radians, East = 0 |

### Obstacle identity: fixed pool

```kotlin
private fun nextFreeId(existing: List<Obstacle>): Int? =
    (1..MAX_OBSTACLES).firstOrNull { id -> existing.none { it.id == id } }
```

Ids come from a fixed pool of 8; a removed obstacle returns its number to the pool. The checklist
says obstacle numbers run "from 1, 2, 3,..n", and a monotonic counter that displays B2/B6/B9 reads
as a bug to a supervisor even though it isn't. Reuse is safe because `SUB,B3` always precedes the
next `ADD,B3`.

`null` (pool exhausted) rejects the placement — which is also where the 8-obstacle cap is enforced,
rather than needing a separate check.

**No obstacle tray.** A tray was considered and rejected: every benefit claimed for it (stable
numbering, reuse, visible cap) comes from the allocator, not the UI. A `4 / 8` count label covers
the rest at a fraction of the screen cost.

### Invariants, enforced in the model and unit-tested

No two obstacles share a cell; cells stay within 0..19; nothing is placed in the 4×4 start zone; at
most 8 obstacles. These apply to **drag as well as placement**. A violated placement is *rejected*,
never thrown.

---

## 7. UI design

Single landscape screen. All ten checklist items visible at once, deliberately — a supervisor
signing off C.1 through C.10 in one sitting should not have to navigate.

```
┌──────────────────────────┬──────────────────┐
│  ARENA CANVAS            │ robot · timer    │
│  660×660, 20×20 cells    │ control pad      │
│  axis labels 0..19       │ face compass     │
│                          │   OR status      │
│                          │ raw BT log       │
└──────────────────────────┴──────────────────┘
```

### The binding constraint: cells are smaller than fingers

```
660px grid ÷ 20 cells = 33px = 4.7 mm per cell
Material minimum touch target = 48dp = 7.6 mm
```

A grid cell is ~61% of the minimum touchable size, so **hit area is decoupled from render size**.
A block draws at one cell but claims a 48dp radius; overlaps resolve to the nearest centre.

Consequences carried through the design:

- **Face annotation is a compass, not edge-tapping.** A block face is 4.7 mm × 1 mm. C.7
  anticipates this: an alternative method is allowed provided it stays touch-based. Compass keys
  are 56px (7.9 mm), clear of the floor. Centre key confirms; tapping an active face toggles it off.
- **A coordinate badge follows the drag**, offset from the touch point, because a finger completely
  covers a 33px block.
- **Destructive state is signalled arena-wide.** Dragging a block outside flags the whole canvas —
  no small target to miss.
- **Axis labels 0..19 on both edges**, matching every reference tablet image in the ARCM slides.

### Messages fire on finger-lift, never during the drag

C.6 requires the coordinates "once the positioning of the obstacle is completed and the finger is
lifted". Emitting during the drag would send one message per cell crossed. **A tap that merely
selects a block must not emit anything** — otherwise opening the face compass re-announces an
obstacle that never moved.

### C.4: the status panel is filtered, the log is raw

The checklist forbids dumping the stream into the status box: it "must only display selective
information". So there are two surfaces — a **status panel** showing only `MSG,[...]` payloads, and
a **raw log** showing both directions (`TX`/`RX`), which is C.1's evidence, the debugging tool, and
the source for log export. One piece of work, three purposes.

### C.9: block shows the ID, status line names the image

The block displays the Target ID in large white as required (`11`). The status line expands it —
*"Target 11 · digit 1 · at B2"* — so a supervisor can judge whether the recognition was correct
without consulting the ID table. Image IDs are always exactly two digits (11–40), so the block
never resizes its text.

### Visual direction

Cream ground, heavy ink outlines, hard offset shadows, Bricolage Grotesque + DM Mono. Chosen from
three explored directions. Chunky by construction, which suits a screen where touch targets are the
binding constraint, and distinctive on video.

Colour is genuinely free choice — the checklist PDF shows black blocks with yellow face bars, the
ARCM slides show blue blocks with red bars. The two official documents disagree, so neither is
normative.

---

## 8. Error handling

| Failure | Behaviour |
|---|---|
| Link drops mid-run | `Reconnecting`, arena preserved, control pad disabled, retry loop runs |
| Malformed inbound line | `Unknown(raw)` → log only, never throws |
| Partial frame at drop | Frame buffer cleared on disconnect |
| `TARGET` for unknown obstacle | Logged, ignored — never auto-created |
| `ROBOT` with out-of-range coords | Logged, ignored — robot does not move |
| Write fails | Marked failed in the log, triggers reconnect |
| Adapter off / permission denied | Distinct UI states with a route to settings |

Three of these are decisions rather than defaults:

**Outbound messages are dropped while disconnected, never queued.** A queued `f` replayed thirty
seconds later would drive the robot when nobody expects it.

**Out-of-range poses are ignored, not clamped.** A robot at a clamped position looks plausible and
is wrong; a robot that did not move is obviously wrong. Prefer the visible failure.

**Arena persists to DataStore on every change.** Eight obstacles is a trivial payload, and
re-entering the course by hand after a process death mid-session is exactly the avoidable loss that
ruins a run.

---

## 9. Testing

**Tier 1 — JVM unit tests, no device.** `protocol/` and `arena/` are pure Kotlin. Table-driven:
every documented message variant from both source documents plus malformed inputs; id allocation
and reuse; the invariants; the y-flip in both directions; hit-test resolution. The codec table is
the most valuable file in the repo — it is where the source contradictions stop being prose and
become executable facts.

**Tier 2 — `FakeTransport` tests.** Drive `ConnectionRepository` deterministically: connect → drop
→ reconnect, assert the attempt counter, assert a malformed line does not kill the read loop. C.8's
logic without Bluetooth or real timeouts.

**Tier 3 — manual demos against AMD.** `docs/checklist-demos.md`, one entry per C.1–C.10:
preconditions, steps, expected result. Doubles as the script handed to a supervisor and the shot
list for the video.

**Compose UI instrumentation tests are deliberately skipped.** One screen, a week-7 deadline, and
the logic already lives in pure Kotlin. Stated here so it is a decision, not an omission.

---

## 10. AMD tool integration

The AMD tool ships in `AMDTOOL/`. Three setup steps, all required before any verification:

1. **Set Default Arena Settings to 20 × 20.** It ships at width 15 × height 20 — the legacy arena.
   Every coordinate verified against the default is against the wrong grid. Robot size 3 is correct.
2. **Configure Received Commands** to our movement tokens. They are user-editable; defaults are
   `f`, `r`, `tl`, `tr`, `sl`, `sr`, `beginExplore`, `beginFastest`, `sendArena`. Our control pad is
   six-way Ackermann (FL/F/FR, BL/B/BR) and AMD's vocabulary has no forward-arc, so map F→FORWARD,
   B→REVERSE, FL→ROTATE LEFT, FR→ROTATE RIGHT, BL/BR→the strafe slots. Labels will not match
   semantically; every button will still produce visible motion, which is what C.3 tests.
3. **Write a custom C# send script.** AMD's outbound format comes from editable scripts in
   `AMDTOOL/scripts/`. None of the shipped defaults emit `ROBOT,...` or `TARGET,...`, so without our
   own script C.9 and C.10 cannot be demonstrated against AMD at all. The script must convert
   AMD's top-left origin to our bottom-left (`y' = height-1-y`) and its degrees to letters.

**The AMD user guide's own checklist pages are stale** — they describe an older checklist whose
numbering conflicts with the current one. Use the tool; ignore its checklist pages.

Useful for development before the RPi exists: `sendArena` pushes AMD's arena to the tablet on
demand, and a Robot Status demo generator emits dummy statuses — between them, C.4, C.5, C.9 and
C.10 can all be exercised.

---

## 11. Open questions

These need an answer from a supervisor or from the team. None blocks starting work; all three
become expensive if discovered late.

1. **Does `ROBOT,7,2` name the robot's bottom-left cell or its centre?** The robot is 3×3 cells.
   The algorithms briefing *recommends* bottom-left, but its alternative representation explicitly
   permits the centre, and the ARCM slide prints "Robot (7, 2)" without saying. We draw bottom-left.
   If the RPi means centre, everything renders one cell off diagonally.
2. **Should `FACE` carry the coordinate?** The checklist text says yes, the briefing slide shows a
   format without it. We send it. If the RPi parser is written against the slide, it breaks. **Agree
   this with the RPi owner before either side writes a parser** (AGENTS.md §2.2).
3. **Must the stitched verification image be displayed on Android?** The general briefing permits
   "android or PC". This design assumes PC. If that is wrong, it is new Android scope.

---

## 12. Sources

| Fact | Source |
|---|---|
| C.1–C.10 wording | `docs/Android Remote Controller checklist.pdf` |
| Wire format examples | `docs/MDP ARCM Briefing Slides.pdf` slides 8–13 |
| Image pool, IDs 11–40 | `docs/MDP briefing(1).pdf` p.15 |
| 20×20 grid, robot 3×3, bottom-left origin | `docs/algarithms_briefing_25S2.pdf` p.9 |
| Weights and deadlines | `docs/MDP assessment and system checklist.pdf` pp.2–5 |
| Tablet model; RPi as RFCOMM server | `docs/RPI-InfraSetup-v5(05JAug2024).pdf` pp.1, 19 |
| AMD commands, arena defaults, script API | `AMDTOOL/AMDTOOL User Guide.pdf` pp.12, 16, 17; `AMDTOOL/scripts/` |

Visual design: <https://claude.ai/code/artifact/3196cb7d-b1f4-47b7-9f97-7c71f1c09556>
(working files in `docs/design/`).

> **Note on method.** Several of these documents carry load-bearing information *inside images*,
> which `pdftotext` silently drops. Three errors in this design were caused by trusting extracted
> text. Render slide pages and look at them.
