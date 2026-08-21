package com.mdp.grp11.arena

import com.mdp.grp11.protocol.Face
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class GridTest {

    @Test fun `face parses case insensitively`() {
        assertEquals(Face.N, Face.parse("N"))
        assertEquals(Face.E, Face.parse("e"))
        assertEquals(Face.W, Face.parse(" W "))
        assertNull(Face.parse("NONE"))
        assertNull(Face.parse("Q"))
    }

    @Test fun `y flip maps bottom row to last canvas row`() {
        assertEquals(19, Grid.toCanvasRow(0))
        assertEquals(0, Grid.toCanvasRow(19))
        assertEquals(12, Grid.toCanvasRow(7))
    }

    @Test fun `y flip is its own inverse`() {
        for (y in 0 until 20) assertEquals(y, Grid.toCanvasRow(Grid.toCanvasRow(y)))
    }

    @Test fun `cellAt resolves corners`() {
        val g = 660f
        assertEquals(0 to 19, Grid.cellAt(1f, 1f, g))        // top-left pixel
        assertEquals(19 to 0, Grid.cellAt(659f, 659f, g))    // bottom-right pixel
        assertEquals(0 to 0, Grid.cellAt(1f, 659f, g))       // bottom-left pixel
    }

    @Test fun `cellAt clamps out of range input`() {
        val g = 660f
        assertEquals(0 to 19, Grid.cellAt(-50f, -50f, g))
        assertEquals(19 to 0, Grid.cellAt(9999f, 9999f, g))
    }

    @Test fun `centreOf returns the middle of the cell in canvas pixels`() {
        val g = 660f  // 33px cells
        assertEquals(16.5f to 643.5f, Grid.centreOf(0, 0, g))
        assertEquals(643.5f to 16.5f, Grid.centreOf(19, 19, g))
    }
}
