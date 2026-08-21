package com.mdp.grp11.arena

import com.mdp.grp11.protocol.Face
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ArenaTest {

    private val empty = Arena()

    @Test fun `place assigns ids from one upward`() {
        val (a1, o1) = empty.place(Cell(10, 10))
        val (a2, o2) = a1.place(Cell(11, 11))
        assertEquals(1, o1!!.id)
        assertEquals(2, o2!!.id)
        assertEquals(2, a2.obstacles.size)
    }

    @Test fun `removed id returns to the pool and is reused`() {
        var a = empty
        repeat(3) { i -> a = a.place(Cell(10 + i, 10)).first }
        a = a.remove(2)
        val (a2, o) = a.place(Cell(15, 15))
        assertEquals(2, o!!.id)
        assertEquals(3, a2.obstacles.size)
    }

    @Test fun `place is refused when the pool is exhausted`() {
        var a = empty
        repeat(8) { i -> a = a.place(Cell(10, i + 5)).first }
        val (after, o) = a.place(Cell(19, 19))
        assertNull(o)
        assertEquals(8, after.obstacles.size)
    }

    @Test fun `place is refused inside the start zone`() {
        val (after, o) = empty.place(Cell(3, 3))
        assertNull(o)
        assertTrue(after.obstacles.isEmpty())
    }

    @Test fun `place is allowed just outside the start zone`() {
        assertNotNull(empty.place(Cell(4, 0)).second)
        assertNotNull(empty.place(Cell(0, 4)).second)
    }

    @Test fun `place is refused on an occupied cell`() {
        val a = empty.place(Cell(10, 10)).first
        assertNull(a.place(Cell(10, 10)).second)
    }

    @Test fun `move refuses an occupied cell but allows a no-op onto itself`() {
        var a = empty.place(Cell(10, 10)).first
        a = a.place(Cell(11, 11)).first
        assertEquals(Cell(10, 10), a.move(1, Cell(11, 11)).obstacle(1)!!.cell)
        assertEquals(Cell(10, 10), a.move(1, Cell(10, 10)).obstacle(1)!!.cell)
        assertEquals(Cell(12, 12), a.move(1, Cell(12, 12)).obstacle(1)!!.cell)
    }

    @Test fun `move refuses the start zone`() {
        val a = empty.place(Cell(10, 10)).first
        assertEquals(Cell(10, 10), a.move(1, Cell(0, 0)).obstacle(1)!!.cell)
    }

    @Test fun `annotated face and reported target face are independent`() {
        var a = empty.place(Cell(10, 10)).first
        a = a.setFace(1, Face.N)
        a = a.applyTarget(1, 11, Face.E)
        val o = a.obstacle(1)!!
        assertEquals(Face.N, o.imageFace)
        assertEquals(Face.E, o.target!!.face)
        assertEquals(11, o.target!!.id)
    }

    @Test fun `applyTarget accepts an id outside the image pool`() {
        val a = empty.place(Cell(10, 10)).first.applyTarget(1, 4, null)
        assertEquals(4, a.obstacle(1)!!.target!!.id)
    }

    @Test fun `applyTarget for an unknown obstacle is ignored`() {
        val a = empty.place(Cell(10, 10)).first
        assertEquals(a, a.applyTarget(7, 11, null))
    }

    @Test fun `applyPose rejects out of range coordinates`() {
        val a = empty.applyPose(3, 4, Face.E)
        assertEquals(RobotPose(Cell(3, 4), Face.E), a.robot)
        assertEquals(a, a.applyPose(20, 4, Face.N))
        assertEquals(a, a.applyPose(-1, 4, Face.N))
    }
}
