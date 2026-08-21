package com.mdp.grp11.ui

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The composables that surround it are not unit-tested here, but the mm:ss
 * conversion behind the two run clocks is a pure function and is what an
 * examiner actually reads off the screen.
 */
class FormatElapsedTest {

    @Test fun `zero renders as a padded mm ss`() {
        assertEquals("00:00", formatElapsed(0L))
    }

    @Test fun `sub-second remainders are truncated, never rounded up`() {
        // 59.999s is still 59s: a clock that flicks to 01:00 before the minute
        // has elapsed overstates a scored run.
        assertEquals("00:59", formatElapsed(59_999L))
    }

    @Test fun `seconds roll over into minutes`() {
        assertEquals("01:05", formatElapsed(65_000L))
    }

    @Test fun `minutes are not wrapped at an hour`() {
        // 61 minutes 20 seconds. Wrapping here would understate the reading by
        // a full hour rather than merely looking odd.
        assertEquals("61:20", formatElapsed(3_680_000L))
    }
}
