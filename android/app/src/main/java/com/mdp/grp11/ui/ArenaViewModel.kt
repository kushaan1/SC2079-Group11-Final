package com.mdp.grp11.ui

import androidx.lifecycle.ViewModel
import com.mdp.grp11.arena.Arena
import com.mdp.grp11.arena.ArenaStore
import com.mdp.grp11.arena.Cell
import com.mdp.grp11.config.Config
import com.mdp.grp11.connection.ConnectionRepository
import com.mdp.grp11.connection.TrafficLine
import com.mdp.grp11.protocol.Face
import com.mdp.grp11.protocol.Inbound
import com.mdp.grp11.protocol.Outbound
import com.mdp.grp11.protocol.imageLabel
import com.mdp.grp11.session.RunKind
import com.mdp.grp11.session.RunTimer
import com.mdp.grp11.session.RunTimes
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * Where operator gestures become transmitted messages, and inbound robot
 * reports become screen state.
 *
 * ADD is transmitted whenever positioning of an obstacle completes, which
 * happens two ways: a tap that places a block ([place], which transmits at
 * once, since nothing follows a tap) and a drag that ends ([commit], on
 * finger-lift). Tapping a block into place and later dragging it correctly
 * produces two ADDs - two positions announced, not a duplicate.
 *
 * `Obstacle.imageFace` (what WE annotate, outbound, written only by [pickFace])
 * and `Obstacle.target` (what the ROBOT reports, inbound, written only by
 * [onInbound]) are different fields, and neither function touches the other's.
 */
class ArenaViewModel(
    private val repo: ConnectionRepository,
    private val scope: CoroutineScope,
    private val runTimer: RunTimer,
    private val arenaStore: ArenaStore,
) : ViewModel() {

    private val _arena = MutableStateFlow(Arena())
    val arena: StateFlow<Arena> = _arena.asStateFlow()

    private val _selectedId = MutableStateFlow<Int?>(null)
    val selectedId: StateFlow<Int?> = _selectedId.asStateFlow()

    private val _statusText = MutableStateFlow<String?>(null)
    val statusText: StateFlow<String?> = _statusText.asStateFlow()

    /**
     * Posts an app-level message to the status line, sharing the surface the
     * robot's own status uses rather than adding a second one - the operator
     * has one place they are trained to look. The next inbound status
     * overwrites it, so nothing lingers into a scored run.
     */
    fun note(text: String) {
        _statusText.value = text
    }

    private val _targetLine = MutableStateFlow<String?>(null)
    val targetLine: StateFlow<String?> = _targetLine.asStateFlow()

    private val _traffic = MutableStateFlow<List<TrafficLine>>(emptyList())
    val traffic: StateFlow<List<TrafficLine>> = _traffic.asStateFlow()

    private val _runTimes = MutableStateFlow(runTimer.times())
    val runTimes: StateFlow<RunTimes> = _runTimes.asStateFlow()

    private val _savedLayouts = MutableStateFlow<List<String>>(emptyList())
    val savedLayouts: StateFlow<List<String>> = _savedLayouts.asStateFlow()

    /**
     * Cell each obstacle was last CONFIRMED told to the robot. Seeded by
     * [place], refreshed by [dragTo], consumed by [commit].
     *
     * Deliberately not written by [select]: a cancelled drag can leave the
     * local arena at a cell the robot was never told about, and if a bare
     * selection adopted that cell as truth, a later no-net-movement drag would
     * conclude nothing needs reporting and the robot would stay stuck on stale
     * information with nothing able to correct it.
     */
    private val dragOrigin = mutableMapOf<Int, Cell>()

    /** Ticks [_runTimes] while a run is active. */
    private var tickJob: Job? = null

    /**
     * The collectors started in `init`, retained so [onCleared] can stop them.
     * They run on the injected [scope], which the caller owns and which
     * outlives this ViewModel, so otherwise every ViewModel ever built would go
     * on collecting the repository for the life of the process.
     *
     * Declared before the `init` that fills it - initialisers run in
     * declaration order.
     */
    private val collectorJobs = mutableListOf<Job>()

    init {
        collectorJobs += scope.launch { repo.inbound.collect(::onInbound) }
        collectorJobs += scope.launch {
            repo.traffic.collect { line ->
                // Oldest-first, matching BtLogPanel's contract. takeLast, not
                // take - take would keep the oldest lines forever instead of
                // rolling the window forward.
                _traffic.value = (_traffic.value + line).takeLast(Config.TRAFFIC_LOG_CAP)
            }
        }
        collectorJobs += scope.launch { refreshSavedLayouts() }

        // The timer is process-scoped so a scored clock survives this ViewModel
        // being rebuilt, but [onCleared] stops the tick - so a ViewModel
        // constructed over a run still in progress must pick the ticking back
        // up, or the reading sits frozen until the next start or stop.
        if (runTimer.times().running != null) startTicking()
    }

    private fun onInbound(msg: Inbound) {
        when (msg) {
            is Inbound.Status -> _statusText.value = msg.text
            is Inbound.TargetFound -> {
                _arena.value = _arena.value.applyTarget(msg.obstacle, msg.targetId, msg.face)
                // The block shows the id; the symbol goes here so correctness
                // can be judged without the lookup table.
                _targetLine.value =
                    "Target ${msg.targetId} · ${imageLabel(msg.targetId)} · at B${msg.obstacle}"
            }
            is Inbound.Pose -> _arena.value = _arena.value.applyPose(msg.x, msg.y, msg.heading)
            is Inbound.Unknown -> Unit   // already in the raw log
        }
    }

    /**
     * A tap on empty ground. Placing is a completed positioning in its own
     * right, so the new obstacle's ADD goes out immediately.
     */
    fun place(cell: Cell) {
        val (next, placed) = _arena.value.place(cell)
        _arena.value = next
        if (placed != null) {
            _selectedId.value = placed.id
            dragOrigin[placed.id] = placed.cell
            scope.launch { repo.send(Outbound.AddObstacle(placed.id, placed.cell.x, placed.cell.y)) }
        }
    }

    fun select(id: Int) {
        _selectedId.value = id
    }

    fun dragTo(id: Int, cell: Cell) {
        if (!dragOrigin.containsKey(id)) {
            _arena.value.obstacle(id)?.let { dragOrigin[id] = it.cell }
        }
        _arena.value = _arena.value.move(id, cell)
    }

    /**
     * ADD for the drag path. Fires on finger-lift, never mid-drag - one message
     * per cell crossed would flood the link - and only when the drag actually
     * changed the cell, so a lift with no net movement does not re-announce a
     * position the robot already has.
     */
    fun commit(id: Int) {
        val o = _arena.value.obstacle(id) ?: return
        val origin = dragOrigin.remove(id)
        if (origin != null && origin != o.cell) {
            scope.launch { repo.send(Outbound.AddObstacle(o.id, o.cell.x, o.cell.y)) }
        }
    }

    fun dropOutside(id: Int) {
        _arena.value = _arena.value.remove(id)
        if (_selectedId.value == id) _selectedId.value = null
        dragOrigin.remove(id)
        scope.launch { repo.send(Outbound.RemoveObstacle(id)) }
    }

    /** Tapping the active face again clears it, which is how a mis-tap is undone. */
    fun pickFace(face: Face) {
        val id = _selectedId.value ?: return
        val o = _arena.value.obstacle(id) ?: return
        val next = if (o.imageFace == face) null else face
        _arena.value = _arena.value.setFace(id, next)
        scope.launch { repo.send(Outbound.SetFace(id, o.cell.x, o.cell.y, next)) }
    }

    fun clearSelection() { _selectedId.value = null }

    fun move(token: String) {
        scope.launch { repo.send(Outbound.Move(token)) }
    }

    /**
     * Starts the clock AND sends the task token as one action. A start button
     * that moves the robot without starting the clock, or the reverse, is worse
     * than useless mid-run: the operator cannot tell which happened.
     *
     * The clock is zeroed first because [RunTimer.start] banks the previous
     * elapsed time and counts up from it, so a practice run followed by the
     * scored attempt would otherwise display the sum. Only [kind] is zeroed.
     */
    fun startRun(kind: RunKind) {
        runTimer.reset(kind)
        runTimer.start(kind)
        _runTimes.value = runTimer.times()
        startTicking()
        move(taskTokenFor(kind))
    }

    /** Drives the on-screen reading while a run is active. */
    private fun startTicking() {
        tickJob?.cancel()
        tickJob = scope.launch {
            while (true) {
                delay(Config.RUN_TIMER_TICK_MS)
                _runTimes.value = runTimer.times()
            }
        }
    }

    /** Stops the clock and the tick. Sends nothing - AMD has no end-run slot. */
    fun endRun() {
        tickJob?.cancel()
        tickJob = null
        runTimer.stop()
        _runTimes.value = runTimer.times()
    }

    /**
     * Cancels the jobs this class started on the caller-owned [scope]. Nothing
     * else would: left alone, the tick loop burns cycles writing a StateFlow
     * nobody collects, and the `init` collectors keep reading the repository
     * for the life of the app. [scope] itself is not ours to cancel.
     *
     * Widened to public so unit tests can invoke it - normally only a
     * ViewModelStore does, and these are plain JVM tests.
     */
    public override fun onCleared() {
        tickJob?.cancel()
        tickJob = null
        collectorJobs.forEach { it.cancel() }
        collectorJobs.clear()
        super.onCleared()
    }

    fun sendArena() {
        move(Config.taskTokens.sendArena)
    }

    fun saveLayout(name: String) {
        scope.launch {
            try {
                arenaStore.save(name, _arena.value)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _statusText.value = "Could not save layout \"$name\""
                return@launch
            }
            refreshSavedLayouts()
        }
    }

    /**
     * Removes a saved layout. Purely local - the robot was never told this
     * layout existed. Failure is surfaced because the list refreshes straight
     * after, so silence would leave the operator looking at a name they just
     * deleted and concluding the button is broken.
     */
    fun deleteLayout(name: String) {
        scope.launch {
            try {
                arenaStore.delete(name)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _statusText.value = "Could not delete layout \"$name\""
                return@launch
            }
            refreshSavedLayouts()
        }
    }

    /**
     * Zeroes one clock without starting a run, for clearing a stale reading
     * between attempts.
     *
     * Refused while that clock is RUNNING: the gesture behind this is a
     * long-press on the reading itself, which is exactly what a thumb does by
     * accident while holding the tablet, and a scored time destroyed has no way
     * back. The other clock is never touched.
     */
    fun resetRunClock(kind: RunKind) {
        if (runTimer.times().running == kind) return
        runTimer.reset(kind)
        _runTimes.value = runTimer.times()
    }

    /**
     * A full resync, not just an announcement: every obstacle the robot knows
     * about is retracted with SUB, then every loaded obstacle is announced with
     * ADD, and FACE for any carrying an annotation.
     *
     * Retraction matters because loading layout B over layout A - an ordinary
     * operator action - would otherwise leave the robot believing A's obstacles
     * still exist. Unlike an edit, a load has no gestures following it for the
     * robot to learn the new layout from.
     */
    fun loadLayout(name: String) {
        scope.launch {
            val loaded = try {
                arenaStore.load(name)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _statusText.value = "Could not load layout \"$name\""
                return@launch
            } ?: run {
                // A null is a decode failure - wrong format version, a
                // truncated write - not an I/O one, so it lands here rather
                // than in the catch above. Silence would make LOAD look dead.
                _statusText.value = "Layout \"$name\" is unreadable"
                return@launch
            }

            val stale = _arena.value.obstacles
            _arena.value = loaded
            _selectedId.value = null
            dragOrigin.clear()

            stale.forEach { o -> repo.send(Outbound.RemoveObstacle(o.id)) }
            loaded.obstacles.forEach { o ->
                repo.send(Outbound.AddObstacle(o.id, o.cell.x, o.cell.y))
                o.imageFace?.let { face -> repo.send(Outbound.SetFace(o.id, o.cell.x, o.cell.y, face)) }
            }
        }
    }

    /**
     * Clears the arena on the tablet AND retracts every obstacle from the robot.
     *
     * The retraction is not optional: ADD only ever updates a position, never
     * removes one. Reset from eight obstacles, re-place three, and the robot
     * permanently believes in five the tablet does not have, with no later
     * action able to correct it. The cost if this is unnecessary is a few SUB
     * lines on a link that is idle during editing.
     */
    fun resetArena() {
        val stale = _arena.value.obstacles
        _arena.value = Arena()
        _selectedId.value = null
        dragOrigin.clear()
        scope.launch { stale.forEach { o -> repo.send(Outbound.RemoveObstacle(o.id)) } }
    }

    /**
     * A storage failure must never crash the app, but it must not be silent
     * either: running after a save whose confirmation already passed, a
     * swallowed failure leaves the operator looking at a stale list and finding
     * the gap only when they load a name that never made it in.
     *
     * `CancellationException` is caught and rethrown ahead of the generic
     * branch - a coroutine cancelled mid-call must unwind rather than carry on.
     */
    private suspend fun refreshSavedLayouts() {
        try {
            _savedLayouts.value = arenaStore.names()
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            _statusText.value = "Could not refresh saved layouts"
        }
    }

    private fun taskTokenFor(kind: RunKind): String = when (kind) {
        RunKind.Exploration -> Config.taskTokens.beginExploration
        RunKind.FastestCar -> Config.taskTokens.beginFastest
    }
}
