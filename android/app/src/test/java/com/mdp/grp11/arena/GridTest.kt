package com.mdp.grp11.arena

import com.mdp.grp11.config.Config

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

    // --- Continuous conversions, for the robot's fractional pose

    private val gridPx = 660f   // 33px cells

    /**
     * The robot and an obstacle now count in the SAME units - a cell index -
     * so the continuous conversion at (i,j) must land exactly where the
     * discrete one puts cell (i,j)'s centre. This identity is the whole point
     * of the change; if it ever breaks, robot and obstacle coordinates have
     * silently drifted apart by half a cell.
     */
    @Test fun `the continuous conversion at a cell index IS that cell's centre`() {
        for (x in 0 until 20) {
            for (y in 0 until 20) {
                val (cx, cy) = Grid.centreOf(x, y, gridPx)
                assertEquals("cell ($x,$y) x", cx, Grid.toCanvasX(x.toFloat(), gridPx), 0.001f)
                assertEquals("cell ($x,$y) y", cy, Grid.toCanvasY(y.toFloat(), gridPx), 0.001f)
            }
        }
    }

    @Test fun `arena y is flipped, with y=0 at the bottom`() {
        assertEquals("cell 0's centre is near the BOTTOM", 643.5f, Grid.toCanvasY(0f, gridPx), 0f)
        assertEquals("cell 19's centre is near the top", 16.5f, Grid.toCanvasY(19f, gridPx), 0f)
        assertEquals("and -0.5 is the bottom edge itself", 660f, Grid.toCanvasY(-0.5f, gridPx), 0f)
    }

    @Test fun `arena x maps straight across with no flip`() {
        assertEquals(16.5f, Grid.toCanvasX(0f, gridPx), 0f)
        assertEquals(643.5f, Grid.toCanvasX(19f, gridPx), 0f)
        assertEquals("and -0.5 is the left edge itself", 0f, Grid.toCanvasX(-0.5f, gridPx), 0f)
    }

    @Test fun `pointAt is the inverse of the two conversions`() {
        val (x, y) = Grid.pointAt(
            Grid.toCanvasX(5.55f, gridPx),
            Grid.toCanvasY(6.55f, gridPx),
            gridPx,
        )
        assertEquals(5.55f, x, 0.001f)
        assertEquals(6.55f, y, 0.001f)
    }

    @Test fun `pointAt clamps a touch that lands off the grid`() {
        val (lowX, lowY) = Grid.pointAt(-40f, 900f, gridPx)
        assertEquals(0f, lowX, 0f)
        assertEquals(0f, lowY, 0f)
        val (highX, highY) = Grid.pointAt(900f, -40f, gridPx)
        assertEquals(19f, highX, 0f)
        assertEquals(19f, highY, 0f)
    }

    /**
     * A 3-cell robot centred on cell (1,1) covers cells 0..2 on both axes, so
     * its body is flush with the arena's bottom-left corner. That is the start
     * pose and [Arena.moveRobot]'s clamp floor.
     */
    @Test fun `a corner-parked robot's body lands on the arena corner`() {
        val half = Config.ROBOT_SIZE_CELLS / 2f
        assertEquals("its left edge is the arena's", 0f, Grid.toCanvasX(1f - half, gridPx), 0f)
        assertEquals("its bottom edge too", gridPx, Grid.toCanvasY(1f - half, gridPx), 0f)
    }
}
