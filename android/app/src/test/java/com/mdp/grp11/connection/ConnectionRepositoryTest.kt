package com.mdp.grp11.connection

import com.mdp.grp11.config.Config
import com.mdp.grp11.protocol.Face
import com.mdp.grp11.protocol.Inbound
import com.mdp.grp11.protocol.Outbound
import com.mdp.grp11.transport.ConnectTarget
import com.mdp.grp11.transport.DeviceInfo
import com.mdp.grp11.transport.FakeTransport
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class ConnectionRepositoryTest {

    private val device = DeviceInfo("AMD-TOOL", "3C:5A:B4:11:88:F2")

    @Test fun `connect moves Idle to Connected`() = runTest {
        val fake = FakeTransport()
        val repo = ConnectionRepository(fake, TestScope(testScheduler))
        assertTrue(repo.state.value is ConnectionState.Idle)
        repo.connect(ConnectTarget.Client(device))
        assertEquals(ConnectionState.Connected(device), repo.state.value)
    }

    @Test fun `a malformed line does not stop later messages arriving`() = runTest {
        val fake = FakeTransport()
        val repo = ConnectionRepository(fake, TestScope(testScheduler))
        repo.connect(ConnectTarget.Client(device))

        val got = mutableListOf<Inbound>()
        val job = launch { repo.inbound.collect { got += it } }
        runCurrent() // let the internal reader and this collector subscribe before delivering

        fake.deliver("TARGET,B2")        // truncated
        fake.deliver("ROBOT,3,4,E")      // must still arrive
        runCurrent() // let the queued resumptions actually forward both lines
        job.cancel()

        assertTrue(got[0] is Inbound.Unknown)
        assertEquals(Inbound.Pose(3f, 4f, 90f), got[1])
    }

    @Test fun `send records an outbound traffic line`() = runTest {
        val fake = FakeTransport()
        val repo = ConnectionRepository(fake, TestScope(testScheduler))
        repo.connect(ConnectTarget.Client(device))

        val seen = mutableListOf<TrafficLine>()
        val job = launch { repo.traffic.collect { seen += it } }
        runCurrent() // let this collector subscribe before send emits
        repo.send(Outbound.RemoveObstacle(3))
        runCurrent() // let the queued resumption forward the traffic line
        job.cancel()

        assertEquals(TrafficLine(outbound = true, text = "SUB,B3", delivered = true), seen.last())
        assertEquals(listOf("SUB,B3"), fake.sent)
    }

    @Test fun `send while disconnected is dropped and marked undelivered`() = runTest {
        val fake = FakeTransport()
        val repo = ConnectionRepository(fake, TestScope(testScheduler))
        repo.connect(ConnectTarget.Client(device))
        fake.dropLink()

        val seen = mutableListOf<TrafficLine>()
        val job = launch { repo.traffic.collect { seen += it } }
        runCurrent() // let this collector subscribe before send emits
        val ok = repo.send(Outbound.Move("f"))
        runCurrent() // let the queued resumption forward the traffic line
        job.cancel()

        assertFalse(ok)
        assertFalse(seen.last().delivered)
        assertFalse(fake.sent.contains("f"))
    }

    /**
     * A failed manual connect deliberately does NOT resume automatic retrying -
     * auto-retrying after the operator's explicit attempt failed masks a real
     * fault (wrong device, radio off, peer not listening) instead of showing
     * it. The obligation that creates is a visible RETRY button, which the UI
     * only renders in `Failed`.
     *
     * Arena editing is deliberately not gated on the link - obstacles are laid
     * out before connecting - so any tap on the canvas while the operator
     * stares at a FAILED bar calls send(). `lastTarget` is assigned BEFORE
     * transport.connect(), so it survives the failure and beginReconnect()
     * would otherwise find everything it needs to start looping, flipping the
     * bar to RECONNECTING and taking the operator's only way forward with it.
     */
    @Test fun `a send failure after a failed connect does not start an automatic reconnect`() =
        runTest {
            val fake = FakeTransport()
            val repo = ConnectionRepository(fake, TestScope(testScheduler))

            fake.failNextConnect = true
            repo.connect(ConnectTarget.Client(device))
            runCurrent()
            assertTrue(
                "precondition: a failed connect settles in Failed",
                repo.state.value is ConnectionState.Failed,
            )

            // The arena tap. It cannot succeed - there is no link - and its
            // failure is what reaches beginReconnect().
            val ok = repo.send(Outbound.AddObstacle(1, 4, 5))
            runCurrent()
            assertFalse("precondition: the send genuinely failed", ok)

            // Bounded, never advanceUntilIdle: if the guard were absent the
            // retry loop would never finish and this test would hang instead
            // of failing.
            advanceTimeBy(Config.BACKOFF_MS.first() * 2)
            runCurrent()

            assertTrue(
                "a failed connect must stay Failed so RETRY stays on screen",
                repo.state.value is ConnectionState.Failed,
            )
        }

    @Test fun `disconnect returns to Idle`() = runTest {
        val fake = FakeTransport()
        val repo = ConnectionRepository(fake, TestScope(testScheduler))
        repo.connect(ConnectTarget.Client(device))
        repo.disconnect()
        assertTrue(repo.state.value is ConnectionState.Idle)
    }

    @Test fun `a peer drop while idle enters Reconnecting`() = runTest {
        val fake = FakeTransport()
        val repo = ConnectionRepository(fake, TestScope(testScheduler))
        repo.connect(ConnectTarget.Client(device))

        // No send() call - nobody is pressing buttons. The link just dies.
        fake.dropLink()
        runCurrent() // let the connection watcher observe the drop and start reconnecting

        assertTrue(repo.state.value is ConnectionState.Reconnecting)
    }

    @Test fun `disconnect cancels an in-flight reconnect`() = runTest {
        val fake = FakeTransport()
        val repo = ConnectionRepository(fake, TestScope(testScheduler))
        repo.connect(ConnectTarget.Client(device))

        fake.dropLink()
        runCurrent() // let the watcher observe the drop and start reconnecting
        assertTrue(repo.state.value is ConnectionState.Reconnecting)

        repo.disconnect()
        assertTrue(repo.state.value is ConnectionState.Idle)

        // Drain every backoff delay in virtual time. If the reconnect loop were
        // still alive it would succeed here (the fake reconnects by default) and
        // flip back to Connected - resurrecting a link the user closed on purpose.
        advanceUntilIdle()
        assertTrue(repo.state.value is ConnectionState.Idle)
    }

    @Test fun `a fresh connect while reconnecting cancels the reconnect and is not overwritten`() = runTest {
        val fake = FakeTransport()
        val repo = ConnectionRepository(fake, TestScope(testScheduler))
        val other = DeviceInfo("OTHER-DEVICE", "AA:BB:CC:DD:EE:FF")

        repo.connect(ConnectTarget.Client(device))
        fake.dropLink()
        runCurrent() // let the watcher observe the drop and start reconnecting
        assertTrue(repo.state.value is ConnectionState.Reconnecting)

        // Operator gets impatient and taps Connect again while the reconnect
        // loop is still parked in its backoff delay() - a deliberate action
        // must win over an automatic retry.
        repo.connect(ConnectTarget.Client(other))
        assertEquals(ConnectionState.Connected(other), repo.state.value)

        // Drain every backoff delay in virtual time. If the reconnect loop
        // were still alive, it would call transport.connect() again with the
        // ORIGINAL target and (the fake reconnects by default) overwrite the
        // fresh Connected(other) with a stale Connected(device).
        advanceUntilIdle()
        assertEquals(ConnectionState.Connected(other), repo.state.value)
    }

    @Test fun `a superseded reconnect loop never resurrects itself`() = runTest {
        val fake = FakeTransport()
        val repo = ConnectionRepository(fake, TestScope(testScheduler))
        val other = DeviceInfo("OTHER-DEVICE", "AA:BB:CC:DD:EE:FF")

        repo.connect(ConnectTarget.Client(device))
        fake.dropLink()
        runCurrent() // let the watcher observe the drop and start reconnecting
        assertTrue(repo.state.value is ConnectionState.Reconnecting)

        repo.connect(ConnectTarget.Client(other))
        assertEquals(ConnectionState.Connected(other), repo.state.value)

        // Record every state transition from here on, not just the value at
        // the end - a resurrected loop would publish Reconnecting and then a
        // stale Connected(device) partway through the drain even if, by
        // coincidence, a later iteration happened to settle back on
        // something that looked fine by the very end.
        val seen = mutableListOf<ConnectionState>()
        val job = launch { repo.state.collect { seen += it } }
        runCurrent() // let this collector subscribe and record the current Connected(other)

        advanceUntilIdle()
        job.cancel()

        assertEquals(listOf(ConnectionState.Connected(other)), seen)
    }

    @Test fun `send failing during an in-flight connect does not start a competing reconnect`() = runTest {
        val fake = FakeTransport()
        val repo = ConnectionRepository(fake, TestScope(testScheduler))

        // Record every state transition from the very start - a competing
        // reconnect loop targets the SAME device this connect() call does,
        // so it can converge on the identical *final* value by coincidence
        // even while it fired; only the full transition sequence tells them
        // apart (the same reasoning as `a superseded reconnect loop never
        // resurrects itself` above, applied to this scenario).
        val seen = mutableListOf<ConnectionState>()
        val job = launch { repo.state.collect { seen += it } }
        runCurrent() // let this collector subscribe and record the initial Idle

        // Park connect() itself mid-flight, genuinely suspended inside
        // transport.connect() - the way the real transport can for seconds
        // inside a blocking socket call.
        val gate = CompletableDeferred<Unit>()
        fake.connectGate = gate
        launch { repo.connect(ConnectTarget.Client(device)) }
        runCurrent() // let connect() run up to and suspend on the gate

        // A movement button pressed while the UI still shows "Connecting…".
        // transport.send() must fail fast - there is no live socket yet -
        // it must not wait on the gate (send() never touches it).
        val ok = repo.send(Outbound.Move("f"))
        assertFalse(ok)
        runCurrent() // let anything send()'s failure might have queued actually run

        // Let the parked connect() finally succeed, and drain everything a
        // competing loop would have used for its own backoff/connect cycle.
        gate.complete(Unit)
        advanceUntilIdle()
        job.cancel()

        // The only transitions allowed: Idle (initial) -> Connecting ->
        // Connected. A competing reconnect loop would insert a Reconnecting
        // entry somewhere in this list even if, by coincidence, it also
        // eventually lands on the same Connected(device) - and on the real
        // transport it would additionally have torn the just-established
        // socket back down via its own teardown() call, which this
        // state-only assertion can't observe directly but which the
        // complete absence of any Reconnecting transition rules out here.
        assertEquals(
            listOf(
                ConnectionState.Idle,
                ConnectionState.Connecting(device),
                ConnectionState.Connected(device),
            ),
            seen,
        )
    }

    // --- Overlapping connects -------------------------------------------------
    //
    // The real transport can sit in a blocking socket connect() for ~12 s.
    // That is long enough that an operator at assessment WILL tap again, so
    // two overlapping connect() calls - tapping A twice, or A then B - are an
    // ordinary occurrence rather than an exotic one. Each of the three tests
    // below parks both attempts genuinely inside transport.connect() using a
    // gate of its own, so the order they resolve in is the test's to choose,
    // and lets the SUPERSEDED one resolve LAST: that is the ordering in which
    // a stale attempt can damage the live session.

    @Test fun `a superseded connect that fails does not overwrite the winner's Connected`() = runTest {
        val fake = FakeTransport()
        val repo = ConnectionRepository(fake, TestScope(testScheduler))
        val other = DeviceInfo("OTHER-DEVICE", "AA:BB:CC:DD:EE:FF")

        val seen = mutableListOf<ConnectionState>()
        val job = launch { repo.state.collect { seen += it } }
        runCurrent() // let this collector subscribe and record the initial Idle

        val firstGate = CompletableDeferred<Unit>()
        fake.connectGate = firstGate
        launch { repo.connect(ConnectTarget.Client(device)) }
        runCurrent() // let the first attempt run up to and suspend on its gate

        // The operator taps again, on a different device, while the first
        // attempt is still parked.
        val secondGate = CompletableDeferred<Unit>()
        fake.connectGate = secondGate
        launch { repo.connect(ConnectTarget.Client(other)) }
        runCurrent() // let the second attempt run up to and suspend on its own gate

        // The newer attempt wins and publishes a live session.
        secondGate.complete(Unit)
        runCurrent()
        assertEquals(ConnectionState.Connected(other), repo.state.value)

        // Only now does the superseded attempt give up. Two attempts racing
        // the same Bluetooth adapter is exactly when that happens, and the
        // transport reports it as Result.failure - NOT a CancellationException
        // - so nothing but a supersession check stops its onFailure branch
        // writing Failed over a link that is actually up and passing traffic.
        fake.failNextConnect = true
        firstGate.complete(Unit)
        advanceUntilIdle()
        job.cancel()

        assertEquals(ConnectionState.Connected(other), repo.state.value)
        assertEquals(
            listOf(
                ConnectionState.Idle,
                ConnectionState.Connecting(device),
                ConnectionState.Connecting(other),
                ConnectionState.Connected(other),
            ),
            seen,
        )
    }

    @Test fun `a superseded connect that succeeds does not publish a link to the wrong device`() = runTest {
        val fake = FakeTransport()
        val repo = ConnectionRepository(fake, TestScope(testScheduler))
        val other = DeviceInfo("OTHER-DEVICE", "AA:BB:CC:DD:EE:FF")

        val seen = mutableListOf<ConnectionState>()
        val job = launch { repo.state.collect { seen += it } }
        runCurrent() // let this collector subscribe and record the initial Idle

        val firstGate = CompletableDeferred<Unit>()
        fake.connectGate = firstGate
        launch { repo.connect(ConnectTarget.Client(device)) }
        runCurrent() // let the first attempt run up to and suspend on its gate

        val secondGate = CompletableDeferred<Unit>()
        fake.connectGate = secondGate
        launch { repo.connect(ConnectTarget.Client(other)) }
        runCurrent() // let the second attempt run up to and suspend on its own gate

        secondGate.complete(Unit)
        runCurrent()
        assertEquals(ConnectionState.Connected(other), repo.state.value)

        // The mirror of the test above: the superseded attempt SUCCEEDS, late.
        // Publishing its result would name `device` as the connected peer
        // while the live socket goes to `other` - the UI would then label,
        // and the operator would trust, the wrong robot.
        firstGate.complete(Unit)
        advanceUntilIdle()
        job.cancel()

        assertEquals(ConnectionState.Connected(other), repo.state.value)
        assertEquals(
            listOf(
                ConnectionState.Idle,
                ConnectionState.Connecting(device),
                ConnectionState.Connecting(other),
                ConnectionState.Connected(other),
            ),
            seen,
        )
    }

    @Test fun `send failing between two overlapping connects does not start a reconnect`() = runTest {
        val fake = FakeTransport()
        val repo = ConnectionRepository(fake, TestScope(testScheduler))
        val other = DeviceInfo("OTHER-DEVICE", "AA:BB:CC:DD:EE:FF")

        val seen = mutableListOf<ConnectionState>()
        val job = launch { repo.state.collect { seen += it } }
        runCurrent() // let this collector subscribe and record the initial Idle

        val firstGate = CompletableDeferred<Unit>()
        fake.connectGate = firstGate
        launch { repo.connect(ConnectTarget.Client(device)) }
        runCurrent() // let the first attempt run up to and suspend on its gate

        val secondGate = CompletableDeferred<Unit>()
        fake.connectGate = secondGate
        launch { repo.connect(ConnectTarget.Client(other)) }
        runCurrent() // let the second attempt run up to and suspend on its own gate

        // Here the FIRST attempt resolves first, and fails. A single boolean
        // in-progress flag is cleared by this resolution even though a
        // connect is still genuinely in flight - which is the whole defect.
        fake.failNextConnect = true
        firstGate.complete(Unit)
        runCurrent()

        // A movement button pressed in that window. There is no live socket
        // yet, so this must fail fast rather than wait on the second attempt.
        val ok = repo.send(Outbound.Move("f"))
        assertFalse(ok)
        runCurrent() // let anything send()'s failure might have queued actually run

        // Failing fast is correct; what must not follow is a reconnect loop
        // started underneath the attempt that is still running. One backoff
        // later that loop calls transport.connect() again, whose teardown()
        // closes the socket the second attempt had just established, and the
        // UI cycles Connecting -> Reconnecting -> ... without ever settling.
        secondGate.complete(Unit)
        advanceUntilIdle()
        job.cancel()

        assertEquals(
            listOf(
                ConnectionState.Idle,
                ConnectionState.Connecting(device),
                ConnectionState.Connecting(other),
                ConnectionState.Connected(other),
            ),
            seen,
        )
    }

    @Test fun `a drop while a superseded connect is parked still starts a reconnect`() = runTest {
        val fake = FakeTransport()
        val repo = ConnectionRepository(fake, TestScope(testScheduler))
        val other = DeviceInfo("OTHER-DEVICE", "AA:BB:CC:DD:EE:FF")

        val firstGate = CompletableDeferred<Unit>()
        fake.connectGate = firstGate
        launch { repo.connect(ConnectTarget.Client(device)) }
        runCurrent() // let the first attempt run up to and suspend on its gate

        val secondGate = CompletableDeferred<Unit>()
        fake.connectGate = secondGate
        launch { repo.connect(ConnectTarget.Client(other)) }
        runCurrent() // let the second attempt run up to and suspend on its own gate

        // The newer attempt wins and the link comes up.
        secondGate.complete(Unit)
        runCurrent()
        assertEquals(ConnectionState.Connected(other), repo.state.value)

        // The peer now vanishes while the superseded attempt is STILL parked -
        // a window of up to ~12 s on the real transport. watchConnection sees
        // the drop and calls beginReconnect(), which correctly returns early
        // because a connect is still in flight. This much is the setup, not
        // the bug.
        fake.dropLink()
        runCurrent()
        assertTrue(
            "the in-flight guard is expected to swallow the drop at this point",
            repo.state.value is ConnectionState.Connected,
        )

        // Now the superseded attempt gives up. `transport.connected` is a
        // StateFlow, so that `false` is never re-delivered and nothing else
        // will ever raise it again. This attempt is the last code with a
        // chance to notice, so it must re-examine the link before walking
        // away. Self-healing "on the next send()" is not good enough: during
        // an exploration run the robot drives itself and the operator sends
        // nothing for minutes, so the app would sit showing Connected on a
        // dead link for the whole scored run (C.8).
        fake.failNextConnect = true
        firstGate.complete(Unit)
        runCurrent()

        assertTrue(
            "a dead link must not be left showing Connected",
            repo.state.value is ConnectionState.Reconnecting,
        )
    }

    @Test fun `a connect parked inside the transport publishes nothing after disconnect`() = runTest {
        val fake = FakeTransport()
        val repo = ConnectionRepository(fake, TestScope(testScheduler))

        // Park a deliberate connect() genuinely inside transport.connect().
        val gate = CompletableDeferred<Unit>()
        fake.connectGate = gate
        launch { repo.connect(ConnectTarget.Client(device)) }
        runCurrent() // let connect() run up to and suspend on the gate

        // The operator gives up waiting and closes the link instead. Same
        // supersession shape as two overlapping connects, reached through
        // disconnect(): on the real transport's Listen role this is not
        // hypothetical - disconnect() closes the server socket, the blocked
        // accept() throws, and the transport reports that as Result.failure,
        // so the parked attempt would write Failed over the Idle the operator
        // just asked for and the app would claim a fault it does not have.
        repo.disconnect()
        assertTrue(repo.state.value is ConnectionState.Idle)

        val seen = mutableListOf<ConnectionState>()
        val job = launch { repo.state.collect { seen += it } }
        runCurrent() // let this collector subscribe and record the current Idle

        gate.complete(Unit)
        advanceUntilIdle()
        job.cancel()

        assertEquals(listOf(ConnectionState.Idle), seen)
    }

    @Test fun `a reconnect cancelled while parked inside transport connect publishes no state`() = runTest {
        val fake = FakeTransport()
        val repo = ConnectionRepository(fake, TestScope(testScheduler))

        repo.connect(ConnectTarget.Client(device))
        fake.dropLink()
        runCurrent() // let the watcher observe the drop and start reconnecting
        assertTrue(repo.state.value is ConnectionState.Reconnecting)

        // Park the reconnect loop genuinely INSIDE transport.connect() -
        // not just its backoff delay() like every other reconnect test in
        // this file - the way the real transport can for up to ~12s inside
        // a blocking socket call.
        val gate = CompletableDeferred<Unit>()
        fake.connectGate = gate
        advanceTimeBy(Config.BACKOFF_MS[0])
        runCurrent() // let the loop's delay() elapse and reach transport.connect(), which now suspends on the gate

        // A deliberate disconnect while the loop is genuinely suspended
        // inside transport.connect() - not merely inside its own backoff
        // delay(), which every other reconnect-cancellation test in this
        // file exercises instead.
        repo.disconnect()
        assertTrue(repo.state.value is ConnectionState.Idle)

        val seen = mutableListOf<ConnectionState>()
        val job = launch { repo.state.collect { seen += it } }
        runCurrent() // let this collector subscribe and record the current Idle

        // Only now let the parked connect() actually resolve.
        gate.complete(Unit)
        advanceUntilIdle()
        job.cancel()

        assertEquals(listOf(ConnectionState.Idle), seen)
    }
}
