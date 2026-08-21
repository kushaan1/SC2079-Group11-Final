package com.mdp.grp11.connection

import com.mdp.grp11.config.Config
import com.mdp.grp11.protocol.Inbound
import com.mdp.grp11.protocol.Outbound
import com.mdp.grp11.protocol.decode
import com.mdp.grp11.protocol.encode
import com.mdp.grp11.transport.ConnectTarget
import com.mdp.grp11.transport.DeviceInfo
import com.mdp.grp11.transport.Transport
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/** One line of Bluetooth traffic, for the raw log. */
data class TrafficLine(val outbound: Boolean, val text: String, val delivered: Boolean)

/**
 * Owns the link. Application-scoped, so it outlives every ViewModel and the
 * arena survives a rotation or a reconnect. The UI never touches a socket and
 * never blocks on one.
 */
class ConnectionRepository(
    private val transport: Transport,
    private val scope: CoroutineScope,
) {

    private val _state = MutableStateFlow<ConnectionState>(ConnectionState.Idle)
    val state: StateFlow<ConnectionState> = _state.asStateFlow()

    private val _inbound = MutableSharedFlow<Inbound>(extraBufferCapacity = 64)
    val inbound: SharedFlow<Inbound> = _inbound.asSharedFlow()

    private val _traffic = MutableSharedFlow<TrafficLine>(extraBufferCapacity = 128)
    val traffic: SharedFlow<TrafficLine> = _traffic.asSharedFlow()

    private val writeLock = Mutex()
    private var readJob: Job? = null
    private var connWatchJob: Job? = null
    private var reconnectJob: Job? = null
    private var lastTarget: ConnectTarget? = null

    /**
     * Stamped on each [connect] at entry so an attempt can tell whether it is
     * still the current one. Only the newest may publish anything.
     *
     * A boolean cannot express this. The real transport can sit in a blocking
     * socket connect for ~12s, long enough that an operator taps again, so two
     * overlapping calls are ordinary - and the loser then publishes its own
     * outcome over the winner's. Two attempts racing the adapter usually means
     * the loser's socket calls fail, which arrives as `Result.failure` rather
     * than a cancellation, so it writes `Failed` over a live `Connected` and
     * the UI shows a disconnected banner while traffic is flowing.
     *
     * Not a cancellation-based guard: a deliberate connect should not be
     * cancelled just because a send failed while it was in flight. Only its
     * stale effects need suppressing.
     */
    private var connectGeneration = 0

    /**
     * How many [connect] calls are suspended inside `transport.connect()`. Read
     * only by [beginReconnect]. A count, not a boolean: overlapping calls would
     * otherwise clear each other's guard.
     *
     * Released the instant the suspension ends, deliberately NOT held across
     * [startReading]/[watchConnection]. Holding it longer swallows a drop
     * landing in the dispatch window right after a successful connect - the
     * watcher subscribes, the StateFlow delivers `false`, and [beginReconnect]
     * returns early on the guard, leaving the app in `Connected` on a dead link.
     */
    private var connectsInFlight = 0

    /**
     * Writes [state] only if the [connect] that stamped [generation] is still
     * current. Every `_state.value` write inside [connect] goes through here,
     * including the trivially-current `Connecting` one, so that no later edit
     * can introduce a publication that skips the check.
     */
    private fun publishIfCurrent(generation: Int, state: ConnectionState) {
        if (generation != connectGeneration) return
        _state.value = state
    }

    suspend fun connect(target: ConnectTarget) {
        // A deliberate tap must win over an automatic retry: a reconnect loop
        // parked inside transport.connect() would otherwise resume later and
        // overwrite - or on the real transport tear down - the session this
        // call is about to establish.
        reconnectJob?.cancel()
        reconnectJob = null

        val myGeneration = ++connectGeneration
        val known = (target as? ConnectTarget.Client)?.device

        // Also blocks beginReconnect() from starting a NEW loop while this call
        // is in flight: a movement button pressed during a slow connect fails,
        // calls beginReconnect(), and one backoff later that loop would connect
        // to the same target and tear down the session being established.
        // send() never reads this counter, so a slow connect cannot deadlock a
        // movement command.
        connectsInFlight++
        val result = try {
            lastTarget = target
            publishIfCurrent(myGeneration, ConnectionState.Connecting(known))
            transport.connect(target)
        } finally {
            connectsInFlight--
        }

        // A superseded attempt publishes nothing and starts nothing.
        if (myGeneration != connectGeneration) {
            // Before walking away, re-examine the link this attempt held the
            // reconnect guard over. While it was parked, a drop could have
            // arrived and been swallowed - watchConnection() would have called
            // beginReconnect(), which correctly returned early on the guard,
            // and a StateFlow never re-delivers that `false`. Recovering on the
            // next send() is not enough: during an exploration run the robot
            // drives itself and the operator sends nothing for minutes.
            if (!transport.connected.value && _state.value is ConnectionState.Connected) {
                beginReconnect()
            }
            return
        }

        result
            .onSuccess { device ->
                publishIfCurrent(myGeneration, ConnectionState.Connected(device))
                startReading()
                watchConnection()
            }
            .onFailure { e ->
                publishIfCurrent(
                    myGeneration,
                    ConnectionState.Failed(e.message ?: "connect failed"),
                )
            }
    }

    private fun startReading() {
        readJob?.cancel()
        readJob = scope.launch {
            transport.incoming.collect { line ->
                _traffic.emit(TrafficLine(outbound = false, text = line, delivered = true))
                // decode is total, so a bad line can never kill this loop.
                _inbound.emit(decode(line))
            }
        }
    }

    /**
     * The only way the repository learns the peer vanished without anyone
     * pressing a button: `incoming` is a hot flow that never completes, and a
     * read loop returns silently on EOF. `transport.connected` is a StateFlow,
     * so a late subscriber still sees the current value.
     */
    private fun watchConnection() {
        connWatchJob?.cancel()
        connWatchJob = scope.launch {
            transport.connected.collect { isUp ->
                if (!isUp && _state.value is ConnectionState.Connected) {
                    beginReconnect()
                }
            }
        }
    }

    /** Returns true when the message actually reached the peer. */
    suspend fun send(msg: Outbound): Boolean {
        val text = encode(msg)
        val ok = writeLock.withLock { transport.send(text).isSuccess }
        _traffic.emit(TrafficLine(outbound = true, text = text, delivered = ok))
        if (!ok) beginReconnect()
        return ok
    }

    private fun beginReconnect() {
        // Only ever RE-connect: resume a link that was up, never promote one
        // that never came up. Arena edits are deliberately not gated on the
        // link, so a send attempted while the bar reads FAILED would otherwise
        // start a retry loop and replace the RETRY button - the operator's only
        // way back - with a reconnecting spinner that masks a real fault.
        val current = _state.value
        if (current !is ConnectionState.Connected && current !is ConnectionState.Reconnecting) return
        // A deliberate connect already owns this target's outcome; let it
        // finish before an automatic retry runs at all. Checked separately from
        // the job guard below: this is a retry racing a deliberate connect, not
        // two retry loops racing each other.
        if (connectsInFlight > 0) return
        // Guard on the job, assigned synchronously below, rather than on state
        // set inside the coroutine - two failing callers must not start two
        // overlapping loops.
        if (reconnectJob?.isActive == true) return
        val target = lastTarget ?: return
        val device = (target as? ConnectTarget.Client)?.device
        reconnectJob = scope.launch {
            var attempt = 1
            while (true) {
                _state.value = ConnectionState.Reconnecting(device, attempt)
                delay(Config.BACKOFF_MS.getOrElse(attempt - 1) { Config.BACKOFF_MS.last() })
                val result = transport.connect(target)
                // Cancelling this job cannot interrupt a blocking socket call;
                // it only flips isActive. So check the instant control returns,
                // before touching state: a cancelled loop must not publish over
                // whatever superseded it, and looping again would reopen a
                // socket nobody asked for.
                if (!isActive) return@launch
                if (result.isSuccess) {
                    _state.value = ConnectionState.Connected(result.getOrThrow())
                    startReading()
                    watchConnection()
                    return@launch
                }
                attempt++
            }
        }
    }

    fun disconnect() {
        // Supersede any connect still parked inside transport.connect().
        // Without this it resumes after this call and publishes over the Idle
        // just asked for - Connected, resurrecting a link closed on purpose, or
        // Failed, claiming a fault that does not exist.
        connectGeneration++
        readJob?.cancel()
        readJob = null
        connWatchJob?.cancel()
        connWatchJob = null
        reconnectJob?.cancel()
        reconnectJob = null
        transport.close()
        _state.value = ConnectionState.Idle
    }
}
