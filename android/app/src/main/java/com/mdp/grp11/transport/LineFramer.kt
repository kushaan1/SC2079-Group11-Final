package com.mdp.grp11.transport

/**
 * RFCOMM is a byte stream, not a message stream: a read may return half a
 * message or several glued together. This accumulates until a newline.
 *
 * Not every peer newline-terminates what it sends (the AMD debug tool does
 * not), so a message with no terminator would otherwise sit in the buffer
 * forever and never be delivered. [flushPending] exists for exactly that
 * case. It must only be called by the transport after confirming no further
 * bytes have arrived for a short idle interval - [feed] always takes
 * priority over it, because more bytes arriving is proof a pending message
 * was not actually finished. That ordering is what lets a message that
 * legitimately spans two reads (the RPi can do this, which is the whole
 * reason this class buffers instead of emitting per read) reach [feed]
 * intact instead of being split by an idle flush that fired too eagerly.
 *
 * reset() MUST be called on disconnect. A half-line left in the buffer would
 * otherwise prepend to the first message after reconnect and corrupt it - a
 * bug that only manifests after a reconnect.
 *
 * Thread safety: all three methods lock on this instance. The transport drives
 * [feed] from its blocking read loop and [flushPending] from a separate
 * idle-timer coroutine, genuinely concurrently and for the life of a
 * connection. Every critical section is a few StringBuilder operations and
 * never a suspension point.
 */
class LineFramer {

    private val buffer = StringBuilder()

    fun feed(bytes: ByteArray, length: Int): List<String> = synchronized(this) {
        buffer.append(String(bytes, 0, length, Charsets.UTF_8))
        if (buffer.indexOf("\n") < 0) return@synchronized emptyList()

        val out = mutableListOf<String>()
        while (true) {
            val nl = buffer.indexOf("\n")
            if (nl < 0) break
            val line = buffer.substring(0, nl).removeSuffix("\r")
            buffer.delete(0, nl + 1)
            if (line.isNotEmpty()) out += line
        }
        out
    }

    /**
     * Emits whatever is currently buffered as a single line and clears the
     * buffer, or returns null if there is nothing pending (including when
     * all that was pending was blank/CRLF noise). See the class doc for the
     * timing contract callers must honour - this method itself has no
     * concept of "idle"; it only knows what is in the buffer right now.
     */
    fun flushPending(): String? = synchronized(this) {
        if (buffer.isEmpty()) return@synchronized null
        val line = buffer.toString().removeSuffix("\r")
        buffer.setLength(0)
        line.ifEmpty { null }
    }

    fun reset() = synchronized(this) {
        buffer.setLength(0)
    }
}
