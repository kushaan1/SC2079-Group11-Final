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

    /**
     * The whole layout in one line, for SEND ARENA. The only message that is
     * JSON rather than comma fields: the RPi hands it to the planner as-is.
     *
     * Every entry carries a face. That is the caller's promise, not this
     * type's check - the ViewModel refuses to build one while a block is
     * unfaced, and says so to the operator, because a planner given half a
     * layout plans half a run.
     */
    data class SendArena(val obstacles: List<ObstacleEntry>) : Outbound

    /**
     * Start the image-recognition run: which planner, and the whole layout
     * it is to plan over, in one line. Replaces a bare start token so the
     * RPi never has to pair a "go" with a layout it received earlier.
     *
     * [algorithm] is already the wire spelling (see `Config.algorithmTokens`);
     * the protocol layer does not know the session-level enum. Same promise
     * as [SendArena] about faces: every entry has one, or this is not built.
     */
    data class BeginImageRec(val algorithm: String, val obstacles: List<ObstacleEntry>) : Outbound
}

/** One obstacle as SEND ARENA states it: id, cell, and the face carrying the image. */
data class ObstacleEntry(val id: Int, val x: Int, val y: Int, val face: Face)
