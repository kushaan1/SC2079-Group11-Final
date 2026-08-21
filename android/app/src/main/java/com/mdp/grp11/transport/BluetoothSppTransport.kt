package com.mdp.grp11.transport

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothServerSocket
import android.bluetooth.BluetoothSocket
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import androidx.core.content.ContextCompat
import com.mdp.grp11.config.Config
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import java.util.concurrent.atomic.AtomicInteger
import kotlin.coroutines.resume

/**
 * Real RFCOMM. Both roles matter:
 *  - Client, for the RPi, which runs `rfcomm listen` and is therefore server.
 *  - Listen, for the AMD tool, which connects TO the tablet. Recovery is graded
 *    by the peer reconnecting to us, so a client-only implementation fails it.
 *
 * Owns its own read loop: [connect] launches it internally the moment a socket
 * is established. Callers only collect [incoming] and watch [connected].
 */
@SuppressLint("MissingPermission")   // callers gate on BLUETOOTH_CONNECT / _SCAN
class BluetoothSppTransport(context: Context) : Transport {

    // Application context: this object is application-scoped and outlives any
    // Activity, so holding an Activity context would leak it.
    private val appContext: Context = context.applicationContext

    private val adapter: BluetoothAdapter? =
        context.getSystemService(BluetoothManager::class.java)?.adapter

    private val framer = LineFramer()
    private val _incoming = MutableSharedFlow<String>(extraBufferCapacity = 64)
    override val incoming: Flow<String> = _incoming.asSharedFlow()

    private val _connected = MutableStateFlow(false)
    override val connected: StateFlow<Boolean> = _connected.asStateFlow()

    /**
     * Root of the read loop's lifetime. A SupervisorJob so a read-loop failure
     * never cancels the scope itself - the transport must survive to serve the
     * next [connect]. [close] cancels this scope's children, never the scope.
     */
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    // Written from connect()/send() on Dispatchers.IO, from close() on the
    // caller's thread, and read by the read loop on a third thread. @Volatile
    // is what makes `socket === s` in the read loop's finally trustworthy.
    @Volatile private var readJob: Job? = null
    @Volatile private var socket: BluetoothSocket? = null
    @Volatile private var serverSocket: BluetoothServerSocket? = null

    /** Last byte read, written by the read loop and read by the flush coroutine. */
    @Volatile private var lastByteAtMs: Long = 0L

    /**
     * Bumped by [teardown] on every session teardown, so a [connect] still
     * blocked in a slow socket call can tell it has been superseded and must
     * not publish its result as the live session.
     *
     * Atomic rather than `@Volatile var`: teardown can run concurrently from
     * [close] and from the top of a fresh [connect], and a bare `epoch++` is a
     * read-modify-write that can lose an increment under exactly that race.
     */
    private val epoch = AtomicInteger(0)

    fun bondedDevices(): List<DeviceInfo> =
        adapter?.bondedDevices.orEmpty().map { DeviceInfo(it.name ?: it.address, it.address) }

    /**
     * Whether the radio is on. [bondedDevices] returns an empty list when it is
     * off, which at the call site is indistinguishable from a device with
     * nothing paired - so the picker would tell the operator to pair a device
     * that is already paired.
     */
    fun isAdapterEnabled(): Boolean = adapter?.isEnabled == true

    override suspend fun connect(target: ConnectTarget): Result<DeviceInfo> =
        withContext(Dispatchers.IO) {
            val a = adapter ?: return@withContext Result.failure(
                IllegalStateException("No Bluetooth adapter")
            )
            if (!a.isEnabled) return@withContext Result.failure(
                IllegalStateException("Bluetooth is off")
            )

            // Declared out here so onFailure below can see which epoch this
            // attempt owns. -1 is unreachable: teardown() is the first
            // statement inside runCatching and cannot throw.
            var myEpoch = -1

            val result = runCatching {
                // Tear down the previous session BEFORE starting a new one.
                // Otherwise the old reader stays parked in a blocking read()
                // and, seconds later when RFCOMM finally times out, its
                // `finally` clears `connected` on the new, healthy link.
                myEpoch = teardown()
                a.cancelDiscovery()

                val s = when (target) {
                    is ConnectTarget.Client -> {
                        val remote = a.getRemoteDevice(target.device.address)
                        // Picking an unpaired device from the scan list has to
                        // fail clearly rather than as a low-level socket error.
                        // Bounded, so a device stuck in BOND_BONDING cannot
                        // hang connect() - and therefore the UI - forever.
                        check(withTimeoutOrNull(Config.BOND_TIMEOUT_MS) { ensureBonded(remote) } ?: false) {
                            "Pairing required or failed"
                        }
                        openClientSocket(remote).also { sock ->
                            // The blocking connect() can run for seconds. If a
                            // close() or a newer connect() superseded this one
                            // meanwhile, abandon the socket rather than publish
                            // it. The Listen role needs no equivalent: close()
                            // interrupts a blocked accept() by closing
                            // serverSocket, which is assigned beforehand.
                            if (epoch.get() != myEpoch || !isActive) {
                                runCatching { sock.close() }
                                throw CancellationException("connect() superseded while blocked")
                            }
                        }
                    }
                    ConnectTarget.Listen -> {
                        val server = openServerSocket(a)
                        serverSocket = server
                        server.accept().also { server.close(); serverSocket = null }
                    }
                }
                // Reset here rather than at the top of the function, where a
                // multi-second bond or accept could sit between the reset and
                // the first byte the new reader feeds in.
                framer.reset()
                socket = s
                // Flipped before the read loop can flip it back: a peer that
                // vanishes microseconds after accept() must still produce a
                // true -> false transition, never a bare final false.
                _connected.value = true
                startReadLoop(s)
                val remote = s.remoteDevice
                DeviceInfo(remote.name ?: remote.address, remote.address)
            }

            result.onFailure {
                // Clean up only if this attempt is still current. Once a newer
                // connect() or a close() has bumped the epoch, socket and
                // serverSocket belong to THAT session - closing them here would
                // tear down a link this attempt never touched. An ordinary
                // failure leaves the epoch unchanged, so this cannot leak.
                if (epoch.get() == myEpoch) {
                    runCatching { socket?.close() }
                    runCatching { serverSocket?.close() }
                    socket = null
                    serverSocket = null
                    // If this attempt had already published the socket before
                    // something later in the block threw, nulling `socket`
                    // above permanently disarms the read loop's identity guard,
                    // so that reader can never clear `connected` itself.
                    _connected.value = false
                }
            }

            // A real cancellation must propagate rather than be reported as a
            // failed connect; runCatching would otherwise swallow it into
            // Result.failure and break structured concurrency for the caller.
            (result.exceptionOrNull() as? CancellationException)?.let { throw it }

            result
        }

    /**
     * Cancels the read loop and closes whatever sockets are open. Does not
     * touch [framer] - callers reset it where it matters for them.
     *
     * Bumps [epoch] and returns the new value. [connect] uses the returned
     * value directly rather than re-reading the field: a separate read leaves a
     * gap in which a concurrent close() could bump again unnoticed.
     */
    private fun teardown(): Int {
        val newEpoch = epoch.incrementAndGet()
        readJob?.cancel()
        readJob = null
        runCatching { socket?.close() }
        runCatching { serverSocket?.close() }
        socket = null
        serverSocket = null
        _connected.value = false
        return newEpoch
    }

    /**
     * Resolves once [device] is bonded, or definitively fails to. Already-bonded
     * devices return immediately with no broadcast round-trip. Callers bound
     * this with a timeout - a device stuck in BOND_BONDING would otherwise
     * suspend here forever.
     *
     * The receiver is registered BEFORE createBond(), so a broadcast fired the
     * instant pairing starts cannot be missed, and is torn down on every exit
     * including cancellation. Unregistering is wrapped because unregistering
     * twice throws, and a terminal broadcast can race the caller cancelling.
     */
    private suspend fun ensureBonded(device: BluetoothDevice): Boolean {
        if (device.bondState == BluetoothDevice.BOND_BONDED) return true

        return suspendCancellableCoroutine { cont ->
            val receiver = object : BroadcastReceiver() {
                override fun onReceive(ctx: Context, intent: Intent) {
                    if (intent.action != BluetoothDevice.ACTION_BOND_STATE_CHANGED) return
                    val changed = bondBroadcastDevice(intent) ?: return
                    if (changed.address != device.address) return
                    when (intent.getIntExtra(BluetoothDevice.EXTRA_BOND_STATE, BluetoothDevice.ERROR)) {
                        BluetoothDevice.BOND_BONDED -> {
                            runCatching { appContext.unregisterReceiver(this) }
                            if (cont.isActive) cont.resume(true)
                        }
                        BluetoothDevice.BOND_NONE -> {
                            runCatching { appContext.unregisterReceiver(this) }
                            if (cont.isActive) cont.resume(false)
                        }
                        // BOND_BONDING: pairing is in progress - keep waiting.
                    }
                }
            }

            val filter = IntentFilter(BluetoothDevice.ACTION_BOND_STATE_CHANGED)
            // RECEIVER_EXPORTED for the same reason BluetoothScanner needs it:
            // on Android 13+ the Bluetooth stack is a separate APEX app, so its
            // broadcasts are cross-app and a NOT_EXPORTED receiver silently
            // never gets them.
            ContextCompat.registerReceiver(
                appContext, receiver, filter, ContextCompat.RECEIVER_EXPORTED,
            )
            cont.invokeOnCancellation {
                runCatching { appContext.unregisterReceiver(receiver) }
            }

            when (device.bondState) {
                BluetoothDevice.BOND_NONE -> {
                    if (!device.createBond()) {
                        // Refused synchronously - no broadcast will follow for
                        // this call, so resolve now instead of waiting.
                        runCatching { appContext.unregisterReceiver(receiver) }
                        if (cont.isActive) cont.resume(false)
                    }
                }
                BluetoothDevice.BOND_BONDED -> {
                    // Bonded in the gap between the early check and
                    // registration; nothing more will arrive to resume this.
                    runCatching { appContext.unregisterReceiver(receiver) }
                    if (cont.isActive) cont.resume(true)
                }
                // BOND_BONDING: a bond is already underway and the receiver
                // above will catch its terminal broadcast.
            }
        }
    }

    /** API 31-32 lack the typed overload; API 33+ deprecates the untyped one. */
    @Suppress("DEPRECATION")
    private fun bondBroadcastDevice(intent: Intent): BluetoothDevice? =
        if (Build.VERSION.SDK_INT >= 33) {
            intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE, BluetoothDevice::class.java)
        } else {
            intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE)
        }

    /**
     * Insecure first, then reflection, then secure:
     *  1. `createInsecureRfcommSocketToServiceRecord` skips the MITM-protected
     *     handshake some stacks require, which is usually what gets through.
     *  2. Hidden `createRfcommSocket(1)` by reflection, for stacks where even
     *     the public insecure API is unreliable.
     *  3. The secure public API, as a last resort.
     *
     * A failure at any stage - socket creation or the blocking connect - falls
     * through to the next rather than aborting the attempt.
     */
    private fun openClientSocket(device: BluetoothDevice): BluetoothSocket {
        attempt { device.createInsecureRfcommSocketToServiceRecord(Config.SPP_UUID) }
            .getOrNull()?.let { return it }

        attempt {
            @Suppress("UNCHECKED_CAST")
            device.javaClass
                .getMethod("createRfcommSocket", Int::class.javaPrimitiveType)
                .invoke(device, 1) as BluetoothSocket
        }.getOrNull()?.let { return it }

        return attempt { device.createRfcommSocketToServiceRecord(Config.SPP_UUID) }.getOrThrow()
    }

    /** Creates and connects one candidate socket, closing it on any failure so
     *  the next fallback starts clean. */
    private fun attempt(create: () -> BluetoothSocket): Result<BluetoothSocket> {
        val s = runCatching(create).getOrElse { return Result.failure(it) }
        return runCatching { s.connect() }
            .map { s }
            .onFailure { runCatching { s.close() } }
    }

    /** Insecure listen first, secure as fallback - the insecure variant is the
     *  more forgiving one for an inbound connection too. */
    private fun openServerSocket(a: BluetoothAdapter): BluetoothServerSocket =
        runCatching { a.listenUsingInsecureRfcommWithServiceRecord("MDP-GRP11", Config.SPP_UUID) }
            .getOrElse { a.listenUsingRfcommWithServiceRecord("MDP-GRP11", Config.SPP_UUID) }

    /**
     * Blocking read loop. Runs until EOF, a fault, or a teardown closing the
     * socket underneath it. Every exit clears [connected] in `finally`, guarded
     * by an identity check: that pairing is what lets the repository start
     * reconnecting without the app having tried to send anything, while
     * stopping a stale reader from clearing a newer session's state.
     *
     * The child coroutine flushes an unterminated inbound line after
     * [Config.INBOUND_FLUSH_IDLE_MS] of silence, since AMD does not
     * newline-terminate what it sends. It cannot be done inline: `read()` is a
     * blocking native call with no timeout this class can set. A child of this
     * job rather than a sibling, so cancelling [readJob] cancels it too - and
     * cancelled explicitly as well, since a parent's `finally` does not wait
     * on its children.
     */
    private fun startReadLoop(s: BluetoothSocket) {
        readJob?.cancel()
        lastByteAtMs = System.currentTimeMillis()
        readJob = scope.launch {
            val flushJob = launch {
                while (isActive) {
                    delay(Config.INBOUND_FLUSH_IDLE_MS)
                    if (System.currentTimeMillis() - lastByteAtMs >= Config.INBOUND_FLUSH_IDLE_MS) {
                        framer.flushPending()?.let { _incoming.emit(it) }
                    }
                }
            }
            try {
                // Inside the try: getInputStream() throws on a torn-down fd,
                // and outside it that throw escapes a SupervisorJob-scoped
                // coroutine with no handler attached - process death, with
                // `connected` never cleared.
                val input = s.inputStream
                val buf = ByteArray(1024)
                while (true) {
                    val n = input.read(buf)
                    if (n < 0) break // EOF: peer closed cleanly
                    lastByteAtMs = System.currentTimeMillis()
                    framer.feed(buf, n).forEach { _incoming.emit(it) }
                }
            } catch (e: CancellationException) {
                throw e
            } catch (_: Throwable) {
                // Peer vanished, the socket was closed under a blocked read, or
                // an OEM stream threw something other than IOException once its
                // fd went away. The link is down either way, and none of these
                // may crash the process.
            } finally {
                flushJob.cancel()
                // Only the current session's reader may clear connected.
                if (socket === s) _connected.value = false
            }
        }
    }

    override suspend fun send(line: String): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            val out = socket?.outputStream ?: error("not connected")
            out.write((line + Config.OUTBOUND_TERMINATOR).toByteArray())
            out.flush()
        }
    }

    override fun close() {
        teardown()
        framer.reset()      // never let a half-line survive into the next session
    }
}
