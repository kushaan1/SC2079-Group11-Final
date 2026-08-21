package com.mdp.grp11.transport

import org.junit.Assert.assertEquals
import org.junit.Test

class LineFramerTest {

    private fun LineFramer.feed(s: String): List<String> {
        val b = s.toByteArray()
        return feed(b, b.size)
    }

    @Test fun `emits nothing until a newline arrives`() {
        val f = LineFramer()
        assertEquals(emptyList<String>(), f.feed("ROBOT,1,1"))
        assertEquals(listOf("ROBOT,1,1,N"), f.feed(",N\n"))
    }

    @Test fun `splits a chunk containing several messages`() {
        val f = LineFramer()
        assertEquals(listOf("A", "B", "C"), f.feed("A\nB\nC\n"))
    }

    @Test fun `reassembles a message delivered one character at a time`() {
        val f = LineFramer()
        val out = mutableListOf<String>()
        "TARGET,B2,11\n".forEach { ch -> out += f.feed(ch.toString()) }
        assertEquals(listOf("TARGET,B2,11"), out)
    }

    @Test fun `tolerates CRLF`() {
        val f = LineFramer()
        assertEquals(listOf("MSG,[Moving]"), f.feed("MSG,[Moving]\r\n"))
    }

    @Test fun `reset drops a half received line`() {
        val f = LineFramer()
        f.feed("ROBO")
        f.reset()
        assertEquals(listOf("T,1,1,N"), f.feed("T,1,1,N\n"))
    }

    // --- flushPending(): delivers a peer (the AMD debug tool) that never
    // --- terminates what it sends, without ever splitting a message that
    // --- legitimately arrives across two reads (the RPi can do this).

    @Test fun `a complete newline-terminated line emits immediately, unchanged, with nothing left to flush`() {
        val f = LineFramer()
        assertEquals(listOf("ROBOT,1,1,N"), f.feed("ROBOT,1,1,N\n"))
        assertEquals(null, f.flushPending())
    }

    @Test fun `a message split across two feeds emits once whole, and the flush does not also emit it`() {
        val f = LineFramer()
        assertEquals(emptyList<String>(), f.feed("TARGET,B2,"))
        assertEquals(listOf("TARGET,B2,11"), f.feed("11\n"))
        // The complete line was already delivered by feed() itself - the
        // flush must find nothing left over to (wrongly) emit a second time.
        assertEquals(null, f.flushPending())
    }

    @Test fun `an unterminated message is delivered by flushPending`() {
        val f = LineFramer()
        assertEquals(emptyList<String>(), f.feed("MSG,[hello]"))
        assertEquals("MSG,[hello]", f.flushPending())
        // Flushing drains the buffer - a second flush must find nothing left.
        assertEquals(null, f.flushPending())
    }

    @Test fun `reset discards a pending partial rather than flushing it`() {
        val f = LineFramer()
        f.feed("MSG,[hel")
        f.reset()
        assertEquals(null, f.flushPending())
    }
}
