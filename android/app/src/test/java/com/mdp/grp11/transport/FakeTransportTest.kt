package com.mdp.grp11.transport

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class FakeTransportTest {

    private val device = DeviceInfo("AMD-TOOL", "3C:5A:B4:11:88:F2")

    @Test fun `records what the app sent`() = runTest {
        val t = FakeTransport()
        t.connect(ConnectTarget.Client(device))
        t.send("ADD,B1,(10,6)")
        t.send("SUB,B1")
        assertEquals(listOf("ADD,B1,(10,6)", "SUB,B1"), t.sent)
    }

    @Test fun `delivers a line to collectors`() = runTest {
        val t = FakeTransport()
        t.connect(ConnectTarget.Client(device))
        val received = mutableListOf<String>()
        val job = launch { t.incoming.collect { received += it } }
        runCurrent() // let the collector subscribe before we deliver (no-replay SharedFlow)
        t.deliver("ROBOT,1,1,N")
        runCurrent() // let the resumed collector actually run before we cancel it
        job.cancel()
        assertEquals(listOf("ROBOT,1,1,N"), received)
    }

    @Test fun `connect can be made to fail`() = runTest {
        val t = FakeTransport()
        t.failNextConnect = true
        assertTrue(t.connect(ConnectTarget.Client(device)).isFailure)
        assertTrue(t.connect(ConnectTarget.Client(device)).isSuccess)
    }

    @Test fun `send fails once the link is dropped`() = runTest {
        val t = FakeTransport()
        t.connect(ConnectTarget.Client(device))
        t.dropLink()
        assertTrue(t.send("f").isFailure)
    }

    @Test fun `connect suspends until the gate is completed`() = runTest {
        val t = FakeTransport()
        val gate = CompletableDeferred<Unit>()
        t.connectGate = gate

        var resolved = false
        val job = launch {
            t.connect(ConnectTarget.Client(device))
            resolved = true
        }
        runCurrent() // let connect() run up to and suspend on the gate
        assertFalse(resolved)

        gate.complete(Unit)
        job.join()
        assertTrue(resolved)
    }

    @Test fun `a null gate is a no-op, exactly like before this property existed`() = runTest {
        val t = FakeTransport()
        // connectGate defaults to null - connect() must still resolve with
        // no suspension at all, unaffected by this property's existence.
        assertTrue(t.connect(ConnectTarget.Client(device)).isSuccess)
    }
}
