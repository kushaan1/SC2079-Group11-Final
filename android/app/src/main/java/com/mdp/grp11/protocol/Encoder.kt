package com.mdp.grp11.protocol

import com.mdp.grp11.config.Config

/**
 * Formats follow the worked examples in MDP ARCM Briefing Slides.pdf.
 *
 * FACE additionally carries the coordinate: the checklist text requires "the
 * target face and obstacle coordinate", while the slide format omits it. We
 * send the superset. This must be agreed with the RPi parser owner.
 *
 * MOVEROBOT has no slide to follow - it is ours. Its coordinates are bare
 * rather than parenthesised because it mirrors the inbound ROBOT line it
 * answers, not the ADD line it sits beside, and they are decimal cells naming
 * the CENTRE of the robot, with the heading in degrees (0 = N, clockwise).
 *
 * Float.toString is locale-independent, unlike String.format - a decimal comma
 * would break every parser on the other end.
 *
 * SEND ARENA and the two run starts are JSON, written by hand. The values
 * are ints, floats, four fixed letters and tokens from Config, so there is
 * nothing to escape and nothing a library would add but a dependency and
 * formatting choices this test suite does not control. All are kept to one
 * line with no whitespace: the link frames on newlines, and a pretty-printed
 * object would arrive as a dozen unparseable fragments.
 */
fun encode(msg: Outbound): String = when (msg) {
    is Outbound.AddObstacle -> "ADD,B${msg.id},(${msg.x},${msg.y})"
    is Outbound.RemoveObstacle -> "SUB,B${msg.id}"
    is Outbound.SetFace -> "FACE,B${msg.id},(${msg.x},${msg.y}),${msg.face?.name ?: "NONE"}"
    is Outbound.Move -> msg.token
    is Outbound.MoveRobot -> "MOVEROBOT,${msg.x},${msg.y},${msg.headingDegrees}"
    is Outbound.SendArena -> """{"obstacles":${obstaclesJson(msg.obstacles)}}"""
    is Outbound.BeginImageRec ->
        """{"command":"${Config.taskTokens.imageRec}","algorithm":"${msg.algorithm}","robot":${robotJson(msg.robot)},"obstacles":${obstaclesJson(msg.obstacles)}}"""
    is Outbound.BeginFaceSearch ->
        """{"command":"${Config.taskTokens.faceSearch}","robot":${robotJson(msg.robot)},"obstacles":${obstaclesJson(msg.obstacles)}}"""
}

/** The obstacle array the JSON messages share, so they cannot drift apart. */
private fun obstaclesJson(obstacles: List<ObstacleEntry>): String =
    obstacles.joinToString(prefix = "[", separator = ",", postfix = "]") { o ->
        """{"id":${o.id},"x":${o.x},"y":${o.y},"face":"${o.face.name}"}"""
    }

/** The robot's pose as the run starts state it; same Float.toString as MOVEROBOT. */
private fun robotJson(robot: StartPose): String =
    """{"x":${robot.x},"y":${robot.y},"heading":${robot.headingDegrees}}"""
