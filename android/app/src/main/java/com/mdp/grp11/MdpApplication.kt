package com.mdp.grp11

import android.app.Application
import android.os.SystemClock
import com.mdp.grp11.arena.ArenaStore
import com.mdp.grp11.arena.PreferencesArenaStore
import com.mdp.grp11.connection.ConnectionRepository
import com.mdp.grp11.session.RunTimer
import com.mdp.grp11.transport.BluetoothScanner
import com.mdp.grp11.transport.BluetoothSppTransport
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob

/**
 * Application-scoped so the connection, the arena and the run clocks outlive
 * every ViewModel: a rotation or a reconnect must not lose the course you just
 * laid out, or the time already banked against a scored run.
 */
class MdpApplication : Application() {

    /**
     * `Dispatchers.Main.immediate`, NOT `Dispatchers.IO`.
     * [ConnectionRepository]'s job handles and generation counters are plain,
     * non-`@Volatile` vars: sound under a single-threaded confined dispatcher
     * and unsound under a multi-threaded one, where IO would silently reopen
     * races no test here could catch. Nothing needs IO anyway -
     * [BluetoothSppTransport] wraps its own blocking calls in it.
     */
    lateinit var appScope: CoroutineScope
        private set

    lateinit var transport: BluetoothSppTransport
        private set

    lateinit var connection: ConnectionRepository
        private set

    /**
     * Device discovery. Application-scoped like the transport, so a scan
     * survives a rotation and the receiver it registers is owned by something
     * that outlives the Activity. Separate from [transport] on purpose - see
     * [BluetoothScanner].
     */
    lateinit var scanner: BluetoothScanner
        private set

    lateinit var arenaStore: ArenaStore
        private set

    /**
     * Held here rather than per-ViewModel so a scored clock survives the
     * ViewModel being cleared and rebuilt. `ArenaViewModel` resumes ticking
     * at construction when it finds a run already in progress - see its `init`.
     */
    lateinit var runTimer: RunTimer
        private set

    override fun onCreate() {
        super.onCreate()
        appScope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
        transport = BluetoothSppTransport(this)
        scanner = BluetoothScanner(this)
        connection = ConnectionRepository(transport, appScope)
        arenaStore = PreferencesArenaStore(this)
        // elapsedRealtime(), NOT currentTimeMillis(). Wall-clock time jumps
        // backwards on an NTP correction, and RunTimer folds each reading into
        // a banked total - so one jump corrupts that total for the rest of the
        // session. elapsedRealtime() is monotonic since boot and counts through
        // deep sleep, which is what a run timer needs.
        runTimer = RunTimer { SystemClock.elapsedRealtime() }
    }
}
