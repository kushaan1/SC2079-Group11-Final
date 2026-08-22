package com.mdp.grp11.transport

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import android.os.Handler
import android.os.Looper
import androidx.core.content.ContextCompat
import com.mdp.grp11.config.Config
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Bluetooth Classic device discovery.
 *
 * Separate from [BluetoothSppTransport] by design: discovery needs the adapter
 * and a Context and shares no socket, epoch, read loop or connection state with
 * it, so a bug in here cannot reach the connect path - the worst it can do is
 * show a wrong list.
 *
 * The one real interaction runs the other way: an active discovery degrades an
 * RFCOMM connect, so [BluetoothSppTransport.connect] calls `cancelDiscovery()`
 * on the adapter, which stops a scan this class started without either class
 * knowing about the other.
 *
 * Nothing here bonds, connects or transmits. Producing the list is the job.
 */
@SuppressLint("MissingPermission")   // callers gate on BLUETOOTH_SCAN / _CONNECT
class BluetoothScanner(context: Context) {

    // Application context: a receiver registered against an Activity outlives
    // it if anything goes wrong on the unregister path.
    private val appContext: Context = context.applicationContext

    private val adapter: BluetoothAdapter? =
        context.getSystemService(BluetoothManager::class.java)?.adapter

    private val _scanning = MutableStateFlow(false)

    /** True from the moment a scan is asked for until the adapter says it finished. */
    val scanning: StateFlow<Boolean> = _scanning.asStateFlow()

    private val _found = MutableStateFlow<List<DeviceInfo>>(emptyList())

    /**
     * Devices seen by the current scan, in the order they appeared - roughly
     * signal strength, which is useful ordering for an operator looking for the
     * robot a metre away. Survives [stop] so results stay tappable once
     * scanning ends; only [start] and [clear] empty it.
     */
    val found: StateFlow<List<DeviceInfo>> = _found.asStateFlow()

    private val _sightings = MutableStateFlow(0)

    /**
     * Raw `ACTION_FOUND` broadcasts, counted before de-duplication and before
     * the picker hides already-paired devices. Diagnostic: an empty FOUND list
     * has several unrelated causes and this number separates them.
     *  - 0 for the full scan: nothing nearby is DISCOVERABLE. Classic discovery
     *    only reports devices in pairing mode, so an idle laptop is invisible.
     *    Common, and not a fault.
     *  - 0 with the spinner gone at once: discovery never started.
     *  - non-zero with an empty list: everything seen was already paired.
     */
    val sightings: StateFlow<Int> = _sightings.asStateFlow()

    /** Held so [stop] unregisters exactly the instance it registered. */
    private var receiver: BroadcastReceiver? = null

    /**
     * True only between a `startDiscovery()` that returned true and the
     * teardown of that scan.
     *
     * `cancelDiscovery()` is ASYNCHRONOUS: [start] cancels any running
     * discovery before starting its own, and that cancel's
     * ACTION_DISCOVERY_FINISHED lands milliseconds later, after this receiver
     * is registered. Without this flag, the handler reads that stale broadcast
     * as "our scan ended" and tears down the scan it just started.
     */
    private var started = false

    /**
     * Ends a scan the platform never told us had ended. On the main looper,
     * where onReceive also runs, so the two cannot race into [stop].
     */
    private val watchdog = Handler(Looper.getMainLooper())
    private val endScan = Runnable { stop() }

    /**
     * Starts a scan, replacing any previous results.
     *
     * Returns false when there is no adapter or the radio is off, so the caller
     * can say which rather than showing a list that stays empty for a reason
     * the operator cannot guess.
     */
    fun start(): Boolean {
        val a = adapter ?: return false
        if (!a.isEnabled) return false

        // Idempotent: a second tap on SCAN restarts cleanly rather than
        // stacking a second receiver on the first.
        stop()
        _found.value = emptyList()
        _sightings.value = 0

        val filter = IntentFilter().apply {
            addAction(BluetoothDevice.ACTION_FOUND)
            addAction(BluetoothAdapter.ACTION_DISCOVERY_FINISHED)
        }
        val r = object : BroadcastReceiver() {
            override fun onReceive(ctx: Context, intent: Intent) {
                when (intent.action) {
                    BluetoothDevice.ACTION_FOUND -> {
                        // Counted first, before every reason a sighting might
                        // not reach the list - that is what makes it diagnostic.
                        _sightings.value = _sightings.value + 1
                        val device = broadcastDevice(intent) ?: return
                        val address = device.address ?: return
                        // Keyed on address, never name: a name can be null,
                        // duplicated, or arrive later than the first sighting.
                        if (_found.value.any { it.address == address }) return
                        _found.value = _found.value + DeviceInfo(device.name ?: address, address)
                    }
                    // Driving `scanning` off the adapter's own end-of-scan means
                    // the spinner stops exactly when the platform stopped,
                    // including when something else cancelled the discovery.
                    BluetoothAdapter.ACTION_DISCOVERY_FINISHED -> if (started) stop()
                }
            }
        }

        // RECEIVER_EXPORTED is load-bearing. On Android 13+ the Bluetooth stack
        // runs as its own APEX app, so ACTION_FOUND and ACTION_DISCOVERY_FINISHED
        // arrive as CROSS-APP broadcasts and a NOT_EXPORTED receiver is never
        // handed them. The failure is silent: registration succeeds,
        // startDiscovery() returns true, the radio scans, and this class hears
        // nothing - no devices ever appear AND the spinner never stops.
        ContextCompat.registerReceiver(appContext, r, filter, ContextCompat.RECEIVER_EXPORTED)
        receiver = r

        // Published before asking the adapter, so the stop() below finds the
        // state it is meant to clear if startDiscovery() fails.
        _scanning.value = true

        // startDiscovery() refuses while a discovery is still running, and the
        // cancel above is asynchronous - so a second press of SCAN would fail
        // silently. Retried once against the adapter's own `isDiscovering`,
        // which is the state that actually gates the call.
        var ok = a.startDiscovery()
        if (!ok && !a.isDiscovering) ok = a.startDiscovery()
        if (!ok) {
            stop()
            return false
        }
        started = true
        watchdog.postDelayed(endScan, Config.DISCOVERY_TIMEOUT_MS)
        return true
    }

    /**
     * Ends the scan and unregisters. Safe when nothing is running and safe
     * twice - the finish broadcast and the operator closing the sheet race each
     * other by design. Unregistering is wrapped because unregistering a
     * receiver that is already gone throws.
     */
    fun stop() {
        watchdog.removeCallbacks(endScan)
        started = false
        receiver?.let { runCatching { appContext.unregisterReceiver(it) } }
        receiver = null
        // Guarded so this cannot interfere with a discovery something else started.
        adapter?.let { if (it.isDiscovering) runCatching { it.cancelDiscovery() } }
        _scanning.value = false
    }

    /** Drops the results without touching a running scan. */
    fun clear() {
        _found.value = emptyList()
    }

    private fun broadcastDevice(intent: Intent): BluetoothDevice? =
        if (Build.VERSION.SDK_INT >= 33) {
            intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE, BluetoothDevice::class.java)
        } else {
            @Suppress("DEPRECATION")
            intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE)
        }
}
