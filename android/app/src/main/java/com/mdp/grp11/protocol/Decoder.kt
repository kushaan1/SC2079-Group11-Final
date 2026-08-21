package com.mdp.grp11.protocol

/**
 * Total function: every input produces an Inbound, and it never throws.
 *
 * A parser exception on the I/O coroutine would kill the read loop, which from
 * the UI is indistinguishable from a disconnect. Worst case is Unknown.
 *
 * Tolerances exist because the two source documents disagree:
 *  - the checklist writes "TARGET, <n>, <id>" with spaces
 *  - the slides write obstacle ids as "B2", the checklist as a bare number
 *  - the 4-argument TARGET form appears only in the slides
 *  - the checklist's own example uses target id 4, outside the 11-40 pool,
 *    so target ids are NEVER range-checked
 */
fun decode(line: String): Inbound {
    val raw = line.trim()
    if (raw.isEmpty()) return Inbound.Unknown(line)

    val parts = raw.split(',').map { it.trim() }
    val verb = parts[0].uppercase()

    return when (verb) {
        "MSG" -> decodeStatus(raw, line)
        "TARGET" -> decodeTarget(parts, line)
        "ROBOT" -> decodePose(parts, line)
        else -> Inbound.Unknown(line)
    }
}

private fun decodeStatus(raw: String, original: String): Inbound {
    val body = raw.substringAfter(',', missingDelimiterValue = "").trim()
    if (body.isEmpty()) return Inbound.Unknown(original)
    val inner = body.substringAfter('[', "").substringBeforeLast(']', "")
    return Inbound.Status(if (inner.isNotEmpty()) inner else body)
}

private fun decodeTarget(parts: List<String>, original: String): Inbound {
    if (parts.size !in 3..4) return Inbound.Unknown(original)
    val obstacle = obstacleId(parts[1]) ?: return Inbound.Unknown(original)
    val targetId = parts[2].toIntOrNull() ?: return Inbound.Unknown(original)
    val face = if (parts.size == 4) {
        Face.parse(parts[3]) ?: return Inbound.Unknown(original)
    } else null
    return Inbound.TargetFound(obstacle, targetId, face)
}

private fun decodePose(parts: List<String>, original: String): Inbound {
    if (parts.size != 4) return Inbound.Unknown(original)
    val x = parts[1].toIntOrNull() ?: return Inbound.Unknown(original)
    val y = parts[2].toIntOrNull() ?: return Inbound.Unknown(original)
    val heading = Face.parse(parts[3]) ?: return Inbound.Unknown(original)
    return Inbound.Pose(x, y, heading)
}

/** Accepts "B2" or "2". */
private fun obstacleId(token: String): Int? =
    token.trim().removePrefix("B").removePrefix("b").toIntOrNull()
