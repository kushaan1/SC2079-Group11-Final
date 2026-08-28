package com.mdp.grp11.arena

import com.mdp.grp11.config.Config
import com.mdp.grp11.protocol.Face
import com.mdp.grp11.protocol.normaliseDegrees

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

/**
 * Where the robot is and which way it points, both CONTINUOUS.
 *
 * [x] and [y] are the CELL its footprint is centred on, in the same units an
 * obstacle's coordinate uses - `5` means cell 5 for both - except that decimals
 * are allowed and interpolate between cell centres. The centre rather than a
 * corner because an Ackermann car arcs to arbitrary poses, and a corner anchor
 * would move the drawn body every time the heading changed.
 *
 * [headingDegrees] is 0 = north, increasing clockwise, normalised to [0,360).
 * Four cardinal letters cannot describe a car mid-arc; [Face.degrees] converts
 * the operator's compass keys into this.
 */
data class RobotPose(val x: Float, val y: Float, val headingDegrees: Float)

/** Where a fresh arena, a reset and a robot-less saved layout all start. */
val START_POSE = RobotPose(
    Config.ROBOT_START_X,
    Config.ROBOT_START_Y,
    Config.ROBOT_START_HEADING,
)

data class Arena(
    val obstacles: List<Obstacle> = emptyList(),
    /**
     * Never absent. The robot is a physical object that exists whether or not
     * it has reported in, so the operator always has something to drag - and
     * every reader is spared a null branch that could only mean "not heard
     * from yet".
     */
    val robot: RobotPose = START_POSE,
) {

    fun obstacle(id: Int): Obstacle? = obstacles.firstOrNull { it.id == id }

    /** Lowest unused id in 1..MAX, or null when the pool is exhausted. */
    fun nextFreeId(): Int? =
        (1..Config.MAX_OBSTACLES).firstOrNull { id -> obstacles.none { it.id == id } }

    fun canOccupy(cell: Cell, ignoreId: Int?): Boolean {
        if (!inBounds(cell)) return false
        if (cell.x < Config.TASK1_START_ZONE_CELLS && cell.y < Config.TASK1_START_ZONE_CELLS) return false
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

    /**
     * Inbound ROBOT. Out-of-range coordinates are ignored, never clamped: a
     * clamped position looks plausible and would be wrong, where an unmoved
     * robot is obviously wrong, which is the point.
     *
     * The footprint is NOT checked, only the centre - a robot genuinely
     * hanging off the edge is drawn hanging off the edge. What the robot
     * reports is shown as reported. [moveRobot], where the tablet is the
     * author rather than the audience, clamps instead.
     */
    fun applyPose(x: Float, y: Float, headingDegrees: Float): Arena {
        if (!centreInBounds(x, y)) return this
        return copy(robot = RobotPose(x, y, normaliseDegrees(headingDegrees)))
    }

    /**
     * The operator dragging the robot, in continuous cells. CLAMPED, not
     * refused - a finger dragged past the edge leaves the robot against the
     * wall the way a real one would stop against it, and the centre is held
     * half a footprint clear of each edge.
     *
     * That keeps the AXIS-ALIGNED footprint on the board. The body is drawn
     * rotated, so at a diagonal heading its corners reach further than the
     * margin allows for and can overhang. Left alone deliberately:
     * a real car nosed into a corner at an angle overhangs too, and clamping
     * for the worst case would stop it short of walls it can actually reach.
     *
     * No obstacle-collision check, unlike [canOccupy]. Obstacles are a layout
     * being authored, so where they may go is the app's business; the robot is
     * a physical object whose position is being stated.
     */
    fun moveRobot(x: Float, y: Float): Arena {
        // How many cells the centre must stay in from the outermost cell for
        // the whole footprint to fit: 1 for a 3-cell robot, giving 1..18.
        val margin = (Config.ROBOT_SIZE_CELLS - 1) / 2f
        val last = Config.CELLS - 1 - margin
        val cx = x.coerceIn(margin, last)
        val cy = y.coerceIn(margin, last)
        if (cx == robot.x && cy == robot.y) return this
        return copy(robot = robot.copy(x = cx, y = cy))
    }

    /** The operator setting the heading. Never clears it - a robot always faces somewhere. */
    fun turnRobot(headingDegrees: Float): Arena {
        val d = normaliseDegrees(headingDegrees)
        if (d == robot.headingDegrees) return this
        return copy(robot = robot.copy(headingDegrees = d))
    }

    /**
     * The same 0..CELLS-1 range an obstacle's coordinate uses, since the robot
     * now counts in the same units. A centre on cell 0 or cell 19 is legal -
     * that is a robot at the very edge, half its body off the board, which is
     * a real position and is drawn as one.
     */
    private fun centreInBounds(x: Float, y: Float) =
        x in 0f..(Config.CELLS - 1).toFloat() && y in 0f..(Config.CELLS - 1).toFloat()

    private fun inBounds(cell: Cell) =
        cell.x in 0 until Config.CELLS && cell.y in 0 until Config.CELLS
}
