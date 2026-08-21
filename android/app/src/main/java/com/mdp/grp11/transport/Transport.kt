package com.mdp.grp11.transport

import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.StateFlow

data class DeviceInfo(val name: String, val address: String)

sealed interface ConnectTarget {
    /** Connect out, as the RPi expects (it runs `rfcomm listen`). */
    data class Client(val device: DeviceInfo) : ConnectTarget

    /** Accept an incoming connection, as the AMD tool expects. */
    data object Listen : ConnectTarget
}

/**
 * A framed, line-oriented link. Implementations emit only COMPLETE lines.
 */
interface Transport {
    val incoming: Flow<String>

    /** True while the link is up. The only way a caller can learn the peer vanished
     *  without having tried to send or receive anything. */
    val connected: StateFlow<Boolean>
    suspend fun connect(target: ConnectTarget): Result<DeviceInfo>
    suspend fun send(line: String): Result<Unit>
    fun close()
}
