package com.mdp.grp11.ui

import com.mdp.grp11.config.Config
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The pad's wiring, pinned.
 *
 * There is no Compose UI test harness here, so without this the six mappings
 * are verifiable only by reading them - and they can be renamed or reordered
 * without the pad visibly moving.
 *
 * This does NOT establish that `sl` is the right token for the button labelled
 * BL: which of `sl`/`sr` belongs there is a chassis convention still open with
 * the robot side (see [Config.MoveTokens]). If the answer comes back the other
 * way, this test changes with it.
 *
 * Asserted against LITERAL wire strings, deliberately - writing
 * `Config.moveTokens.reverseLeft` on both sides would pass whatever it said.
 */
class ControlPadTest {

    @Test fun `each pad position sends the wire token its label promises`() {
        val rows = padRows()

        assertEquals("the pad is two rows of three", listOf(3, 3), rows.map { it.size })

        assertEquals(
            "top row is the forward arcs: AMD's tl/f/tr slots",
            listOf("FL" to "tl", "F" to "f", "FR" to "tr"),
            rows[0].map { it.label to it.token },
        )
        assertEquals(
            "bottom row is the reverse arcs: AMD's sl/r/sr slots",
            listOf("BL" to "sl", "B" to "r", "BR" to "sr"),
            rows[1].map { it.label to it.token },
        )
    }

    /**
     * Every AMD movement slot is reachable and none is wired twice. A duplicate
     * would mean one slot is unreachable, and the operator would find out by
     * pressing a button and watching nothing happen.
     */
    @Test fun `the six movement slots are each used exactly once`() {
        val tokens = padRows().flatten().map { it.token }

        assertEquals("six buttons", 6, tokens.size)
        assertEquals("no token is wired to two buttons", tokens.size, tokens.toSet().size)
        assertEquals(
            "and they are exactly AMD's six movement slots",
            setOf("f", "r", "tl", "tr", "sl", "sr"),
            tokens.toSet(),
        )
    }

    /** STOP is not on the pad grid, and must never be one of the six. */
    @Test fun `stop is separate from the movement slots`() {
        assertEquals("s", Config.moveTokens.stop)
        assertEquals(
            "stop must not be reachable from a movement button",
            false,
            padRows().flatten().any { it.token == Config.moveTokens.stop },
        )
    }
}
