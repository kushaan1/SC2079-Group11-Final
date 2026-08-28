package com.mdp.grp11.protocol

sealed interface Inbound {
    data class Status(val text: String) : Inbound
    data class TargetFound(val obstacle: Int, val targetId: Int, val face: Face?) : Inbound
    /** Centre of the robot's footprint in arena cells; heading 0 = N, clockwise. */
    data class Pose(val x: Float, val y: Float, val headingDegrees: Float) : Inbound
    data class Unknown(val raw: String) : Inbound
}

sealed interface Outbound {
    data class AddObstacle(val id: Int, val x: Int, val y: Int) : Outbound
    data class RemoveObstacle(val id: Int) : Outbound
    data class SetFace(val id: Int, val x: Int, val y: Int, val face: Face?) : Outbound
    data class Move(val token: String) : Outbound

    /**
     * The operator repositioning the robot on the tablet. Named apart from
     * inbound [Inbound.Pose]'s `ROBOT` on purpose: one name in both directions
     * would echo back on any RPi that re-broadcasts what it receives, and the
     * two would then be indistinguishable in the log.
     */
    data class MoveRobot(val x: Float, val y: Float, val headingDegrees: Float) : Outbound
}
