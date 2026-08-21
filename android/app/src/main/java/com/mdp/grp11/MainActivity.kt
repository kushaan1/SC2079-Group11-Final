package com.mdp.grp11

import android.bluetooth.BluetoothAdapter
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.core.content.ContextCompat
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.mdp.grp11.config.Config
import com.mdp.grp11.transport.ConnectTarget
import com.mdp.grp11.transport.DeviceInfo
import com.mdp.grp11.ui.ArenaViewModel
import com.mdp.grp11.ui.DevicePickerSheet
import com.mdp.grp11.ui.MainScreen
import com.mdp.grp11.ui.theme.MdpTheme
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {

    /**
     * Snapshot state rather than a plain flag so the picker re-renders the
     * moment the grant lands - the sheet may well be open when the operator
     * answers the system prompt.
     */
    private val bluetoothPermissionsGranted = mutableStateOf(false)

    /**
     * Whether the radio is on. Snapshot state for the same reason as the
     * permission flag: the operator can turn Bluetooth on from the system
     * dialog while the sheet is open, and the sheet has to notice.
     */
    private val bluetoothEnabled = mutableStateOf(false)

    /**
     * The last target the operator deliberately chose, so RETRY can repeat it
     * in one tap. Held here rather than read from the repository, whose own
     * `lastTarget` is also written by automatic reconnects and so is not a
     * record of what the operator asked for.
     */
    private var lastTarget: ConnectTarget? = null

    private val requestBluetoothPermissions = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { refreshBluetoothState() }

    /**
     * The system's "allow this app to turn on Bluetooth?" dialog. Its result
     * code is deliberately ignored in favour of re-reading the adapter: the
     * operator can decline here and then enable the radio from the quick
     * settings shade instead, and a RESULT_CANCELED would claim otherwise.
     */
    private val requestEnableBluetooth = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { refreshBluetoothState() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Opted into on every version so the layout behaves identically here
        // and on Android 15+, where it is mandatory. MainScreen pads itself
        // back out of the bars.
        enableEdgeToEdge()
        val app = application as MdpApplication

        refreshBluetoothState()
        if (!bluetoothPermissionsGranted.value) {
            requestBluetoothPermissions.launch(Config.BLUETOOTH_PERMISSIONS.toTypedArray())
        }

        // Through a ViewModelProvider, not constructed inline: the arena and
        // the run clocks must survive any configuration change the activity
        // does not handle itself, and onCleared() (which stops the run-timer
        // tick job) only ever runs for a ViewModel the store owns.
        val vm = ViewModelProvider(
            this,
            viewModelFactory {
                initializer {
                    ArenaViewModel(app.connection, app.appScope, app.runTimer, app.arenaStore)
                }
            },
        )[ArenaViewModel::class.java]

        setContent {
            MdpTheme {
                val granted by bluetoothPermissionsGranted
                val adapterOn by bluetoothEnabled
                val state by app.connection.state.collectAsState()
                var showPicker by remember { mutableStateOf(false) }
                var devices by remember { mutableStateOf(emptyList<DeviceInfo>()) }

                // Listed when the sheet opens, and again if the permission is
                // granted or the radio turned on while it is open. Never
                // before: bondedDevices() reaches the adapter, which throws
                // without BLUETOOTH_CONNECT. `adapterOn` is a key and not just
                // a guard - a list gathered with the radio off is empty, and
                // nothing else would re-gather it.
                LaunchedEffect(showPicker, granted, adapterOn) {
                    devices = if (showPicker && granted && adapterOn) {
                        app.transport.bondedDevices()
                    } else {
                        emptyList()
                    }
                }

                val discovered by app.scanner.found.collectAsState()
                val scanning by app.scanner.scanning.collectAsState()
                val sightings by app.scanner.sightings.collectAsState()

                // A scan must not outlive the sheet: discovery contends with
                // RFCOMM for the radio, so one left running behind a closed
                // sheet degrades the very connection the operator closed it to
                // make. DisposableEffect rather than the dismiss handler,
                // because the sheet also goes away when the Activity does.
                if (showPicker) {
                    DisposableEffect(Unit) { onDispose { app.scanner.stop() } }
                }

                // Paints the theme background across the whole window, which
                // now includes the strips behind the system bars. Without it
                // those strips fall back to the platform theme's own window
                // background rather than the app's.
                Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                    MainScreen(
                        vm = vm,
                        state = state,
                        onOpenPicker = { showPicker = true },
                        // Falls back to the picker when there is nothing to
                        // repeat, so RETRY always leads somewhere.
                        onRetry = { lastTarget?.let(::connect) ?: run { showPicker = true } },
                    )
                }

                if (showPicker) {
                    DevicePickerSheet(
                        devices = devices,
                        // A scan re-finds paired devices too, and listing one
                        // twice with two different-looking outcomes is the
                        // confusion the split sections exist to avoid.
                        discovered = discovered.filterNot { d ->
                            devices.any { it.address == d.address }
                        },
                        scanning = scanning,
                        sightings = sightings,
                        permissionsGranted = granted,
                        adapterEnabled = adapterOn,
                        onGrantPermissions = {
                            requestBluetoothPermissions.launch(
                                Config.BLUETOOTH_PERMISSIONS.toTypedArray()
                            )
                        },
                        onOpenAppSettings = ::openAppSettings,
                        onEnableBluetooth = {
                            requestEnableBluetooth.launch(
                                Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE)
                            )
                        },
                        onStartScan = {
                            if (!app.scanner.start()) {
                                // start() only refuses for a reason the
                                // operator can act on, and this flips the
                                // sheet to the branch that says so.
                                refreshBluetoothState()
                            }
                        },
                        onStopScan = { app.scanner.stop() },
                        onConnect = { d ->
                            // Before connect(), not after: an active discovery
                            // measurably degrades an RFCOMM connect, and the
                            // one being started here is the one that matters.
                            app.scanner.stop()
                            showPicker = false
                            connect(ConnectTarget.Client(d))
                        },
                        onListen = {
                            app.scanner.stop()
                            showPicker = false
                            connect(ConnectTarget.Listen)
                        },
                        onDismiss = { showPicker = false },
                    )
                }
            }
        }
    }

    /**
     * Re-checked here because a permanently denied permission is granted from
     * system Settings instead, which never routes back through the launcher's
     * own callback - without this the picker would keep claiming the
     * permission is missing until the app was restarted.
     */
    override fun onResume() {
        super.onResume()
        refreshBluetoothState()
    }

    /**
     * Both gates in one place, refreshed together: the permission and the radio
     * are the two independent reasons the picker can have nothing to show, and
     * every route that changes either one comes back through here.
     *
     * The adapter is only readable with BLUETOOTH_CONNECT, so it is read after
     * the permission check and reported as off without it.
     */
    private fun refreshBluetoothState() {
        bluetoothPermissionsGranted.value = hasBluetoothPermissions()
        bluetoothEnabled.value = bluetoothPermissionsGranted.value &&
            (application as MdpApplication).transport.isAdapterEnabled()
    }

    /**
     * On the application scope, never `lifecycleScope`: a socket connect can
     * block for seconds, and an Activity torn down in that window would cancel
     * the attempt mid-flight and leave the repository nothing to publish.
     */
    private fun connect(target: ConnectTarget) {
        val app = application as MdpApplication
        lastTarget = target
        app.appScope.launch { app.connection.connect(target) }
    }

    /**
     * The only route left once Android stops showing the permission dialog,
     * which it does after two denials - from then on the launcher returns
     * immediately having displayed nothing. [onResume] picks up whatever
     * changes while the operator is in Settings.
     */
    private fun openAppSettings() {
        startActivity(
            Intent(
                Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                Uri.fromParts("package", packageName, null),
            )
        )
    }

    private fun hasBluetoothPermissions(): Boolean =
        Config.BLUETOOTH_PERMISSIONS.all {
            ContextCompat.checkSelfPermission(this, it) == PackageManager.PERMISSION_GRANTED
        }
}
