package com.mdp.grp11.config

import android.Manifest
import com.mdp.grp11.protocol.Face
import java.util.UUID

/**
 * Every tunable constant in the app. Nothing physical or protocol-related is
 * hardcoded at a call site.
 *
 * Background on the protocol choices is in `docs/design-decisions.md`.
 */
object Config {
    const val CELLS = 20
    const val MAX_OBSTACLES = 8

    /**
     * Task 1's start zone: 40cm square at the arena's bottom-left corner
     * (AGENTS.md 3.1), so 4 cells on a 10cm grid.
     *
     * Task 1 ONLY. Task 2 starts in a 60cm carpark whose position in the arena
     * is never given - its layout is defined relative to the goal obstacles,
     * at a distance unknown until the run (AGENTS.md 5.1, 5.4). There is no
     * defensible place to draw it, so the app does not.
     */
    const val TASK1_START_ZONE_CELLS = 4

    /**
     * NOT the robot's size. This is the algorithms deck's 30cm x 30cm
     * PLANNING footprint - an inflated safety margin. The real chassis is
     * ~18.7cm x 23cm (AGENTS.md 3.1), nearer 2x2 cells, and not square.
     *
     * Held at the planning figure for now. Since the robot's coordinate names
     * its CENTRE, this value only controls how big the box is drawn - it no
     * longer has to agree with AMD's own robot size, because a mismatch can no
     * longer shift where the robot sits. Changing it to the real chassis is
     * therefore a local change, whenever someone measures the car.
     *
     * Consequence worth knowing until then: the box on screen is ~60% wider
     * than the car it represents, which is visible in any photo of the tablet
     * beside the robot.
     */
    const val ROBOT_SIZE_CELLS = 3

    /**
     * Where a fresh arena parks the robot: the CELL its footprint is centred
     * on, in the same units an obstacle's coordinate uses.
     *
     * Cell (1,1) puts a 3-cell robot flush into the arena's bottom-left corner,
     * covering cells 0..2 on both axes. It is also [Arena.moveRobot]'s clamp
     * floor, so a drag hard into that corner lands back here exactly.
     *
     * A choice, not a specified position. The briefing says only that the robot
     * starts "in the 40x40cm start zone" (AGENTS.md 4.1) - never where in it or
     * facing which way - and Task 2's starting orientation is still open
     * (AGENTS.md 10).
     */
    const val ROBOT_START_X = 1f
    const val ROBOT_START_Y = 1f
    val ROBOT_START_HEADING: Float = Face.N.degrees

    /** Bluetooth Serial Port Profile. */
    val SPP_UUID: UUID = UUID.fromString("00001101-0000-1000-8000-00805F9B34FB")

    /** Client reconnect backoff. Repeats the last value indefinitely. */
    val BACKOFF_MS = listOf(1_000L, 2_000L, 4_000L, 5_000L)

    /** Ceiling on a pairing handshake, bounding a device stuck in BOND_BONDING. */
    const val BOND_TIMEOUT_MS: Long = 30_000L

    /**
     * Appended to every outbound line. `"\n"` is the RPi's framing and the
     * project default: RFCOMM is a byte stream with no message boundaries, so
     * without a delimiter consecutive sends concatenate on the wire.
     *
     * Set this to `""` to drive the **AMD debug tool** instead. AMD compares
     * each received chunk against its configured command strings verbatim, so
     * a trailing newline makes every token mismatch - the text still appears
     * in its RECEIVED TEXT panel, but nothing fires in its COMMAND LOG.
     *
     * Outbound only. Inbound framing always splits on `"\n"` whatever this says.
     */
    //const val OUTBOUND_TERMINATOR: String = "\n"
    const val OUTBOUND_TERMINATOR: String = ""

    /**
     * Idle interval after which an unterminated inbound line is flushed anyway.
     *
     * Framing waits for `"\n"` because a message can legitimately span two
     * reads, but AMD does not terminate what it sends, so without this its
     * messages would sit in the buffer forever. Tens of milliseconds is the
     * right order: longer than the gap between two reads of one message,
     * shorter than an operator would notice.
     */
    const val INBOUND_FLUSH_IDLE_MS: Long = 40L

    /**
     * Refresh rate for the on-screen run clocks. Purely cosmetic - RunTimer
     * computes elapsed time from its own clock, so a delayed tick costs
     * smoothness, never accuracy.
     */
    const val RUN_TIMER_TICK_MS: Long = 250L

    /**
     * Backstop on one discovery session. The platform's own window is ~12s and
     * ends with ACTION_DISCOVERY_FINISHED, so this only fires if that broadcast
     * never arrives - in which case the spinner would otherwise run forever.
     */
    const val DISCOVERY_TIMEOUT_MS: Long = 20_000L

    /**
     * Retained traffic lines for the raw log. A run generates thousands of
     * movement commands; older lines are dropped so memory stays bounded.
     */
    const val TRAFFIC_LOG_CAP = 200

    /**
     * Movement tokens, matching AMD's Settings -> Received Commands.
     *
     * **The field names describe the motion; the values are AMD's slot names,
     * and the two deliberately disagree.** The car is Ackermann - it cannot
     * strafe or turn on the spot - so AMD's six slots (`f`/`r`/`tl`/`tr`/`sl`/`sr`)
     * are mapped onto six arcs: `tl`/`tr` carry the forward arcs, `sl`/`sr` the
     * reverse ones.
     *
     * OPEN for the chassis owner: reversing with the wheels turned left swings
     * the front left and the rear right, so whether `sl` belongs under the
     * button labelled BL is a hardware convention this app cannot settle. If it
     * is backwards, swap these two values and the matching test expectations.
     */
    data class MoveTokens(
        val forward: String = "f",
        val reverse: String = "r",
        val forwardLeft: String = "tl",
        val forwardRight: String = "tr",
        val reverseLeft: String = "sl",
        val reverseRight: String = "sr",
        val stop: String = "s",
    )

    val moveTokens = MoveTokens()

    /** Task-level commands, as distinct from movement. These start a run. */
    data class TaskTokens(
        val beginExploration: String = "beginExplore",
        val beginFastest: String = "beginFastest",
        val sendArena: String = "sendArena",
    )

    val taskTokens = TaskTokens()

    /** Persisted layout format version. Bump on any breaking change to it. */
    const val ARENA_FORMAT_VERSION = "V1"

    /** Persisted-layout token for an absent optional field. */
    const val ARENA_FIELD_ABSENT = "-"

    /**
     * Runtime permissions for the Bluetooth link on Android 12+. All three are
     * one "Nearby devices" group, granted or denied together: SCAN for
     * `startDiscovery()` and `bondedDevices()`, CONNECT to open a socket and
     * read a device name.
     *
     * ADVERTISE has no consumer - it gates `ACTION_REQUEST_DISCOVERABLE`, which
     * this app never fires. It stays declared because the group is granted as
     * one anyway. Do not cite it as evidence the Listen role needs it.
     *
     * Without these `bondedDevices()` throws rather than returning an empty
     * list, so the picker must check them before calling the transport.
     */
    val BLUETOOTH_PERMISSIONS: List<String> = listOf(
        Manifest.permission.BLUETOOTH_CONNECT,
        Manifest.permission.BLUETOOTH_SCAN,
        Manifest.permission.BLUETOOTH_ADVERTISE,
    )

    /** Divisors for rendering a millisecond reading as mm:ss. */
    const val MILLIS_PER_SECOND = 1_000L
    const val SECONDS_PER_MINUTE = 60L
}
