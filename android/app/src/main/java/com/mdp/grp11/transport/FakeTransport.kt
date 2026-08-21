package com.mdp.grp11.transport

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.withContext
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * In-memory Transport for tests and for developing without hardware.
 * The emulator has no Bluetooth SPP stack and the AMD tool needs a second
 * physical device, so this is the only way to exercise the app solo.
 */
class FakeTransport : Transport {

    private val _incoming = MutableSharedFlow<String>(extraBufferCapacity = 64)
    override val incoming: SharedFlow<String> = _incoming.asSharedFlow()

    private val _connected = MutableStateFlow(false)
    override val connected: StateFlow<Boolean> = _connected.asStateFlow()

    private val _sent = mutableListOf<String>()
    val sent: List<String> get() = _sent

    var failNextConnect: Boolean = false

    /**
     * Optional suspension gate for [connect]. `null` means connect() resolves
     * synchronously. A test that wants to park a call mid-flight - the way the
     * real transport sits for seconds inside a blocking socket call - sets a
     * fresh `CompletableDeferred()` here, then completes it to let go.
     */
    var connectGate: CompletableDeferred<Unit>? = null

    override suspend fun connect(target: ConnectTarget): Result<DeviceInfo> {
        // NonCancellable, not a plain await(): a plain await() reacts to the
        // CALLER's cancellation and throws, so no test could exercise a caller
        // that checks cancellation itself against a connect() that completes
        // normally despite the caller already being cancelled - which is both
        // what those checks guard, and how a transport with no
        // cancellation-aware suspension point behaves anyway.
        connectGate?.let { withContext(NonCancellable) { it.await() } }
        if (failNextConnect) {
            failNextConnect = false
            return Result.failure(IllegalStateException("fake: refused"))
        }
        _connected.value = true
        val device = when (target) {
            is ConnectTarget.Client -> target.device
            ConnectTarget.Listen -> DeviceInfo("FAKE-PEER", "00:00:00:00:00:00")
        }
        return Result.success(device)
    }

    override suspend fun send(line: String): Result<Unit> {
        if (!_connected.value) return Result.failure(IllegalStateException("fake: not connected"))
        _sent += line
        return Result.success(Unit)
    }

    override fun close() {
        _connected.value = false
    }

    // --- levers only a fake has -------------------------------------------

    /** Simulate a line arriving from the peer. */
    suspend fun deliver(line: String) {
        _incoming.emit(line)
    }

    /** Simulate the peer vanishing mid-session. */
    fun dropLink() {
        _connected.value = false
    }
}
