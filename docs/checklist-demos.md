# Android Remote Controller — Checklist Demo Scripts

This is the script for demonstrating checklist items **C.1 through C.10** to a supervisor, and
the shot list for the module video. Verification is against the **AMD tool**, not the RPi — the
checklist itself names AMD as the reference peer for C.1, C.3, C.4 and C.8.

Each C.n section is independently demonstrable — run them in any order, in one sitting. Sections
after C.10 are supporting evidence: 8 on-device Bluetooth scenarios that stress-test the transport
(`BluetoothSppTransport` / `ConnectionRepository`) beyond what C.2 and C.8 alone exercise, the
save/load persistence walkthrough, and a general pre-flight pass. None of these three are separate
checklist items; run them before the supervisor arrives, not in front of them, except where a shot
note below says otherwise.

**Android has no Compose UI instrumentation tests and no way to unit-test a real
`BluetoothSocket`.** Everything in this document — the transport, every gesture, the whole UI,
save/load — is verified by nothing except a human running these steps on real hardware. Run all of
it, not just C.1–C.10, before Week 7.

---

## 0. Read this first

### 0.1 Three protocol questions — get a yes/no from the RPi owner before this demo runs

These are unresolved as of this writing (`docs/superpowers/specs/2026-08-21-android-controller-design.md`
§11). Getting any of them wrong is a silent, plausible-looking failure, not a crash — exactly the
kind of thing that looks fine to a supervisor watching from across the table.

| # | Question | What we currently do | Risk if the answer is different | RPi owner's answer |
|---|---|---|---|---|
| 1 | Does `ROBOT,7,2` name the robot's **bottom-left cell** or its **centre**? The robot is 3×3 cells. | We draw it as bottom-left (`ArenaCanvas.drawRobot`: anchored at `cell`, footprint extends up-and-right). | Every drawn robot position is off by one cell, diagonally, for the rest of the demo. | Y / N — bottom-left ⬜ / centre ⬜ |
| 2 | Should `FACE` carry the obstacle coordinate? The checklist text demands "target face **and** obstacle coordinate"; the briefing slide shows a format without it. | We send the superset: `FACE,B3,(14,15),E`. | If the RPi parser is written against the slide's shorter format, it may reject or mis-parse every `FACE` line we send. | Y / N — accepts the superset ⬜ |
| 3 | Must the stitched verification image (Task 1) display **on the Android tablet**, or is the **PC display** sufficient? | This app was built assuming PC. There is no stitched-image screen in the Android module. | If the answer is "must be on Android," that is new scope, not a bug in what exists today — it will not appear in any of the sections below. | Y (PC is fine) / N (needs Android) ⬜ |

None of these block running the demo below — they change what "correct" looks like for C.10 (#1),
for whether the RPi actually acts on our `FACE` messages (#2), and for whether Task 1's stitched
image belongs in this app at all (#3). Get answers before the supervisor sees this, not during.

### 0.2 Known limitations — do not walk into these live

- **Dragging an obstacle in the AMD tool does not appear on the tablet.** Obstacles travel
  tablet→robot in this protocol, not the other way (controller ruling R22). AMD's send script
  (`AMDTOOL/scripts/mdp_grp11.cs`) emits `AMDADD,(x,y)` / `AMDSUB,(x,y)` when its virtual obstacle is
  dragged, and `Decoder.decode()` has no case for either verb — they fall through to
  `Inbound.Unknown` and never touch the arena. If someone drags an obstacle in AMD expecting it to
  show up on the tablet, it will not, and the raw log will show the unparsed `AMDADD`/`AMDSUB` line
  as the only evidence anything happened. **Place every obstacle on the tablet itself** — that is
  what C.6 and C.7 actually test. AMD's virtual **robot** drag is unaffected by this: it emits
  `ROBOT,<x>,<y>,<letter>`, which the decoder does understand (see C.10).
- **`PreferencesArenaStore` (the real save/load backing store) has zero automated test
  coverage.** This was a deliberate, ruled trade during development — every other part of save/load
  is proven only against an in-memory fake. The on-device scenario in §"Arena persistence" below is
  the *only* verification this class will ever get. Do not skip it.
- **A connect attempt can take up to ~12 seconds to fail** when the peer is powered off or
  unreachable (the real `BluetoothSocket.connect()` blocks that long before giving up). That is
  expected, not a hang. Don't start tapping CONNECT repeatedly during that window — see transport
  scenario 1 below for why that specifically matters.

### 0.3 One-time AMD tool setup (do this before any item below)

1. **Settings → Default Arena Settings** → Arena width **20**, Arena height **20**, Robot size **3**.
   AMD ships pointed at a 15×20 legacy arena; every coordinate checked against the default is checked
   against the wrong grid.
2. **Settings → Custom Scripts** → load `AMDTOOL/scripts/mdp_grp11.cs`. This is our own send script;
   none of AMD's shipped defaults emit `ROBOT,...` or `TARGET,...`, so without it C.9 and C.10 cannot
   be demonstrated against AMD at all.
3. **Settings → Received Commands** → set FORWARD `f`, REVERSE `r`, ROTATE LEFT `tl`, ROTATE RIGHT
   `tr`, STRAFE LEFT `sl`, STRAFE RIGHT `sr` — must match `Config.moveTokens` in
   `android/app/src/main/java/com/mdp/grp11/config/Config.kt`. The control pad is six-way Ackermann
   and AMD's vocabulary has no forward-arc, so the labels will not match semantically (our "FL" maps
   to AMD's ROTATE LEFT, not a forward-left arc) — every button still produces visible motion, which
   is what C.3 actually tests. `Config.MoveTokens`' FIELD names describe the motion (`forwardLeft`,
   `reverseLeft`, …) while the VALUES stay AMD's slot names; the two deliberately disagree.
   **Still open for the chassis owner:** reversing an Ackermann car with the wheels turned left
   swings the front left and the *rear* right, so whether `sl` belongs under the button labelled BL
   or BR is a hardware convention, not something the app can decide. If BL and BR turn out reversed
   on the real robot, swap those two values in `Config.MoveTokens` and the matching expectations in
   `ControlPadTest` — nothing else changes.
4. Pair the tablet with the AMD host machine (and with the RPi, once it exists) in Android/Windows
   Bluetooth settings ahead of time, outside the demo. The app can now scan and pair from inside
   itself (C.2's `SCAN` button), but pairing beforehand is still the right move for the graded run:
   it is one less system dialog between you and a working link, and the `PAIRED` section connects in
   a single tap. Demonstrate the scan deliberately during C.2, then rely on the pairing you did
   earlier for everything after it.
5. **Ignore the AMD user guide's own checklist pages** — they describe an older, differently-numbered
   checklist. Use the tool; the checklist below is the current one.

### 0.4 Quick reference — message formats used throughout

| Direction | Format | Example |
|---|---|---|
| Outbound | `ADD,B<id>,(<x>,<y>)` | `ADD,B1,(10,6)` |
| Outbound | `SUB,B<id>` | `SUB,B1` |
| Outbound | `FACE,B<id>,(<x>,<y>),<N\|E\|S\|W\|NONE>` | `FACE,B3,(14,15),E` |
| Outbound | movement / task tokens | `f`, `r`, `tl`, `tr`, `sl`, `sr`, `s`, `beginExplore`, `beginFastest`, `sendArena` |
| Inbound | `MSG,[<text>]` | `MSG,[Moving]` |
| Inbound | `TARGET,<id>,<targetId>` or `TARGET,<id>,<targetId>,<face>` | `TARGET,B2,11` / `TARGET,B2,11,N` |
| Inbound | `ROBOT,<x>,<y>,<face>` | `ROBOT,7,2,E` |

Obstacle ids accept `B2` or bare `2`. Target ids are **never range-checked** — the checklist's own
worked example uses target id 4, outside the 11–40 image pool, and it must still work. Any unrecognised
verb decodes to `Unknown` and is only ever logged, never thrown — a malformed line cannot crash the
read loop or look like a disconnect.

---

## C.1 — Bidirectional text over Bluetooth

**Setup:** AMD tool running on a laptop, arena set to 20×20 (§0.3), app installed on the tablet, not
yet connected.

**Steps:**
1. In the app, open the device picker (tap the connection bar) and tap `WAIT FOR INCOMING (AMD)`.
2. In AMD: Bluetooth → Scan For Devices → select the tablet → connect.
3. In AMD's `SEND TO REMOTE` box, type `MSG,[Hello]` and press SEND.
4. In the app, tap an empty arena cell and lift your finger.

**Expected:**
- The app's raw Bluetooth log (bottom-right panel) shows `RX MSG,[Hello]`; the status panel above it
  shows `Hello`, not the raw `MSG,[Hello]` string.
- AMD's `RECEIVED TEXT` panel shows `ADD,B1,(x,y)` with the cell you tapped.

**Failure signature:** the connection bar shows the AMD device's name (implying Connected) but
nothing above happens on either side within a couple of seconds — that is a swallowed drop, not a
slow link. See transport scenario 1.

**Shot:** the tablet screen and AMD's laptop screen in one frame (phone/second camera), showing the
typed line on one side and the raw log line appearing on the other within the same take.

**Contributor:** ______________________

---

## C.2 — GUI scans, selects and connects to a Bluetooth device

**Setup:** the RPi (or the AMD host laptop) powered on and discoverable. A second device already
paired with the tablet is useful for showing both halves. App not connected to anything.

The picker has **two sections**, and the checklist's three verbs map onto them:

| Section | Source | Covers |
|---|---|---|
| `PAIRED` | `bondedDevices()` — no radio traffic | selection, connection |
| `FOUND` | a live `startDiscovery()` behind the `SCAN` button | **scanning** |

**Steps — show the scan, since that is the word the checklist uses:**
1. Open the device picker.
2. Tap `SCAN`. A spinner appears next to the `FOUND` heading and the button becomes `STOP`.
3. Devices appear under `FOUND` as they answer — first-seen first, which is roughly nearest first.
   Anything already in `PAIRED` is filtered out rather than listed twice.
4. Tap `CONNECT` on the target. Scanning stops automatically before the connect begins.
5. Watch the connection bar (top of the right-hand column).

**Expected:**
- Bar reads `CONNECTING…`, then the connected device's name, with no further taps.
- The scan ends by itself after roughly 12 seconds (the platform's own discovery window) — the
  spinner stops and the button returns to `SCAN`. This is normal, not a fault.
- Connecting to something in `FOUND` that has never been paired raises the **system pairing dialog**
  first; accept it and the connection proceeds. That path runs `ensureBonded()` under
  `Config.BOND_TIMEOUT_MS`, which is what the bonding cases below exercise.
- Devices in `PAIRED` are listed even when out of range — that list is bonding records, not a scan.

**If the scan is going to be skipped on the day:** everything except step 2–3 still works with
devices paired in Android Settings beforehand. Say so rather than pressing `SCAN` and narrating an
empty list — a scan that finds nothing looks like a broken app even when it is a quiet room.

> Discovery and RFCOMM contend for the same radio, which is why the app stops the scan before it
> connects, when the sheet closes, and when the Activity goes away. If a connection is unusually slow
> to establish, check that a scan is not still running.

**Also verify — permission denial (do this once, deliberately):**
1. Fresh install, or with Bluetooth permission revoked in Android Settings.
2. Open the device picker.
3. **Expected:** the sheet shows an explanation and two buttons, `GRANT BLUETOOTH PERMISSION` and
   `OPEN APP SETTINGS` — never an empty device list. An empty list with no explanation reads as a
   broken app, not a permission the operator can act on. Deny the system prompt once, confirm the
   explanation replaces the list; tap `GRANT`, confirm the system prompt reappears.

**Also verify — bonding edge cases (covers a real defect class, I-4, found in review):**
1. **(a)** Connect to a device that is paired but has never completed a full bond handshake, if you
   have one available, and accept the pairing prompt when it appears — should connect normally.
2. **(b)** Same, but reject the pairing prompt — expect a `Failed · Pairing required or failed`
   state within about 40 seconds, **not** an indefinite spinner.
3. **(c)** Start a bond from Android Settings on a different device, leave it sitting at the PIN
   prompt (don't confirm), then tap Connect on that same device in the app. **This is the scenario to
   watch closely**: does the app hang forever in `CONNECTING…`? A bond stuck in `BOND_BONDING` with no
   other actor producing a terminal broadcast is exactly the condition a fixed 30-second bond timeout
   exists to catch (`Config.BOND_TIMEOUT_MS`). If it never resolves, that timeout has a gap.

**Contributor:** ______________________

---

## C.3 — Interactive control of robot movement over Bluetooth

**Setup:** connected to AMD (either role), Received Commands mapped per §0.3.

**Steps:**
1. With nothing connected, confirm all six pad buttons and STOP are visibly disabled (greyed out) —
   they must not be tappable before a link exists.
2. Connect. Tap `FL`, `F`, `FR`, `BL`, `B`, `BR` in turn, pausing between each to watch AMD's virtual
   robot.
3. Tap `STOP`.

**Expected:** every tap produces visible motion in AMD (`FL`/`FR` rotate the virtual robot left/right,
`F`/`B` drive it forward/back, `BL`/`BR` hit AMD's strafe slots) — the checklist requires interactive
GUI control of movement, explicitly *not* a text box for typing raw commands, and this pad has no
text entry anywhere. Each tap produces exactly one `TX <token>` line in the raw log.

**Shot:** the tablet's control pad and AMD's virtual robot in one frame — a button press and the
resulting motion in the same take is the single clearest proof this item asks for.

**Contributor:** ______________________

---

## C.4 — Remote status updates via a selective TextView (not a raw dump)

**Setup:** connected. STATUS panel visible (tap `OK` on any open face compass first, or don't select
a block — the compass replaces the status panel while a block is selected).

**Steps:**
1. From AMD, send `MSG,[Ready]`.
2. Confirm the STATUS panel shows exactly `Ready` — no brackets, no `MSG,` prefix.
3. Send `TARGET,B1,15,N` (place an obstacle first if none exists, so `B1` refers to something real).
4. Confirm STATUS still reads `Ready` (unchanged) and a *separate* line below it now reads something
   like `Target 15 · digit 5 · at B1`.
5. Send `ROBOT,5,5,N`.
6. Confirm STATUS and the target line are both unaffected by the `ROBOT` line.
7. Scroll to the raw log panel and confirm all three RX lines from steps 1, 3 and 5 are present,
   verbatim, in both directions.

**Expected:** the status panel only ever changes on an inbound `MSG`; it never renders a raw protocol
line. The raw log renders everything, unfiltered. Two separate panels doing two separate jobs is the
point — the checklist explicitly forbids "all the text data that is being streamed" appearing in the
status view.

**Failure signature:** STATUS panel showing `MSG,[Ready]` verbatim, or changing on a `TARGET`/`ROBOT`
line, is exactly the failure this item checks for.

**Contributor:** ______________________

---

## C.5 — Numbered blocks and robot heading visible

**Setup:** connected. One obstacle placed on the tablet (tap an empty cell), then tap `OK` on the
face compass that opens so nothing stays selected — the target line only renders on the STATUS
panel, which is hidden behind the compass while a block is selected.

**Steps:**
1. From AMD, send `TARGET,B1,26` (or the checklist's own example, `TARGET,B1,4`, to also confirm
   out-of-range ids render).
2. Confirm the obstacle's block now shows the numeral (`26` or `4`) in large white text, and the
   STATUS panel's target line names it (`Target 26 · letter G · at B1`, or `Target 4 · unrecognised
   id · at B1` for the out-of-range example — "unrecognised id" is the documented behaviour for ids
   outside the 11–40 pool, not a bug).
3. Send `ROBOT,5,5,N` (or drag AMD's virtual robot to a known cell so its script emits the
   equivalent `ROBOT,<x>,<y>,N`).
4. Confirm the yellow 3×3 robot block appears anchored with its bottom-left corner at (5,5), **and**
   a filled dark triangle inside it points toward the top of the grid.
5. **Check the heading against something you know is true, not by eye.** If a real robot is on hand
   and physically facing away from the start zone (i.e. north in arena terms), confirm the triangle
   on screen also points away from the start-zone corner. If no robot is on hand, send each of
   `ROBOT,5,5,E`, `ROBOT,5,5,S`, `ROBOT,5,5,W` in turn and confirm the triangle rotates to point
   right, down, and left respectively, in that order, using the axis labels (now on both edges) to
   confirm "up" on screen is the higher-numbered row.

**Expected:** the target id is visible on the block, and the robot's position **and** heading are
both visible — a filled triangle spanning most of the 3×3 footprint, pointing in the reported
compass direction (`drawHeadingArrow` in `ArenaCanvas.kt`, added in commit `4078aa7`).

**Failure signature — read this before signing off:** `ROBOT,...,N` producing a triangle that points
toward the **bottom** of the screen (or `S` pointing up) means the arena is mirrored vertically. This
looks entirely plausible to someone unfamiliar with the convention — a triangle pointing *somewhere*
is easy to wave through without noticing it points the wrong way. That is exactly why step 5 asks you
to check a known heading against the physical robot (or a deliberate N→E→S→W sweep) rather than
eyeballing a single reading and moving on.

**Shot:** the tablet screen and the physical robot in one frame, robot facing a known direction,
tablet showing the matching triangle — the clearest single proof this item asks for.

**Contributor:** ______________________

---

## C.6 — Place, drag and remove obstacles; coordinates sent only on finger-lift

**Setup:** connected, arena reset (empty).

**Steps:**
1. Tap an empty cell. Watch the raw log the instant you lift your finger.
2. Tap `OK` on the compass that opens. Watch the raw log — nothing new should appear; a bare
   selection must never transmit.
3. Press and slowly drag the block across roughly five cells, watching the raw log continuously
   throughout the drag (not just at the end).
4. Lift your finger.
5. Press the same block again and drag it entirely off the edge of the grid, then lift.

**Expected:**
- Step 1: exactly one `TX ADD,B1,(x,y)`, matching the tapped cell.
- Step 2: zero new lines.
- Step 3 (**during** the drag): **zero** new lines, for the whole drag, regardless of how many cells
  it crosses.
- Step 4 (on lift): exactly one more `TX ADD,B1,(new-x,new-y)`.
- Step 5: the block disappears, the whole canvas flags the destructive action (not a small target),
  and exactly one `TX SUB,B1` appears; the obstacle counter decrements.

**Failure signature:** a `TX ADD` line for every cell crossed mid-drag means C.6 is failing and would
flood the real link during a run — this is the single most load-bearing thing to watch for in this
item. A drag that ends with **no** `ADD` at all (silently swallowed) is the inverse failure and just
as bad.

**Reminder:** do not try this by dragging an obstacle in the AMD tool instead — that direction is not
wired (§0.2). This item is specifically about dragging on the tablet.

**Shot:** the canvas and the raw log panel in the same frame, filmed continuously through one slow
drag — the empty stretch of log during the drag, followed by exactly one line on lift, is the whole
proof in a single unbroken shot.

**Contributor:** ______________________

---

## C.7 — Face compass sets an image face; block appearance changes; FACE transmitted

**Setup:** connected, one obstacle already placed (from C.6).

**Steps:**
1. Tap the existing block (not empty ground). Confirm the compass opens (`IMAGE FACE · B1`) and the
   raw log shows nothing new — selecting a block that already exists must never re-announce it.
2. Tap the `N` key.
3. Observe the block and the raw log.
4. Tap `N` again (the same face).
5. Observe the block and the raw log again.
6. Tap `OK` to close the compass.

**Expected:**
- Step 2/3: a yellow bar appears along the block's top (north) edge; raw log shows
  `TX FACE,B1,(x,y),N`.
- Step 4/5: the bar disappears; raw log shows `TX FACE,B1,(x,y),NONE`. Tapping an already-active face
  again is the deliberate way back for an operator who mis-tapped on a 4.7 mm block — it is not a
  toggle bug.
- The block's face bar (what we annotated) is a different fact from any face a `TARGET,...,<face>`
  message later reports (what the robot found) — both can be shown on the same block at once and are
  not the same field.

**Contributor:** ______________________

---

## C.8 — Link drop and recovery keep the app responsive (Listen role)

**Setup:** connected via `WAIT FOR INCOMING (AMD)`.

**Steps:**
1. In AMD's Bluetooth menu, **Disconnect**.
2. Watch the connection bar and confirm the rest of the screen (arena, panels) still redraws and
   responds to touch — nothing should freeze.
3. In AMD, **Connect** (or "Reconnect to last device") again.
4. Confirm recovery on the tablet with **zero taps**.

**Expected:**
- Immediately after AMD disconnects: connection bar reads `RECONNECTING · RETRY 1`, then `RETRY 2`,
  and so on as the backoff (1 s → 2 s → 4 s → 5 s, repeating) progresses. The control pad and task
  buttons disable but nothing else about the app locks up.
- On AMD reconnecting: the bar returns to showing the device's name with no tablet-side action.

**Also run — 5 drop cycles (Listen-role reconnect, the proper C.8 stress test):**
Repeat Disconnect → Connect in AMD five times in a row without restarting the app. Confirm the SDP
record re-registers each time and AMD's own device list still shows the tablet's service on the fifth
cycle, not just the first.

**Failure signature:** the bar shows the device name (implying `Connected`) but the app never
responds to a tapped movement button — that is a swallowed drop (see transport scenario 1
immediately below; run it right after this item, on the same session, since it is the same failure
family under a harder trigger).

**Contributor:** ______________________

---

## C.9 — TARGET messages update the block

**Setup:** connected, arena reset. Place **two** obstacles (tap two empty cells, `OK` the compass
each time) so the second one is `B2`. If C.6/C.7 already left one obstacle placed as `B1`, placing
one more now gets you `B2` directly.

**Steps:**
1. From AMD, send `TARGET,B2,11`.
2. Confirm `B2`'s block now shows `11`, and (with nothing selected) the STATUS panel's target line
   reads `Target 11 · digit 1 · at B2`.
3. Send `TARGET,B2,11,N`.
4. Confirm `B2` additionally shows a face bar on its north edge — this is the *robot's* reported
   face, kept separate from anything set via the C.7 compass.
5. Send `TARGET,B9,20` (an obstacle id that does not exist — only `B1`/`B2` are placed).
6. Confirm nothing changes on the canvas and no phantom block appears; the raw log shows the line
   was received but ignored.

**Expected:** both the 3-argument and 4-argument `TARGET` forms are accepted; an unknown obstacle id
is logged and ignored, never auto-created.

**Contributor:** ______________________

---

## C.10 — ROBOT messages move and rotate the robot

**Setup:** connected.

**Steps:**
1. Send `ROBOT,7,2,E`.
2. Confirm the yellow 3×3 block appears anchored with its bottom-left corner at (7,2).
3. Send `ROBOT,10,10,N` and confirm the block relocates.
4. Send an out-of-range pose, e.g. `ROBOT,25,25,N` (outside 0..19).
5. Confirm the robot does **not** move or disappear — the previous, in-range position is retained.

**Expected:** every valid pose relocates the robot; an out-of-range pose is logged in the raw log but
otherwise ignored (never clamped to the nearest valid cell — a clamped position looks plausible and
would be wrong; an unmoved robot is obviously wrong, which is the point).

**Reminder — open question #1 (§0.1):** if the RPi owner confirms `ROBOT,x,y` names the robot's
*centre* rather than its bottom-left cell, every position drawn in this item is one cell off,
diagonally. Re-run this section once that answer lands.

**Failure signature (from the AMD integration script, if driving the virtual robot instead of typing
`ROBOT,...` by hand):** dragging AMD's virtual robot to AMD's top-left corner should draw the robot in
the arena's top-left corner too (arena "up" is the higher-y direction in both views, even though the
underlying y numbers differ after the script's coordinate re-indexing). If the two displays instead
agree on left/right but disagree on top/bottom — an AMD-top drag lands the app's robot at the
bottom — the y-flip is inverted somewhere. That is a vertical-mirror bug, not a rounding error, and it
will be visually obvious once you know to look for it.

**Shot:** tablet screen and AMD's virtual robot in one frame, showing a drag on one side and the
matching relocation on the other in the same take.

**Contributor:** ______________________

---

## Bluetooth transport reliability — 8 on-device scenarios

Supports **C.2** and **C.8**. `BluetoothSppTransport`/`ConnectionRepository` cannot be exercised on
the JVM — `FakeTransport` proves the reconnect *state machine* is correct, but nothing in the unit
suite touches a real `BluetoothSocket`. A review of this code (documented in
`.superpowers/sdd/2026-08-21-android-controller/task-10-findings.md`) found one Critical and seven
Important defects across four fix rounds, every one a variant of the same root cause: **a stale or
superseded connect attempt damages a healthy session it has nothing to do with.** These 8 scenarios
exist specifically to catch that family on real hardware, where it can only actually occur.

**Log every `connected` transition with a timestamp while running these** (logcat filtered on the app
process is enough) — several of these are judged by timing, not just end state.

### 1. Confirms/denies the Critical defect (C-1) — run this one first

Client role, connected to a real peer (RPi if available, else any paired device you can power off).
Kill the peer's radio **without a clean close** (pull its battery / toggle airplane mode instantly —
not a graceful disconnect), then **immediately** tap a movement control so `send()` fails and a
reconnect kicks off. Restore the peer so reconnect succeeds. **Then do nothing for 60 seconds** and
just watch.

**Expected:** reconnect succeeds once and stays connected. **Confirms the defect if**, sometime in
that 60-second window, the state spontaneously flips `true → false` with nothing touching the tablet,
followed by a second reconnect 10–25 seconds later. That is a stale reader from the *old* socket
finally timing out and clearing `connected` on the *new*, healthy link. Also check logcat for
`CloseGuard` warnings mentioning `BluetoothSocket` — a sign a socket was never closed.

### 2. Clean EOF drop

Peer closes the connection cleanly (not a radio kill). Expect exactly **one** `true → false`
transition and exactly one reconnect — no spontaneous extra flips.

### 3. Instance reuse

10 consecutive connect/close cycles on the same running app (don't restart it). Session 10 must still
deliver lines correctly, and logcat must not show an accumulating pile of `CloseGuard` warnings across
the cycles.

### 4. Framer integrity across a reconnect

Have the peer send a partial line with no trailing newline (e.g. `AL`), then drop the link before
completing it. Reconnect, then have the peer send `IGN|1|11\n`. The first line the app receives after
reconnect must be exactly `IGN|1|11` — never `ALIGN|1|11`. (The line-framing buffer must be cleared on
disconnect, not merged across sessions.)

### 5. Unpaired / bonding edge cases (I-4)

Same as C.2's "also verify" block above — reproduced here because it is fundamentally a transport
scenario: (a) accept an unpaired device's pairing prompt → connects; (b) reject it → fails within
~40 s with a message like "Pairing required or failed," not an indefinite hang; (c) start a bond from
Android Settings, leave it at the PIN prompt, then tap Connect in the app → does it hang forever, or
does the 30-second bond timeout recover it?

### 6. Confirms/denies I-2 — a connect that outraces a cancel

Connect to a paired but powered-off device. While the app still shows "Connecting…", tap Disconnect.
Then power the device on so the in-flight connect attempt succeeds anyway. **Expected:** the app must
not end up silently reading from a link it believes it already disconnected — it should either stay
disconnected or clearly show the new connection, never a state that contradicts what's actually
open.

### 7. Which socket stage actually wins

(Requires a temporary logging build, not a stock one — coordinate with whoever built the transport if
this is needed for the video; otherwise this can be inferred from consistent, fast connects across
the other scenarios.) Expected: the insecure RFCOMM socket stage succeeds every time on this
hardware; the reflection-based fallback stage should never fire on API 31+.

### 8. Listen-role reconnect across 5 cycles (this is C.8's own item, repeated here for completeness)

See C.8 above — AMD's "Reconnect to last device" across 5 drop cycles, confirming the SDP record and
service visibility survive every cycle.

**Contributor:** ______________________

---

## Arena persistence — on-device save/load scenario

Supports **C.6/C.7** as evidence, and is the **only verification `PreferencesArenaStore` will ever
get** — every other part of save/load in this codebase is tested only against an in-memory fake,
which proves the ViewModel logic and proves nothing about whether bytes actually reach disk. If step
4 below fails, save/load is broken in a way nothing else in this project will catch.

**Setup:** connected (for step 5's raw-log check), arena reset.

**Steps:**
1. Place at least three obstacles, annotate a face on at least one of them (C.7's compass), then tap
   `SAVE` and give the layout a name.
2. Build a **second**, different layout (different obstacle count/positions) and save it under a
   different name. Confirm both names appear when you tap `LOAD`.
3. **Force-stop the app from Android Settings** — not just background it — and relaunch.
4. Confirm both saved names still appear under `LOAD`. Load the first one. Every obstacle must return
   to its exact cell, and the annotated face must still be annotated.
5. With a peer connected, watch the raw log while loading a layout **over** the current one (don't
   reset first). Confirm the order is: a `SUB` for every obstacle the robot currently knows about,
   **then** an `ADD` for every restored obstacle, **then** a `FACE` for the one carrying an
   annotation — retractions strictly before announcements. This is the resync behaviour that keeps the
   robot from believing a stale layout is still current.
6. Load the second layout **over** the first, same check: all of the first layout's obstacles
   retracted before any of the second's are announced, and the board ends up showing only the
   second layout's obstacles.
7. Reset the arena (clears the board). Confirm the saved layout names are **still listed** under
   `LOAD` — reset clears the on-screen board, not the persisted store.

**Contributor:** ______________________

---

## General on-device acceptance pass

Run this once, start to finish, before any supervisor sees the app — it was never runnable on the
build machine (`:app:installDebug` needs a physical device, which the build environment did not
have), so every line below is unverified until someone runs it on the actual Android 14 tablet, in
landscape.

1. **Launch.** App opens in landscape without crashing. The arena renders square, with axis labels
   0..19 along the bottom and left edges (0 at the start-zone corner, 19 at the far edge), and the
   start zone is shaded.
2. **Bluetooth permission.** On first launch the runtime permission prompt appears
   (`BLUETOOTH_CONNECT`/`BLUETOOTH_SCAN` on Android 12+). Deny it once, deliberately: the device
   picker must show an actionable explanation, not an empty list (see C.2's "also verify").
3. **Tap to place.** Tap an empty cell: a block appears **and** the raw log shows a matching `ADD` —
   this is ruling R33; it was missing entirely until a review caught it.
4. **Drag to move.** Drag a block across several cells. The log must show nothing during the drag and
   exactly one `ADD` on finger-lift (this is C.6, repeated here as a smoke test).
5. **Drag off to remove.** Drag a block outside the grid: the whole canvas flags the destructive
   action, and a `SUB` is sent.
6. **Tap to open the compass.** Tapping an existing block opens the face compass and sends nothing.
   If a message appears, selecting a block is re-announcing an obstacle that never moved.
7. **Face annotate and clear.** Set a face, confirm `FACE,B<n>,(x,y),<letter>`. Tap the same face
   again — it must clear, sending `...,NONE`.
8. **Run controls.** Tap `IMAGE REC` (or `FASTEST`): the robot must receive the matching task token
   **and** the clock must start, in one action. Confirm both start buttons and the same button
   disable while a run is active, and re-enable after `END RUN`.
9. **Layout under volume.** After a run generates several hundred log lines, confirm the newest line
   is still visible without scrolling, and that the log panel has not been squeezed off-screen by the
   rest of the right-hand column on the actual device.

**Contributor:** ______________________
