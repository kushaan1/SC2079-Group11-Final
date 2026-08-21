package com.mdp.grp11.ui

import com.mdp.grp11.arena.Arena
import com.mdp.grp11.arena.Cell
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class HitTestTest {

    private val gridPx = 660f     // 33px cells

    private fun arenaWith(vararg cells: Cell): Arena {
        var a = Arena()
        cells.forEach { a = a.place(it).first }
        return a
    }

    @Test fun `a tap on the block selects it`() {
        val a = arenaWith(Cell(10, 10))
        // cell (10,10) centre in canvas px: x = 10*33+16.5, y = (19-10)*33+16.5
        assertEquals(1, hitTest(a, 346.5f, 313.5f, gridPx)?.id)
    }

    @Test fun `a tap just outside the block still selects it within 48dp`() {
        val a = arenaWith(Cell(10, 10))
        // 24px away - inside the 27px radius, outside the 33px cell
        assertEquals(1, hitTest(a, 346.5f + 24f, 313.5f, gridPx)?.id)
    }

    @Test fun `a tap beyond the radius selects nothing`() {
        val a = arenaWith(Cell(10, 10))
        assertNull(hitTest(a, 346.5f + 40f, 313.5f, gridPx))
    }

    @Test fun `overlapping targets resolve to the nearest centre`() {
        val a = arenaWith(Cell(10, 10), Cell(11, 10))
        // Centres are 33px apart (346.5, 379.5) and the radius is 27.06px, so
        // both blocks are genuinely in range for 352.44 < x < 373.56.
        // x=355: 8.5px from block 1's centre, 24.5px from block 2's - 1 is nearer.
        assertEquals(1, hitTest(a, 355f, 313.5f, gridPx)?.id)
        // x=371: 8.5px from block 2's centre, 24.5px from block 1's - 2 is nearer.
        assertEquals(2, hitTest(a, 371f, 313.5f, gridPx)?.id)
    }

    @Test fun `empty arena hits nothing`() {
        assertNull(hitTest(Arena(), 300f, 300f, gridPx))
    }

    @Test fun `a tap just off the grid edge still grabs the adjacent block`() {
        // (0,0) is inside the start zone and place() refuses it, so use the
        // nearest left-edge cell outside it: x=0, y=4 (START_ZONE_CELLS=4
        // only blocks cells where BOTH x<4 and y<4).
        val a = arenaWith(Cell(0, 4))
        // centre is (16.5, 511.5): x = 0*33+16.5, y = (19-4)*33+16.5. This
        // point is 21.5px past the left edge of the grid, still inside the
        // 27.06px radius. hitTest has no bounds clamp, so a touch that lands
        // just off-grid can still claim the nearest edge block - asserted
        // here as the intended behaviour.
        assertEquals(1, hitTest(a, -5f, 511.5f, gridPx)?.id)
    }
}
