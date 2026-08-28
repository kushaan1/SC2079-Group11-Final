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

    @Test fun `applyPose rejects a centre outside the arena`() {
        val a = empty.applyPose(3f, 4f, Face.E.degrees)
        assertEquals(RobotPose(3f, 4f, 90f), a.robot)
        assertEquals(a, a.applyPose(19.5f, 4f, 0f))
        assertEquals(a, a.applyPose(-1f, 4f, 0f))
    }

    /**
     * A centre on the outermost cell is legal - that is a robot at the very
     * edge with half its body off the board. The footprint is deliberately not
     * checked: what the robot reports is shown as reported.
     */
    @Test fun `applyPose accepts an edge cell and does not check the footprint`() {
        assertEquals(RobotPose(0f, 19f, 0f), empty.applyPose(0f, 19f, 0f).robot)
    }

    /** A heading is periodic, so 450 IS 90 - not an error to reject. */
    @Test fun `applyPose normalises the heading`() {
        assertEquals(90f, empty.applyPose(5f, 5f, 450f).robot.headingDegrees, 0f)
        assertEquals(270f, empty.applyPose(5f, 5f, -90f).robot.headingDegrees, 0f)
    }

    /** The whole point of going continuous: no rounding to a cell. */
    @Test fun `applyPose keeps a fractional pose exactly`() {
        assertEquals(RobotPose(5.55f, 6.55f, 20f), empty.applyPose(5.55f, 6.55f, 20f).robot)
    }

    // --- The robot the OPERATOR moves

    /**
     * Cell (1,1): a 3-cell robot centred there covers cells 0..2 on both axes,
     * flush into the arena's bottom-left corner. Also [Arena.moveRobot]'s
     * clamp floor, which a test below relies on.
     */
    @Test fun `a fresh arena parks the robot in the corner facing north`() {
        assertEquals(START_POSE, empty.robot)
        assertEquals(1f, empty.robot.x, 0f)
        assertEquals(1f, empty.robot.y, 0f)
        assertEquals(Face.N.degrees, empty.robot.headingDegrees, 0f)
    }

    /**
     * The robot and an obstacle count in the SAME units. A robot reported at
     * cell (10,10) is centred on the very cell an obstacle at (10,10) occupies
     * - not half a cell off it. This is the property the whole coordinate
     * scheme exists to give, and it would fail silently by exactly 5cm.
     */
    @Test fun `a robot at a cell index sits on that same cell`() {
        val a = empty.place(Cell(10, 10)).first.applyPose(10f, 10f, 0f)
        assertEquals(Cell(10, 10), a.obstacle(1)!!.cell)
        assertEquals(10f, a.robot.x, 0f)
        assertEquals(10f, a.robot.y, 0f)
    }

    /**
     * The centre is held one cell in from the outermost cell, so a 3-cell
     * robot on a 20-cell board runs 1 to 18. Asserted at all four edges: an
     * off-by-one here draws the robot hanging off the arena.
     */
    @Test fun `moveRobot keeps the whole footprint on the board`() {
        assertEquals(18f, empty.moveRobot(25f, 5f).robot.x, 0f)
        assertEquals(1f, empty.moveRobot(-3f, 5f).robot.x, 0f)
        assertEquals(18f, empty.moveRobot(5f, 99f).robot.y, 0f)
        assertEquals(1f, empty.moveRobot(5f, 0f).robot.y, 0f)
    }

    /**
     * The asymmetry with [Arena.applyPose] is the point: a finger dragged past
     * the wall should stop against it, while a malformed wire message must be
     * visibly ignored rather than turned into a plausible-looking position.
     */
    @Test fun `moveRobot clamps exactly where applyPose refuses`() {
        assertEquals(18f, empty.moveRobot(25f, 25f).robot.x, 0f)
        assertEquals(empty.robot, empty.applyPose(25f, 25f, 0f).robot)
    }

    @Test fun `moveRobot keeps a fractional position`() {
        val dragged = empty.moveRobot(5.55f, 6.55f)
        assertEquals(5.55f, dragged.robot.x, 0f)
        assertEquals(6.55f, dragged.robot.y, 0f)
    }

    /**
     * Unlike [Arena.place], which validates. Obstacles are a layout being
     * authored; the robot's position is a fact being stated.
     */
    @Test fun `moveRobot does not mind an obstacle underneath`() {
        val a = empty.place(Cell(10, 10)).first
        assertEquals(10f, a.moveRobot(10f, 10f).robot.x, 0f)
    }

    @Test fun `moveRobot leaves the heading alone`() {
        val facing = empty.turnRobot(180f)
        assertEquals(180f, facing.moveRobot(9f, 9f).robot.headingDegrees, 0f)
    }

    @Test fun `moveRobot to where it already sits changes nothing`() {
        assertEquals(empty, empty.moveRobot(empty.robot.x, empty.robot.y))
    }

    /** The start pose IS the clamp floor, so a drag into the corner is a no-op. */
    @Test fun `the start pose sits exactly on the clamp floor`() {
        assertEquals(empty, empty.moveRobot(-5f, -5f))
    }

    @Test fun `turnRobot sets the heading, normalises it and never clears it`() {
        val a = empty.turnRobot(270f)
        assertEquals(270f, a.robot.headingDegrees, 0f)
        assertEquals("the centre must not move", empty.robot.x, a.robot.x, 0f)
        assertEquals("re-picking the active heading is a no-op", a, a.turnRobot(270f))
        assertEquals("and 630 is that same heading", a, a.turnRobot(630f))
    }
}
