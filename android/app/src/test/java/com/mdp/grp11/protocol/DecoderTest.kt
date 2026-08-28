package com.mdp.grp11.protocol

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class DecoderTest {

    @Test fun `MSG extracts the bracketed payload`() {
        assertEquals(Inbound.Status("Moving"), decode("MSG,[Moving]"))
        assertEquals(Inbound.Status("Scanning obstacle 2"), decode("MSG,[Scanning obstacle 2]"))
    }

    @Test fun `MSG without brackets falls back to the remainder`() {
        assertEquals(Inbound.Status("Ready"), decode("MSG,Ready"))
    }

    @Test fun `TARGET three arg form`() {
        assertEquals(Inbound.TargetFound(2, 11, null), decode("TARGET,B2,11"))
    }

    @Test fun `TARGET four arg form carries the face`() {
        assertEquals(Inbound.TargetFound(2, 11, Face.N), decode("TARGET,B2,11,N"))
    }

    @Test fun `TARGET accepts a bare obstacle number and spaces after commas`() {
        assertEquals(Inbound.TargetFound(2, 11, null), decode("TARGET, 2, 11"))
    }

    @Test fun `TARGET accepts an id outside the image pool`() {
        assertEquals(Inbound.TargetFound(2, 4, null), decode("TARGET,B2,4"))
    }

    @Test fun `ROBOT parses the legacy integers-and-a-letter form`() {
        assertEquals(Inbound.Pose(1f, 1f, 0f), decode("ROBOT,1,1,N"))
        assertEquals(Inbound.Pose(7f, 2f, 270f), decode("ROBOT, 7, 2, w"))
    }

    /**
     * The continuous form an arcing car actually produces. Both forms name the
     * footprint's CENTRE - the anchor is a property of the message, not of the
     * number format, or the same robot would draw in two places depending on
     * which form arrived.
     */
    @Test fun `ROBOT parses decimal cells and a heading in degrees`() {
        assertEquals(Inbound.Pose(5.55f, 6.55f, 20f), decode("ROBOT,5.55,6.55,20"))
    }

    /** Each field decides for itself, so a mixed line needs no special case. */
    @Test fun `ROBOT accepts a decimal position with a letter heading`() {
        assertEquals(Inbound.Pose(7.5f, 2f, 0f), decode("ROBOT,7.5,2,N"))
    }

    /** A heading is periodic. 450 is 90, and -90 is 270 - neither is an error. */
    @Test fun `ROBOT normalises the heading`() {
        assertEquals(Inbound.Pose(1f, 1f, 90f), decode("ROBOT,1,1,450"))
        assertEquals(Inbound.Pose(1f, 1f, 270f), decode("ROBOT,1,1,-90"))
    }

    /**
     * toFloatOrNull accepts "NaN" and "Infinity". Left through, they would
     * reach the renderer and draw nothing, which reads as a display bug rather
     * than as the malformed message it is.
     */
    @Test fun `ROBOT rejects non-finite numbers`() {
        assertTrue(decode("ROBOT,NaN,1,0") is Inbound.Unknown)
        assertTrue(decode("ROBOT,1,Infinity,0") is Inbound.Unknown)
        assertTrue(decode("ROBOT,1,1,NaN") is Inbound.Unknown)
    }

    @Test fun `ROBOT still rejects a heading that is neither letter nor number`() {
        assertTrue(decode("ROBOT,1,1,NE") is Inbound.Unknown)
    }

    @Test fun `verbs are case insensitive`() {
        assertEquals(Inbound.TargetFound(2, 11, null), decode("target,B2,11"))
    }

    @Test fun `unknown verb becomes Unknown and keeps the raw line`() {
        val r = decode("WAT,1,2")
        assertTrue(r is Inbound.Unknown)
        assertEquals("WAT,1,2", (r as Inbound.Unknown).raw)
    }

    @Test fun `malformed lines never throw`() {
        val junk = listOf(
            "", "   ", ",", "TARGET", "TARGET,", "TARGET,B2", "TARGET,B2,xx",
            "ROBOT,1", "ROBOT,1,1", "ROBOT,1,1,Q", "ROBOT,a,b,N", "MSG",
            "TARGET,B2,11,Q", " ",
        )
        junk.forEach { line ->
            val r = decode(line)          // must not throw
            assertTrue("expected Unknown for '$line' but got $r", r is Inbound.Unknown)
        }
    }
}
