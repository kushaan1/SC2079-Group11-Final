package com.mdp.grp11.protocol

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ImagePoolTest {

    @Test fun `digits map to 11 through 19`() {
        assertEquals("digit 1", imageLabel(11))
        assertEquals("digit 9", imageLabel(19))
    }

    @Test fun `letters skip I through R`() {
        assertEquals("letter A", imageLabel(20))
        assertEquals("letter H", imageLabel(27))
        assertEquals("letter S", imageLabel(28))
        assertEquals("letter Z", imageLabel(35))
    }

    @Test fun `arrows and stop occupy 36 to 40`() {
        assertEquals("up arrow", imageLabel(36))
        assertEquals("left arrow", imageLabel(39))
        assertEquals("stop", imageLabel(40))
    }

    @Test fun `ids outside the pool get a label rather than an error`() {
        assertEquals("unrecognised id", imageLabel(4))
        assertEquals("unrecognised id", imageLabel(99))
    }

    // --- The reference chart's data ----------------------------------------

    @Test fun `the pool is the thirty ids 11 to 40, in order`() {
        assertEquals(30, imagePool.size)
        assertEquals((11..40).toList(), imagePool.map { it.id })
    }

    /**
     * The chart and the status line must never disagree. They are graded
     * against each other in practice: C.9 puts the numeric id on the block,
     * the status line spells it out, and this chart is what the operator
     * checks both against.
     */
    @Test fun `every chart row agrees with the status line's label`() {
        imagePool.forEach { entry ->
            assertEquals(
                "chart row ${entry.id} disagrees with imageLabel(${entry.id})",
                imageLabel(entry.id),
                entry.label,
            )
        }
    }

    @Test fun `no chart row is the fallback label`() {
        assertTrue(
            "every id in the pool must have a real label",
            imagePool.none { it.label == "unrecognised id" || it.label.isBlank() },
        )
    }
}
