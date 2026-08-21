package com.mdp.grp11.protocol

sealed interface Inbound {
    data class Status(val text: String) : Inbound
    data class TargetFound(val obstacle: Int, val targetId: Int, val face: Face?) : Inbound
    data class Pose(val x: Int, val y: Int, val heading: Face) : Inbound
    data class Unknown(val raw: String) : Inbound
}

sealed interface Outbound {
    data class AddObstacle(val id: Int, val x: Int, val y: Int) : Outbound
    data class RemoveObstacle(val id: Int) : Outbound
    data class SetFace(val id: Int, val x: Int, val y: Int, val face: Face?) : Outbound
    data class Move(val token: String) : Outbound
}
