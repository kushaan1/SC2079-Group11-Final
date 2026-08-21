package com.mdp.grp11.session

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class RunTimerTest {

    private var clock = 0L
    private fun timer() = RunTimer { clock }

    @Test fun `a fresh timer is zero and idle`() {
        val t = timer()
        assertEquals(RunTimes(0L, 0L, null), t.times())
    }

    @Test fun `a running timer reports elapsed time`() {
        clock = 1_000
        val t = timer()
        t.start(RunKind.Exploration)
        clock = 4_500
        assertEquals(3_500L, t.times().exploration)
        assertEquals(0L, t.times().fastestCar)
        assertEquals(RunKind.Exploration, t.times().running)
    }

    @Test fun `stop freezes the elapsed value`() {
        clock = 0
        val t = timer()
        t.start(RunKind.Exploration)
        clock = 2_000
        t.stop()
        clock = 9_999
        assertEquals(2_000L, t.times().exploration)
        assertNull(t.times().running)
    }

    @Test fun `starting the other task banks the first one`() {
        clock = 0
        val t = timer()
        t.start(RunKind.Exploration)
        clock = 3_000
        t.start(RunKind.FastestCar)
        clock = 5_000
        assertEquals(3_000L, t.times().exploration)
        assertEquals(2_000L, t.times().fastestCar)
        assertEquals(RunKind.FastestCar, t.times().running)
    }

    @Test fun `resuming after stop accumulates rather than restarting`() {
        clock = 0
        val t = timer()
        t.start(RunKind.Exploration)
        clock = 2_000
        t.stop()
        clock = 10_000
        t.start(RunKind.Exploration)
        clock = 10_500
        assertEquals(2_500L, t.times().exploration)
    }

    @Test fun `reset zeroes only the named task`() {
        clock = 0
        val t = timer()
        t.start(RunKind.Exploration)
        clock = 3_000
        t.start(RunKind.FastestCar)
        clock = 5_000
        t.reset(RunKind.Exploration)
        assertEquals(0L, t.times().exploration)
        assertEquals(2_000L, t.times().fastestCar)
    }

    @Test fun `resetting the running task restarts its clock from now`() {
        clock = 0
        val t = timer()
        t.start(RunKind.Exploration)
        clock = 3_000
        t.reset(RunKind.Exploration)
        assertEquals(0L, t.times().exploration)
        clock = 4_000
        assertEquals(1_000L, t.times().exploration)
    }

    @Test fun `a clock that goes backwards never reports a negative elapsed and does not corrupt the banked total`() {
        clock = 1_000
        val t = timer()
        t.start(RunKind.Exploration)
        clock = 500 // clock jumps backwards while the run is in progress
        assertEquals(0L, t.times().exploration)
        t.stop() // banking must clamp too, or the backward jump poisons the total forever
        assertEquals(0L, t.times().exploration)
        assertNull(t.times().running)
        // resuming and advancing normally afterwards must accumulate cleanly, proving
        // the earlier backward jump left no residue in the banked total
        clock = 500
        t.start(RunKind.Exploration)
        clock = 1_500
        assertEquals(1_000L, t.times().exploration)
    }

    @Test fun `a clock that returns the same value twice yields zero elapsed, not a negative`() {
        clock = 5_000
        val t = timer()
        t.start(RunKind.Exploration)
        // clock does not advance before stopping
        t.stop()
        assertEquals(0L, t.times().exploration)
    }

    @Test fun `stop on an idle timer is a no-op`() {
        val t = timer()
        t.stop() // never started
        assertEquals(RunTimes(0L, 0L, null), t.times())

        clock = 1_000
        t.start(RunKind.Exploration)
        clock = 2_000
        t.stop()
        t.stop() // double stop
        assertEquals(1_000L, t.times().exploration)
        assertNull(t.times().running)
    }

    @Test fun `a later read reports a larger elapsed while the run is still going`() {
        clock = 0
        val t = timer()
        t.start(RunKind.Exploration)
        clock = 1_000
        val first = t.times().exploration
        clock = 2_500
        val second = t.times().exploration
        assertEquals(1_000L, first)
        assertEquals(2_500L, second)
        assertTrue(second > first)
    }
}
