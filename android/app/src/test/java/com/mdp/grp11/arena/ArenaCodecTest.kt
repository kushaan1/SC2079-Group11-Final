package com.mdp.grp11.arena

import com.mdp.grp11.protocol.Face
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.assertNull
import org.junit.Test

class ArenaCodecTest {

    @Test fun `empty arena round-trips`() {
        val a = Arena()
        assertEquals(a, decodeArena(encodeArena(a)))
    }

    @Test fun `obstacles and robot round-trip`() {
        var a = Arena().place(Cell(4, 13)).first
        a = a.place(Cell(9, 7)).first
        a = a.applyPose(1f, 1f, Face.N.degrees)
        assertEquals(a, decodeArena(encodeArena(a)))
    }

    /**
     * Files written before the robot was always present carry no `R` line.
     * Falling back to the start pose keeps them loadable - returning null
     * would make an old save look corrupt, and the operator would lose a
     * layout that is perfectly readable.
     */
    @Test fun `a layout saved without a robot line loads at the start pose`() {
        val back = decodeArena(
            """
            V1
            O 1 5 5 - - -
            """.trimIndent()
        )!!
        assertEquals(START_POSE, back.robot)
        assertEquals(1, back.obstacles.size)
    }

    @Test fun `a fractional pose and an arbitrary heading round-trip`() {
        val a = Arena().moveRobot(5.55f, 6.55f).turnRobot(20f)
        assertEquals(a, decodeArena(encodeArena(a)))
    }

    /**
     * The old integers-and-a-letter form, exactly as files written before the
     * pose went continuous carry it. Losing these would lose saved layouts.
     */
    @Test fun `a legacy R line still loads`() {
        val back = decodeArena(
            """
            V1
            R 1 1 N
            O 1 5 5 - - -
            """.trimIndent()
        )!!
        assertEquals(RobotPose(1f, 1f, 0f), back.robot)
    }

    @Test fun `annotated face and reported target survive independently`() {
        var a = Arena().place(Cell(9, 7)).first
        a = a.setFace(1, Face.N)
        a = a.applyTarget(1, 11, Face.E)
        val back = decodeArena(encodeArena(a))!!
        val o = back.obstacle(1)!!
        assertEquals(Face.N, o.imageFace)
        assertEquals(11, o.target!!.id)
        assertEquals(Face.E, o.target!!.face)
    }

    @Test fun `a target with no face round-trips`() {
        var a = Arena().place(Cell(5, 5)).first
        a = a.applyTarget(1, 4, null)
        val back = decodeArena(encodeArena(a))!!
        assertEquals(4, back.obstacle(1)!!.target!!.id)
        assertNull(back.obstacle(1)!!.target!!.face)
    }

    @Test fun `ids are preserved rather than reallocated`() {
        var a = Arena().place(Cell(5, 5)).first
        a = a.place(Cell(6, 6)).first
        a = a.place(Cell(7, 7)).first
        a = a.remove(2)
        val back = decodeArena(encodeArena(a))!!
        assertEquals(listOf(1, 3), back.obstacles.map { it.id }.sorted())
    }

    @Test fun `malformed input decodes to null rather than throwing`() {
        val junk = listOf(
            "", "   ", "V2\n", "nonsense",
            "V1\nO 1 4\n", "V1\nO x y z - - -\n", "V1\nR 1 1\n", "V1\nR 1 1 Q\n",
        )
        junk.forEach { assertNull("expected null for '$it'", decodeArena(it)) }
    }

    @Test fun `a duplicate obstacle id decodes to null`() {
        val text = "V1\nO 1 4 13 - - -\nO 1 9 7 - - -\n"
        assertNull(decodeArena(text))
    }

    @Test fun `an obstacle id outside the allocation pool decodes to null`() {
        assertNull(decodeArena("V1\nO 0 4 13 - - -\n"))
        assertNull(decodeArena("V1\nO 9 4 13 - - -\n"))
    }
}
