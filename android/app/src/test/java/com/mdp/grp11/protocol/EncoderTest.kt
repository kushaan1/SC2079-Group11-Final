package com.mdp.grp11.protocol

import org.junit.Assert.assertEquals
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
}
