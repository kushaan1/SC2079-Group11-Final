package com.mdp.grp11.ui

import com.mdp.grp11.arena.Arena
import com.mdp.grp11.arena.ArenaStore
import com.mdp.grp11.arena.Cell
import com.mdp.grp11.arena.Obstacle
import com.mdp.grp11.arena.RobotPose
import com.mdp.grp11.config.Config
import com.mdp.grp11.connection.ConnectionRepository
import com.mdp.grp11.protocol.Face
import com.mdp.grp11.session.RunKind
import com.mdp.grp11.session.RunTimer
import com.mdp.grp11.transport.ConnectTarget
import com.mdp.grp11.transport.DeviceInfo
import com.mdp.grp11.transport.FakeTransport
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class ArenaViewModelTest {

    private val device = DeviceInfo("AMD-TOOL", "3C:5A:B4:11:88:F2")

    /**
     * In-memory ArenaStore, isolated per test instance (no shared file, no
     * process-lifetime singleton, no Context, no Android stub jar involved at
     * all) - the seam arena/ArenaStore.kt exposes specifically so this
     * fake could exist. [failNext] makes the NEXT call throw once, so a test
     * can exercise a genuine failure deterministically, independent of
     * anything any other test in this class does.
     */
    private class FakeArenaStore : ArenaStore {
        private val stored = mutableMapOf<String, Arena>()
        var failNext = false

        private fun maybeFail() {
            if (failNext) {
                failNext = false
                throw IllegalStateException("fake: arenaStore call failed")
            }
        }

        override suspend fun save(name: String, arena: Arena) {
            maybeFail()
            stored[name] = arena
        }

        override suspend fun load(name: String): Arena? {
            maybeFail()
            return stored[name]
        }

        override suspend fun names(): List<String> {
            maybeFail()
            return stored.keys.sorted()
        }

        override suspend fun delete(name: String) {
            maybeFail()
            stored.remove(name)
        }
    }

    private suspend fun TestScope.connectedViewModel(
        fake: FakeTransport,
        arenaStore: ArenaStore = FakeArenaStore(),
        runTimer: RunTimer = RunTimer { testScheduler.currentTime },
    ): ArenaViewModel {
        val repo = ConnectionRepository(fake, TestScope(testScheduler))
        repo.connect(ConnectTarget.Client(device))
        val vm = ArenaViewModel(repo, TestScope(testScheduler), runTimer, arenaStore)
        runCurrent() // let the repo's reader and the vm's own collectors subscribe first
        return vm
    }

    // --- ADD is transmitted whenever positioning completes ------------------

    @Test fun `a tap-place transmits exactly one AddObstacle for the allocated id`() = runTest {
        val fake = FakeTransport()
        val vm = connectedViewModel(fake)

        vm.place(Cell(10, 6))
        runCurrent()

        assertEquals(listOf("ADD,B1,(10,6)"), fake.sent)
    }

    @Test fun `a drag of a tap-placed block transmits a second AddObstacle with its new cell`() = runTest {
        val fake = FakeTransport()
        val vm = connectedViewModel(fake)

        vm.place(Cell(10, 6))
        runCurrent()
        vm.dragTo(1, Cell(12, 8))
        vm.commit(1)
        runCurrent()

        // Two completed positionings, two ADDs - not a duplicate, the second
        // one carries the block's new cell.
        assertEquals(listOf("ADD,B1,(10,6)", "ADD,B1,(12,8)"), fake.sent)
    }

    @Test fun `committing an unmoved block sends nothing`() = runTest {
        val fake = FakeTransport()
        val vm = connectedViewModel(fake)

        vm.place(Cell(10, 6))
        vm.commit(1)
        runCurrent()
        val after = fake.sent.size

        vm.select(1)
        vm.commit(1)
        runCurrent()
        assertEquals("a bare select must not re-announce", after, fake.sent.size)
    }

    @Test fun `dragging out removes and sends SUB`() = runTest {
        val fake = FakeTransport()
        val vm = connectedViewModel(fake)

        vm.place(Cell(10, 6))
        vm.commit(1)
        vm.dropOutside(1)
        runCurrent()

        assertTrue(vm.arena.value.obstacles.isEmpty())
        assertTrue(fake.sent.contains("SUB,B1"))
    }

    @Test fun `select does not let a stale robot position get silently adopted as current`() = runTest {
        val fake = FakeTransport()
        val vm = connectedViewModel(fake)

        vm.place(Cell(10, 6))
        runCurrent()
        // A drag that moves the block LOCALLY but is then cancelled -
        // ArenaCanvas's onDragCancel calls neither commit nor dropOutside, so
        // the ViewModel never learns the gesture ended, and the robot is
        // never told about this move.
        vm.dragTo(1, Cell(15, 10))

        // The operator later taps the block to select it (opens the face
        // compass). This must not silently adopt the untransmitted local
        // cell as "the position the robot knows about".
        vm.select(1)

        // A later drag that ends at that same local cell must still tell the
        // robot, because its last CONFIRMED position is still (10,6) - not
        // (15,10), whatever select() saw locally in between.
        vm.dragTo(1, Cell(15, 10))
        vm.commit(1)
        runCurrent()

        assertEquals(listOf("ADD,B1,(10,6)", "ADD,B1,(15,10)"), fake.sent)
    }

    // --- C.7 face annotation --------------------------------------------------

    @Test fun `picking a face sends FACE with the coordinate`() = runTest {
        val fake = FakeTransport()
        val vm = connectedViewModel(fake)

        vm.place(Cell(14, 15))
        vm.select(1)
        vm.pickFace(Face.E)
        runCurrent()

        assertTrue(fake.sent.contains("FACE,B1,(14,15),E"))
    }

    @Test fun `picking the active face again clears it`() = runTest {
        val fake = FakeTransport()
        val vm = connectedViewModel(fake)

        vm.place(Cell(14, 15))
        vm.select(1)
        vm.pickFace(Face.E)
        vm.pickFace(Face.E)
        runCurrent()

        assertTrue(fake.sent.contains("FACE,B1,(14,15),NONE"))
    }

    // --- imageFace (C.7, outbound) vs target (C.9, inbound) must never conflate

    @Test fun `an inbound TARGET updates target without touching the operator-set imageFace`() = runTest {
        val fake = FakeTransport()
        val vm = connectedViewModel(fake)

        vm.place(Cell(10, 6))
        vm.select(1)
        vm.pickFace(Face.N)
        runCurrent()

        fake.deliver("TARGET,B1,17,S")
        runCurrent()

        val o = vm.arena.value.obstacle(1)!!
        assertEquals(Face.N, o.imageFace)
        assertEquals(17, o.target?.id)
        assertEquals(Face.S, o.target?.face)
    }

    // --- Other inbound-driven state (C.4 status, C.9 target line, robot pose)

    @Test fun `an inbound MSG updates statusText`() = runTest {
        val fake = FakeTransport()
        val vm = connectedViewModel(fake)

        fake.deliver("MSG,[Moving forward]")
        runCurrent()

        assertEquals("Moving forward", vm.statusText.value)
    }

    @Test fun `an inbound ROBOT pose updates the arena's robot`() = runTest {
        val fake = FakeTransport()
        val vm = connectedViewModel(fake)

        fake.deliver("ROBOT,3,4,E")
        runCurrent()

        assertEquals(RobotPose(Cell(3, 4), Face.E), vm.arena.value.robot)
    }

    @Test fun `targetLine formats the target id, label and obstacle`() = runTest {
        val fake = FakeTransport()
        val vm = connectedViewModel(fake)

        vm.place(Cell(10, 6))
        runCurrent()
        fake.deliver("TARGET,B1,20,N")
        runCurrent()

        assertEquals("Target 20 · letter A · at B1", vm.targetLine.value)
    }

    // --- C.1 raw traffic log ordering ------------------------------------------

    /**
     * BtLogPanel's KDoc documents `lines` as oldest-first and reverses
     * internally to render newest-at-bottom. The producer here previously
     * built newest-first (`listOf(line) + _traffic.value`), which inverted
     * that contract: the oldest retained line rendered at the bottom as if
     * it were current, while the newest scrolled off-screen.
     */
    @Test fun `traffic accumulates oldest-first, matching BtLogPanel's documented contract`() = runTest {
        val fake = FakeTransport()
        val vm = connectedViewModel(fake)

        fake.deliver("MSG,[first]")
        runCurrent()
        fake.deliver("MSG,[second]")
        runCurrent()
        fake.deliver("MSG,[third]")
        runCurrent()

        assertEquals(
            listOf("MSG,[first]", "MSG,[second]", "MSG,[third]"),
            vm.traffic.value.map { it.text },
        )
    }

    /**
     * The cap direction matters independently of ordering: `take` on a
     * newest-first list keeps the newest N, which is correct for THAT order
     * but wrong once the producer is fixed to build oldest-first - `take` on
     * an oldest-first list would keep the OLDEST TRAFFIC_LOG_CAP lines
     * forever, silently freezing the log. `takeLast` is the one that rolls
     * the window forward and keeps the newest lines, which is what a live
     * log needs.
     */
    @Test fun `traffic caps at TRAFFIC_LOG_CAP by dropping the OLDEST lines, not the newest`() = runTest {
        val fake = FakeTransport()
        val vm = connectedViewModel(fake)

        val total = Config.TRAFFIC_LOG_CAP + 5
        repeat(total) { i ->
            fake.deliver("MSG,[$i]")
            runCurrent()
        }

        val texts = vm.traffic.value.map { it.text }
        assertEquals(Config.TRAFFIC_LOG_CAP, texts.size)
        assertEquals("the oldest 5 lines (0..4) must be the ones dropped", "MSG,[5]", texts.first())
        assertEquals("MSG,[${total - 1}]", texts.last())
    }

    // --- Task-start commands and run timers -----------------------------------

    @Test fun `startRun starts the timer and sends the matching task token atomically`() = runTest {
        val fake = FakeTransport()
        val vm = connectedViewModel(fake)

        vm.startRun(RunKind.Exploration)
        runCurrent()

        assertEquals(RunKind.Exploration, vm.runTimes.value.running)
        assertEquals(listOf(Config.taskTokens.beginExploration), fake.sent)

        // startRun's tick coroutine re-schedules itself forever (while(true) {
        // delay(...) }); runTest drains the shared virtual-time scheduler at
        // the end of every test, so leaving it running here would hang the
        // whole suite. endRun() cancels it - every test that starts a run
        // must also end it before the test body returns.
        vm.endRun()
        runCurrent()
    }

    @Test fun `startRun for FastestCar sends the fastest token`() = runTest {
        val fake = FakeTransport()
        val vm = connectedViewModel(fake)

        vm.startRun(RunKind.FastestCar)
        runCurrent()

        assertEquals(listOf(Config.taskTokens.beginFastest), fake.sent)

        // See the note in the previous test - the tick coroutine must be
        // stopped before this test body returns, or runTest's end-of-test
        // drain of the shared scheduler never terminates.
        vm.endRun()
        runCurrent()
    }

    @Test fun `runTimes ticks every configured interval while a run is active`() = runTest {
        val fake = FakeTransport()
        val vm = connectedViewModel(fake)

        vm.startRun(RunKind.Exploration)
        runCurrent()
        assertEquals(0L, vm.runTimes.value.exploration)

        advanceTimeBy(Config.RUN_TIMER_TICK_MS)
        runCurrent()
        assertEquals(Config.RUN_TIMER_TICK_MS, vm.runTimes.value.exploration)

        advanceTimeBy(Config.RUN_TIMER_TICK_MS)
        runCurrent()
        assertEquals(Config.RUN_TIMER_TICK_MS * 2, vm.runTimes.value.exploration)

        // Stop the tick coroutine before the test ends - see the note above.
        vm.endRun()
        runCurrent()
    }

    /**
     * The scored attempt is almost never the first attempt. RunTimer.start()
     * on its own BANKS the previous elapsed time and counts up from it, and
     * nothing in the UI reaches RunTimer.reset(), so without the zeroing in
     * startRun a practice run would contaminate the reading for the rest of
     * the process - the only way back to zero being a force-stop.
     */
    @Test fun `a second run of the same kind starts from zero, not from the first run's time`() =
        runTest {
            val fake = FakeTransport()
            val vm = connectedViewModel(fake)

            vm.startRun(RunKind.Exploration)
            runCurrent()
            advanceTimeBy(Config.RUN_TIMER_TICK_MS * 8)
            runCurrent()
            vm.endRun()
            runCurrent()
            val firstRun = vm.runTimes.value.exploration
            assertTrue("precondition: the first run put time on the clock", firstRun > 0L)

            vm.startRun(RunKind.Exploration)
            runCurrent()

            assertEquals(
                "each attempt is scored on its own time",
                0L,
                vm.runTimes.value.exploration,
            )

            vm.endRun()
            runCurrent()
        }

    /** Zeroing one task must not disturb the other's banked time. */
    @Test fun `starting a run does not zero the other task's clock`() = runTest {
        val fake = FakeTransport()
        val vm = connectedViewModel(fake)

        vm.startRun(RunKind.Exploration)
        runCurrent()
        advanceTimeBy(Config.RUN_TIMER_TICK_MS * 4)
        runCurrent()
        vm.endRun()
        runCurrent()
        val exploration = vm.runTimes.value.exploration

        vm.startRun(RunKind.FastestCar)
        runCurrent()

        assertEquals(
            "the exploration clock is not this run's to reset",
            exploration,
            vm.runTimes.value.exploration,
        )

        vm.endRun()
        runCurrent()
    }

    @Test fun `endRun stops the clock and transmits nothing`() = runTest {
        val fake = FakeTransport()
        val vm = connectedViewModel(fake)

        vm.startRun(RunKind.Exploration)
        runCurrent()
        advanceTimeBy(Config.RUN_TIMER_TICK_MS)
        runCurrent()
        val sentAtStop = fake.sent.size

        vm.endRun()
        runCurrent()
        val stopped = vm.runTimes.value.exploration

        assertNull(vm.runTimes.value.running)
        assertEquals("endRun must not transmit anything", sentAtStop, fake.sent.size)

        // Ticking has genuinely stopped, not just the `running` flag - advancing
        // further virtual time must not move the reading.
        advanceTimeBy(Config.RUN_TIMER_TICK_MS * 4)
        runCurrent()
        assertEquals(stopped, vm.runTimes.value.exploration)
    }

    @Test fun `onCleared cancels the tick loop so it does not outlive the ViewModel`() = runTest {
        val fake = FakeTransport()
        val vm = connectedViewModel(fake)

        vm.startRun(RunKind.Exploration)
        runCurrent()
        advanceTimeBy(Config.RUN_TIMER_TICK_MS)
        runCurrent()

        // Simulates the ViewModel being cleared while a run is still active
        // (navigation away, screen torn down) WITHOUT the operator pressing
        // end-run - nothing else would ever stop the tick coroutine.
        vm.onCleared()
        val atClear = vm.runTimes.value.exploration

        // Proof by advancing past it, not by inspecting a flag: if the tick
        // coroutine were still alive, this would move the reading again.
        advanceTimeBy(Config.RUN_TIMER_TICK_MS * 4)
        runCurrent()
        assertEquals(atClear, vm.runTimes.value.exploration)
    }

    @Test fun `a ViewModel built over an already-running timer resumes ticking`() = runTest {
        val fake = FakeTransport()
        // The RunTimer is owned at process scope by MdpApplication, so a run
        // started by a PREVIOUS ViewModel is still going when this one is
        // built (a configuration change the activity does not handle itself).
        // onCleared() stopped the old tick job without stopping the clock, so
        // nothing would be driving the on-screen reading unless this ViewModel
        // picks it back up.
        val runTimer = RunTimer { testScheduler.currentTime }
        runTimer.start(RunKind.Exploration)

        val vm = connectedViewModel(fake, runTimer = runTimer)
        assertEquals(RunKind.Exploration, vm.runTimes.value.running)

        advanceTimeBy(Config.RUN_TIMER_TICK_MS)
        runCurrent()
        assertEquals(Config.RUN_TIMER_TICK_MS, vm.runTimes.value.exploration)

        // Stop the resumed tick coroutine before the test ends - see the note
        // on the first startRun test above.
        vm.endRun()
        runCurrent()
    }

    @Test fun `onCleared stops the inbound collectors so they do not outlive the ViewModel`() = runTest {
        val fake = FakeTransport()
        val vm = connectedViewModel(fake)

        fake.deliver("MSG,[before]")
        runCurrent()
        assertEquals("before", vm.statusText.value)

        // The collectors started in `init` run on the injected scope, which
        // the caller owns and which outlives this ViewModel - so nothing else
        // would ever stop them. Left running, every ViewModel ever built
        // keeps collecting the repository for the life of the process.
        vm.onCleared()
        runCurrent()

        fake.deliver("MSG,[after]")
        runCurrent()
        assertEquals(
            "a cleared ViewModel must not still be collecting the repository",
            "before",
            vm.statusText.value,
        )
    }

    @Test fun `sendArena sends the sendArena token`() = runTest {
        val fake = FakeTransport()
        val vm = connectedViewModel(fake)

        vm.sendArena()
        runCurrent()

        assertEquals(listOf(Config.taskTokens.sendArena), fake.sent)
    }

    // --- Arena persistence --------------------------------------------------

    /**
     * This test previously asserted the opposite - that reset transmits
     * nothing - on the reasoning that the robot would relearn the layout from
     * the ADDs the operator's re-entry sends. That reasoning does not hold:
     * ADD only updates a position, it never retracts one, so re-placing FEWER
     * obstacles than were cleared leaves the robot believing in the remainder
     * permanently. Reset now retracts explicitly, matching loadLayout.
     */
    @Test fun `resetArena clears local state and retracts every obstacle`() = runTest {
        val fake = FakeTransport()
        val vm = connectedViewModel(fake)

        vm.place(Cell(10, 6))
        vm.place(Cell(4, 15))
        vm.select(1)
        runCurrent()
        val cleared = vm.arena.value.obstacles.map { it.id }
        assertEquals("precondition: two obstacles placed", 2, cleared.size)
        val sentBeforeReset = fake.sent.size

        vm.resetArena()
        runCurrent()

        assertTrue(vm.arena.value.obstacles.isEmpty())
        assertNull(vm.selectedId.value)

        assertEquals(
            "reset must retract exactly the obstacles it cleared, one SUB each",
            cleared.map { "SUB,B$it" },
            fake.sent.drop(sentBeforeReset),
        )
    }

    @Test fun `saveLayout surfaces a failure through statusText instead of failing silently`() = runTest {
        val fake = FakeTransport()
        val store = FakeArenaStore()
        val vm = connectedViewModel(fake, arenaStore = store)

        vm.place(Cell(10, 6))
        runCurrent()

        store.failNext = true
        vm.saveLayout("pre-run")
        runCurrent()

        assertEquals("Could not save layout \"pre-run\"", vm.statusText.value)
        // The failure must not be reported as if the save had happened.
        assertTrue(vm.savedLayouts.value.isEmpty())
    }

    @Test fun `loadLayout surfaces a failure through statusText instead of failing silently`() = runTest {
        val fake = FakeTransport()
        val store = FakeArenaStore()
        val vm = connectedViewModel(fake, arenaStore = store)

        store.failNext = true
        vm.loadLayout("anything")
        runCurrent()

        assertEquals("Could not load layout \"anything\"", vm.statusText.value)
        assertTrue("a failed load must not touch the arena", vm.arena.value.obstacles.isEmpty())
    }

    @Test fun `saveLayout and loadLayout round-trip through the store`() = runTest {
        val fake = FakeTransport()
        val vm = connectedViewModel(fake)

        vm.place(Cell(6, 6))
        runCurrent()
        vm.saveLayout("mid-game")
        runCurrent()

        assertEquals(listOf("mid-game"), vm.savedLayouts.value)
        assertNull("a successful save must not leave an error message behind", vm.statusText.value)

        // Clear the local view, then load the saved name back - the content
        // must genuinely survive the round trip, not just the in-memory
        // savedLayouts bookkeeping asserted above.
        vm.resetArena()
        assertTrue(vm.arena.value.obstacles.isEmpty())

        vm.loadLayout("mid-game")
        runCurrent()

        assertEquals(listOf(Cell(6, 6)), vm.arena.value.obstacles.map { it.cell })
        assertNull("a successful load must not leave an error message behind", vm.statusText.value)
    }

    @Test fun `deleteLayout removes the name and refreshes the list`() = runTest {
        val fake = FakeTransport()
        val vm = connectedViewModel(fake)

        vm.saveLayout("practice")
        runCurrent()
        vm.saveLayout("scored")
        runCurrent()
        assertEquals(listOf("practice", "scored"), vm.savedLayouts.value)

        vm.deleteLayout("practice")
        runCurrent()

        assertEquals(listOf("scored"), vm.savedLayouts.value)
        assertNull("a successful delete must not leave an error behind", vm.statusText.value)
    }

    /** Deleting is local bookkeeping - the robot was never told the layout existed. */
    @Test fun `deleteLayout transmits nothing`() = runTest {
        val fake = FakeTransport()
        val vm = connectedViewModel(fake)

        vm.saveLayout("practice")
        runCurrent()
        val sentBefore = fake.sent.size

        vm.deleteLayout("practice")
        runCurrent()

        assertEquals(sentBefore, fake.sent.size)
    }

    @Test fun `deleteLayout surfaces a failure instead of failing silently`() = runTest {
        val fake = FakeTransport()
        val store = FakeArenaStore()
        val vm = connectedViewModel(fake, arenaStore = store)

        vm.saveLayout("practice")
        runCurrent()

        store.failNext = true
        vm.deleteLayout("practice")
        runCurrent()

        assertEquals("Could not delete layout \"practice\"", vm.statusText.value)
        assertEquals(
            "a failed delete must leave the list as it was",
            listOf("practice"),
            vm.savedLayouts.value,
        )
    }

    // --- Manual clock reset -------------------------------------------------

    @Test fun `resetRunClock zeroes that clock and leaves the other alone`() = runTest {
        val fake = FakeTransport()
        val vm = connectedViewModel(fake)

        vm.startRun(RunKind.Exploration)
        runCurrent()
        advanceTimeBy(Config.RUN_TIMER_TICK_MS * 4)
        runCurrent()
        vm.endRun()
        runCurrent()

        vm.startRun(RunKind.FastestCar)
        runCurrent()
        advanceTimeBy(Config.RUN_TIMER_TICK_MS * 4)
        runCurrent()
        vm.endRun()
        runCurrent()

        val fastest = vm.runTimes.value.fastestCar
        assertTrue("precondition: both clocks carry time", vm.runTimes.value.exploration > 0L)
        assertTrue("precondition: both clocks carry time", fastest > 0L)

        vm.resetRunClock(RunKind.Exploration)

        assertEquals(0L, vm.runTimes.value.exploration)
        assertEquals("the other task's clock is not this reset's to touch", fastest, vm.runTimes.value.fastestCar)
    }

    /**
     * The gesture behind this is a long-press on the reading itself, which is
     * exactly what a thumb does by accident while holding the tablet. Mid-run
     * that would destroy a scored time with no way back.
     */
    @Test fun `resetRunClock is refused while that run is active`() = runTest {
        val fake = FakeTransport()
        val vm = connectedViewModel(fake)

        vm.startRun(RunKind.Exploration)
        runCurrent()
        advanceTimeBy(Config.RUN_TIMER_TICK_MS * 4)
        runCurrent()
        val running = vm.runTimes.value.exploration
        assertTrue("precondition: the clock is running and non-zero", running > 0L)

        vm.resetRunClock(RunKind.Exploration)

        assertEquals("a running clock must not be resettable", running, vm.runTimes.value.exploration)
        assertEquals(RunKind.Exploration, vm.runTimes.value.running)

        vm.endRun()
        runCurrent()
    }

    /** Only the RUNNING task is protected; the idle one stays resettable. */
    @Test fun `resetRunClock still works on the idle clock during a run`() = runTest {
        val fake = FakeTransport()
        val vm = connectedViewModel(fake)

        vm.startRun(RunKind.FastestCar)
        runCurrent()
        advanceTimeBy(Config.RUN_TIMER_TICK_MS * 4)
        runCurrent()
        vm.endRun()
        runCurrent()

        vm.startRun(RunKind.Exploration)
        runCurrent()

        vm.resetRunClock(RunKind.FastestCar)

        assertEquals(0L, vm.runTimes.value.fastestCar)
        assertEquals("the active run is untouched", RunKind.Exploration, vm.runTimes.value.running)

        vm.endRun()
        runCurrent()
    }

    @Test fun `loadLayout transmits ADD and FACE for every restored obstacle`() = runTest {
        val fake = FakeTransport()
        val store = FakeArenaStore()
        // Populate storage directly through the same store - this is what a
        // PRIOR session's saveLayout would have produced.
        val saved = Arena(
            obstacles = listOf(
                Obstacle(id = 1, cell = Cell(2, 3), imageFace = Face.N),
                Obstacle(id = 2, cell = Cell(9, 1)),
            ),
        )
        store.save("comp-layout", saved)

        val vm = connectedViewModel(fake, arenaStore = store)

        vm.loadLayout("comp-layout")
        runCurrent()

        // resetArena's silence does not apply here - a load has no gestures
        // following it for the robot to learn the layout from, so every
        // restored obstacle must be announced, plus a FACE for the one
        // carrying an operator annotation. The arena started empty, so there
        // is nothing to retract (see the resync test below for that half).
        assertEquals(
            listOf("ADD,B1,(2,3)", "FACE,B1,(2,3),N", "ADD,B2,(9,1)"),
            fake.sent,
        )
        assertEquals(setOf(1, 2), vm.arena.value.obstacles.map { it.id }.toSet())
    }

    @Test fun `loadLayout resyncs - retracts obstacles absent from the newly loaded layout`() = runTest {
        val fake = FakeTransport()
        val store = FakeArenaStore()
        store.save("layout-a", Arena(obstacles = listOf(Obstacle(id = 1, cell = Cell(5, 5)), Obstacle(id = 2, cell = Cell(6, 6)))))
        store.save("layout-b", Arena(obstacles = listOf(Obstacle(id = 1, cell = Cell(2, 3), imageFace = Face.N))))

        val vm = connectedViewModel(fake, arenaStore = store)

        // Loading layout B over layout A - without resetting first - is an
        // ordinary operator action. The robot must not be left believing
        // A's obstacles still exist.
        vm.loadLayout("layout-a")
        runCurrent()
        val afterA = fake.sent.size

        vm.loadLayout("layout-b")
        runCurrent()

        assertEquals(
            listOf("SUB,B1", "SUB,B2", "ADD,B1,(2,3)", "FACE,B1,(2,3),N"),
            fake.sent.drop(afterA),
        )
        assertEquals(listOf(Cell(2, 3)), vm.arena.value.obstacles.map { it.cell })
    }
}
