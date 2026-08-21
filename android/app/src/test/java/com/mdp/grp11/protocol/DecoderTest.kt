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

    @Test fun `ROBOT parses coordinates and heading`() {
        assertEquals(Inbound.Pose(1, 1, Face.N), decode("ROBOT,1,1,N"))
        assertEquals(Inbound.Pose(7, 2, Face.W), decode("ROBOT, 7, 2, w"))
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
