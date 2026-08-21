package com.mdp.grp11.protocol

/**
 * Formats follow the worked examples in MDP ARCM Briefing Slides.pdf.
 *
 * FACE additionally carries the coordinate: the checklist text requires "the
 * target face and obstacle coordinate", while the slide format omits it. We
 * send the superset. This must be agreed with the RPi parser owner.
 */
fun encode(msg: Outbound): String = when (msg) {
    is Outbound.AddObstacle -> "ADD,B${msg.id},(${msg.x},${msg.y})"
    is Outbound.RemoveObstacle -> "SUB,B${msg.id}"
    is Outbound.SetFace -> "FACE,B${msg.id},(${msg.x},${msg.y}),${msg.face?.name ?: "NONE"}"
    is Outbound.Move -> msg.token
}
