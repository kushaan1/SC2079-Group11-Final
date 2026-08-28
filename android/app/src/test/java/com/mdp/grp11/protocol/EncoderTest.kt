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
}
