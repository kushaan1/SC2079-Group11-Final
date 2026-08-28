package com.mdp.grp11.protocol

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
 */
fun encode(msg: Outbound): String = when (msg) {
    is Outbound.AddObstacle -> "ADD,B${msg.id},(${msg.x},${msg.y})"
    is Outbound.RemoveObstacle -> "SUB,B${msg.id}"
    is Outbound.SetFace -> "FACE,B${msg.id},(${msg.x},${msg.y}),${msg.face?.name ?: "NONE"}"
    is Outbound.Move -> msg.token
    is Outbound.MoveRobot -> "MOVEROBOT,${msg.x},${msg.y},${msg.headingDegrees}"
}
