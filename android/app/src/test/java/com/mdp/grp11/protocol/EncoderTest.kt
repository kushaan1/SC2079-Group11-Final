package com.mdp.grp11.protocol

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class EncoderTest {

    @Test fun `add obstacle matches the briefing example`() {
        assertEquals("ADD,B1,(10,6)", encode(Outbound.AddObstacle(1, 10, 6)))
    }

    @Test fun `remove obstacle matches the briefing example`() {
        assertEquals("SUB,B1", encode(Outbound.RemoveObstacle(1)))
    }

    @Test fun `set face carries the coordinate as C7 requires`() {
        assertEquals("FACE,B3,(14,15),E", encode(Outbound.SetFace(3, 14, 15, Face.E)))
    }

    @Test fun `clearing a face sends NONE`() {
        assertEquals("FACE,B3,(14,15),NONE", encode(Outbound.SetFace(3, 14, 15, null)))
    }

    @Test fun `move sends the bare configured token`() {
        assertEquals("f", encode(Outbound.Move("f")))
    }

    /**
     * Bare coordinates, deliberately NOT parenthesised like ADD's: this
     * answers the inbound `ROBOT,x,y,h` line rather than joining the family of
     * obstacle commands. Decimal cells naming the robot's CENTRE, heading in
     * degrees.
     *
     * The literal string matters: Float.toString is locale-independent, where
     * String.format would emit "7,5" on a comma-decimal machine and split the
     * message into an extra field.
     */
    @Test fun `move robot mirrors the inbound ROBOT line`() {
        assertEquals("MOVEROBOT,7.5,2.25,20.0", encode(Outbound.MoveRobot(7.5f, 2.25f, 20f)))
    }

    /** The verb differs from inbound ROBOT so an RPi echo cannot be mistaken for a report. */
    @Test fun `move robot does not reuse the inbound verb`() {
        assertTrue(encode(Outbound.MoveRobot(0f, 0f, 0f)).startsWith("MOVEROBOT,"))
    }

    /**
     * The exact bytes matter here more than anywhere: this is the one message
     * the RPi parses as JSON rather than splitting on commas, so a stray space
     * or a quoted number is a different contract, not a cosmetic difference.
     */
    @Test fun `send arena is one JSON object with every obstacle`() {
        val msg = Outbound.SendArena(
            listOf(
                ObstacleEntry(1, 10, 6, Face.N),
                ObstacleEntry(3, 14, 15, Face.E),
            )
        )
        assertEquals(
            """{"obstacles":[{"id":1,"x":10,"y":6,"face":"N"},{"id":3,"x":14,"y":15,"face":"E"}]}""",
            encode(msg),
        )
    }

    @Test fun `send arena with nothing placed is an empty list, not an absent key`() {
        assertEquals("""{"obstacles":[]}""", encode(Outbound.SendArena(emptyList())))
    }

    @Test fun `begin image rec leads with the command, then the algorithm, then the robot, then the layout`() {
        val msg = Outbound.BeginImageRec(
            algorithm = "greedy",
            robot = StartPose(1f, 1f, 0f),
            obstacles = listOf(ObstacleEntry(1, 10, 6, Face.N), ObstacleEntry(2, 14, 15, Face.E)),
        )
        assertEquals(
            """{"command":"imageRec","algorithm":"greedy","robot":{"x":1.0,"y":1.0,"heading":0.0},"obstacles":[{"id":1,"x":10,"y":6,"face":"N"},{"id":2,"x":14,"y":15,"face":"E"}]}""",
            encode(msg),
        )
    }

    @Test fun `begin image rec on an empty arena still carries the command, algorithm and robot`() {
        assertEquals(
            """{"command":"imageRec","algorithm":"optimal","robot":{"x":1.0,"y":1.0,"heading":0.0},"obstacles":[]}""",
            encode(Outbound.BeginImageRec("optimal", StartPose(1f, 1f, 0f), emptyList())),
        )
    }

    @Test fun `the start pose is written the way MOVEROBOT writes it, decimals and all`() {
        val msg = Outbound.BeginImageRec("greedy", StartPose(7.5f, 2.25f, 20f), emptyList())
        assertTrue(encode(msg).contains(""""robot":{"x":7.5,"y":2.25,"heading":20.0}"""))
    }

    @Test fun `begin face search has no algorithm, just the command, the robot and the layout`() {
        val msg = Outbound.BeginFaceSearch(
            robot = StartPose(1f, 1f, 0f),
            obstacles = listOf(ObstacleEntry(1, 10, 6, Face.S)),
        )
        assertEquals(
            """{"command":"faceSearch","robot":{"x":1.0,"y":1.0,"heading":0.0},"obstacles":[{"id":1,"x":10,"y":6,"face":"S"}]}""",
            encode(msg),
        )
    }
}
