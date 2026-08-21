package com.mdp.grp11.session

enum class RunKind { Exploration, FastestCar }

data class RunTimes(
    val exploration: Long = 0L,
    val fastestCar: Long = 0L,
    val running: RunKind? = null,
)

/**
 * Two independent stopwatches, one per graded task. Both evaluation runs are
 * scored on time, so the tablet times them.
 *
 * Takes a clock function instead of reading the system clock, which is what
 * makes it testable without sleeping.
 *
 * [nowMs] must be monotonically non-decreasing. Elapsed time is folded into a
 * running total, so a clock that goes backwards corrupts that total for the
 * rest of the session rather than producing one bad reading. Each subtraction
 * is clamped at zero as a backstop, but that only hides the symptom - do not
 * wire in `System.currentTimeMillis()`, which jumps on an NTP resync.
 */
class RunTimer(private val nowMs: () -> Long) {

    private val banked = mutableMapOf(
        RunKind.Exploration to 0L,
        RunKind.FastestCar to 0L,
    )
    private var running: RunKind? = null
    private var startedAt: Long = 0L

    /**
     * Starts [kind]. Whatever task is currently running is stopped first and its
     * elapsed time banked — including [kind] itself, so starting an already-running
     * task banks its progress and restarts its clock from now rather than being a
     * no-op.
     */
    fun start(kind: RunKind) {
        stop()
        running = kind
        startedAt = nowMs()
    }

    /** Banks the running task's elapsed time and goes idle. */
    fun stop() {
        val kind = running ?: return
        banked[kind] = (banked[kind] ?: 0L) + maxOf(0L, nowMs() - startedAt)
        running = null
    }

    /** Zeroes [kind] only. If it is running, its clock restarts from now. */
    fun reset(kind: RunKind) {
        banked[kind] = 0L
        if (running == kind) startedAt = nowMs()
    }

    fun times(): RunTimes = RunTimes(
        exploration = elapsed(RunKind.Exploration),
        fastestCar = elapsed(RunKind.FastestCar),
        running = running,
    )

    private fun elapsed(kind: RunKind): Long {
        val base = banked[kind] ?: 0L
        return if (running == kind) base + maxOf(0L, nowMs() - startedAt) else base
    }
}
