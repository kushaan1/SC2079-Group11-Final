package com.mdp.grp11.arena

import com.mdp.grp11.config.Config
import com.mdp.grp11.protocol.Face

data class Cell(val x: Int, val y: Int)

/** What the ROBOT reported (C.9). Distinct from Obstacle.imageFace. */
data class Target(val id: Int, val face: Face?)

data class Obstacle(
    val id: Int,
    val cell: Cell,
    /** What WE annotated (C.7), outbound. */
    val imageFace: Face? = null,
    /** What the ROBOT reported (C.9), inbound. */
    val target: Target? = null,
)

data class RobotPose(val cell: Cell, val heading: Face)

data class Arena(
    val obstacles: List<Obstacle> = emptyList(),
    val robot: RobotPose? = null,
) {

    fun obstacle(id: Int): Obstacle? = obstacles.firstOrNull { it.id == id }

    /** Lowest unused id in 1..MAX, or null when the pool is exhausted. */
    fun nextFreeId(): Int? =
        (1..Config.MAX_OBSTACLES).firstOrNull { id -> obstacles.none { it.id == id } }

    fun canOccupy(cell: Cell, ignoreId: Int?): Boolean {
        if (!inBounds(cell)) return false
        if (cell.x < Config.START_ZONE_CELLS && cell.y < Config.START_ZONE_CELLS) return false
        return obstacles.none { it.id != ignoreId && it.cell == cell }
    }

    /** Returns the new arena and the placed obstacle, or (this, null) if refused. */
    fun place(cell: Cell): Pair<Arena, Obstacle?> {
        if (!canOccupy(cell, null)) return this to null
        val id = nextFreeId() ?: return this to null
        val o = Obstacle(id = id, cell = cell)
        return copy(obstacles = obstacles + o) to o
    }

    fun move(id: Int, cell: Cell): Arena {
        val existing = obstacle(id) ?: return this
        if (existing.cell == cell) return this
        if (!canOccupy(cell, id)) return this
        return copy(obstacles = obstacles.map { if (it.id == id) it.copy(cell = cell) else it })
    }

    fun remove(id: Int): Arena = copy(obstacles = obstacles.filterNot { it.id == id })

    fun setFace(id: Int, face: Face?): Arena {
        obstacle(id) ?: return this
        return copy(obstacles = obstacles.map { if (it.id == id) it.copy(imageFace = face) else it })
    }

    /** Inbound TARGET. Unknown obstacle is ignored, never auto-created. */
    fun applyTarget(id: Int, targetId: Int, face: Face?): Arena {
        obstacle(id) ?: return this
        return copy(
            obstacles = obstacles.map {
                if (it.id == id) it.copy(target = Target(targetId, face)) else it
            }
        )
    }

    /** Inbound ROBOT. Out-of-range coordinates are ignored, never clamped. */
    fun applyPose(x: Int, y: Int, heading: Face): Arena {
        val cell = Cell(x, y)
        if (!inBounds(cell)) return this
        return copy(robot = RobotPose(cell, heading))
    }

    private fun inBounds(cell: Cell) =
        cell.x in 0 until Config.CELLS && cell.y in 0 until Config.CELLS
}
