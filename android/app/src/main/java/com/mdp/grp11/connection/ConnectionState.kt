package com.mdp.grp11.connection

import com.mdp.grp11.transport.DeviceInfo

sealed interface ConnectionState {
    data object Idle : ConnectionState
    data class Connecting(val device: DeviceInfo?) : ConnectionState
    data class Connected(val device: DeviceInfo) : ConnectionState
    data class Reconnecting(val device: DeviceInfo?, val attempt: Int) : ConnectionState
    data class Failed(val reason: String) : ConnectionState
}
