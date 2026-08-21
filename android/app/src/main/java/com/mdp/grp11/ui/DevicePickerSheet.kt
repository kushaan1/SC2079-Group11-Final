package com.mdp.grp11.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.mdp.grp11.transport.DeviceInfo
import com.mdp.grp11.ui.theme.DmMono
import com.mdp.grp11.ui.theme.MdpTokens

/**
 * Scan, select, connect.
 *
 * Both link roles are offered, because they are not interchangeable: the RPi
 * runs `rfcomm listen` so the tablet connects OUT to it, while the AMD tool
 * connects IN and needs the tablet waiting.
 *
 * [permissionsGranted] and [adapterEnabled] are the two independent ways to
 * arrive at an empty list, and the platform reports neither as an error - it
 * just lists nothing. They need OPPOSITE actions from the operator (grant a
 * permission, turn the radio on, or go and pair a device), so collapsing them
 * into one "no paired devices" message sends them the wrong way.
 *
 * PAIRED and FOUND are separate sections because they behave differently on
 * tap: a paired device connects straight away, while an unpaired one has to
 * bond first, which puts the system pairing dialog on screen and can fail.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DevicePickerSheet(
    devices: List<DeviceInfo>,
    discovered: List<DeviceInfo>,
    scanning: Boolean,
    sightings: Int,
    permissionsGranted: Boolean,
    adapterEnabled: Boolean,
    onGrantPermissions: () -> Unit,
    onOpenAppSettings: () -> Unit,
    onEnableBluetooth: () -> Unit,
    onStartScan: () -> Unit,
    onStopScan: () -> Unit,
    onConnect: (DeviceInfo) -> Unit,
    onListen: () -> Unit,
    onDismiss: () -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(
            Modifier
                .padding(20.dp)
                // The sheet has both lists in it now and the tablet gives the
                // app ~700dp of height, so this can genuinely outgrow the
                // screen once a busy lab's worth of devices turns up. Bounded
                // and scrolling, so the WAIT FOR INCOMING button at the bottom
                // stays reachable.
                .heightIn(max = 520.dp)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text("CONNECT TO DEVICE", color = MdpTokens.Muted)

            when {
                !permissionsGranted -> {
                    Text(
                        "Bluetooth permission has not been granted, so no paired device can " +
                            "be listed."
                    )
                    MdpButton(
                        onClick = onGrantPermissions,
                        modifier = Modifier.fillMaxWidth().height(MdpTokens.TouchTarget),
                    ) { Text("GRANT BLUETOOTH PERMISSION") }
                    // Android stops showing the permission dialog after two
                    // denials, at which point the button above is silently a
                    // no-op and Settings is the only route left. Both are
                    // offered unconditionally rather than chosen between from
                    // `shouldShowRequestPermissionRationale` - this screen is
                    // reached precisely when nothing else is working.
                    MdpOutlinedButton(
                        onClick = onOpenAppSettings,
                        modifier = Modifier.fillMaxWidth().height(MdpTokens.TouchTarget),
                    ) { Text("OPEN APP SETTINGS") }
                }

                // Ordered before the empty check on purpose: a disabled radio
                // ALSO produces an empty list, and this is the cause the
                // operator can fix in one tap.
                !adapterEnabled -> {
                    Text("Bluetooth is off, so no paired device can be listed.")
                    MdpButton(
                        onClick = onEnableBluetooth,
                        modifier = Modifier.fillMaxWidth().height(MdpTokens.TouchTarget),
                    ) { Text("TURN ON BLUETOOTH") }
                }

                else -> {
                    DeviceSection(
                        title = "PAIRED",
                        devices = devices,
                        empty = "Nothing paired yet. Scan below, or pair in Android Settings.",
                        onConnect = onConnect,
                    )

                    HorizontalDivider()

                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            // The raw sighting count, not the list length.
                            // An empty FOUND list has several unrelated
                            // causes and they need opposite responses from
                            // the operator - see BluetoothScanner.sightings.
                            if (sightings > 0) "FOUND · $sightings seen" else "FOUND",
                            color = MdpTokens.Muted,
                            modifier = Modifier.weight(1f),
                        )
                        if (scanning) {
                            CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                        }
                        // One button that both starts and stops. A scan the
                        // operator cannot call off is a scan that keeps
                        // degrading the connect they are trying to make -
                        // discovery and RFCOMM contend for the same radio.
                        MdpOutlinedButton(
                            onClick = if (scanning) onStopScan else onStartScan,
                            modifier = Modifier.height(MdpTokens.TouchTarget),
                        ) { Text(if (scanning) "STOP" else "SCAN") }
                    }

                    DeviceSection(
                        title = null,
                        devices = discovered,
                        empty = if (scanning) {
                            "Scanning… devices appear here as they answer."
                        } else {
                            "Press SCAN to look for devices that are not paired yet."
                        },
                        onConnect = onConnect,
                    )
                }
            }

            HorizontalDivider()

            MdpOutlinedButton(
                onClick = onListen,
                // Listening needs the radio just as much as connecting out
                // does; without this the AMD route stays armed and fails with
                // an exception message instead of the one-tap fix above.
                enabled = permissionsGranted && adapterEnabled,
                modifier = Modifier.fillMaxWidth().height(MdpTokens.TouchTarget),
            ) { Text("WAIT FOR INCOMING (AMD)") }
        }
    }
}

@Composable
private fun DeviceSection(
    title: String?,
    devices: List<DeviceInfo>,
    empty: String,
    onConnect: (DeviceInfo) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        if (title != null) Text(title, color = MdpTokens.Muted)
        if (devices.isEmpty()) {
            Text(empty, color = MdpTokens.Muted)
        } else {
            devices.forEach { d ->
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f)) {
                        // A discovered device often has no name until the
                        // stack resolves one, in which case DeviceInfo carries
                        // the address in both fields - bounded so a long name
                        // cannot push CONNECT off the row.
                        Text(d.name, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(
                            d.address,
                            fontFamily = DmMono,
                            color = MdpTokens.Muted,
                            maxLines = 1,
                        )
                    }
                    MdpButton(
                        onClick = { onConnect(d) },
                        modifier = Modifier.height(MdpTokens.TouchTarget),
                    ) { Text("CONNECT") }
                }
            }
        }
    }
}
