package com.mdp.grp11.arena

import com.mdp.grp11.config.Config
import com.mdp.grp11.protocol.Face

private val VERSION = Config.ARENA_FORMAT_VERSION
private val ABSENT = Config.ARENA_FIELD_ABSENT

/**
 * Line-based and human-readable, so a broken save can be diagnosed by eye.
 *
 * Arena coordinates are persisted as-is: this model's origin is bottom-left
 * with y increasing upward, and there is no y-flip here. The only y-inversion
 * in this project belongs to rendering (see Grid.kt) and never touches
 * persisted or wire data.
 */
fun encodeArena(arena: Arena): String = buildString {
    appendLine(VERSION)
    arena.robot?.let { appendLine("R ${it.cell.x} ${it.cell.y} ${it.heading.name}") }
    arena.obstacles.sortedBy { it.id }.forEach { o ->
        append("O ${o.id} ${o.cell.x} ${o.cell.y} ")
        append(o.imageFace?.name ?: ABSENT)
        append(" ")
        append(o.target?.id?.toString() ?: ABSENT)
        append(" ")
        appendLine(o.target?.face?.name ?: ABSENT)
    }
}

/**
 * Total: any malformed input returns null rather than throwing. The input is
 * persisted text that may come from an older app version, a crash mid-write,
 * or hand editing, so every field is validated before use.
 */
fun decodeArena(text: String): Arena? {
    val lines = text.lines().map { it.trim() }.filter { it.isNotEmpty() }
    if (lines.isEmpty() || lines[0] != VERSION) return null

    var robot: RobotPose? = null
    val obstacles = mutableListOf<Obstacle>()
    val seenIds = mutableSetOf<Int>()

    for (line in lines.drop(1)) {
        val f = line.split(" ").filter { it.isNotEmpty() }
        when (f.getOrNull(0)) {
            "R" -> {
                if (f.size != 4) return null
                val x = f[1].toIntOrNull() ?: return null
                val y = f[2].toIntOrNull() ?: return null
                val h = Face.parse(f[3]) ?: return null
                robot = RobotPose(Cell(x, y), h)
            }
            "O" -> {
                if (f.size != 7) return null
                val id = f[1].toIntOrNull() ?: return null
                // Ids come from a fixed pool (Arena.nextFreeId(): 1..MAX_OBSTACLES).
                // A decoded arena must not contain duplicates or ids outside it.
                if (id !in 1..Config.MAX_OBSTACLES) return null
                if (!seenIds.add(id)) return null
                val x = f[2].toIntOrNull() ?: return null
                val y = f[3].toIntOrNull() ?: return null
                val imageFace = if (f[4] == ABSENT) null else Face.parse(f[4]) ?: return null
                val targetId = if (f[5] == ABSENT) null else f[5].toIntOrNull() ?: return null
                val targetFace = if (f[6] == ABSENT) null else Face.parse(f[6]) ?: return null
                obstacles += Obstacle(
                    id = id,
                    cell = Cell(x, y),
                    imageFace = imageFace,
                    target = targetId?.let { Target(it, targetFace) },
                )
            }
            else -> return null
        }
    }
    return Arena(obstacles = obstacles, robot = robot)
}
