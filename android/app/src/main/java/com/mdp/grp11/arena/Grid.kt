package com.mdp.grp11.arena

import com.mdp.grp11.config.Config

/**
 * The single place cell coordinates meet pixels.
 *
 * Arena y counts UPWARD from (0,0) at bottom-left. Android canvas y counts
 * DOWNWARD from the top. Every conversion between the two lives here; scatter
 * it and the grid ends up mirrored.
 */
object Grid {

    /** Arena row -> canvas row (and back; the mapping is its own inverse). */
    fun toCanvasRow(cellY: Int): Int = Config.CELLS - 1 - cellY

    /** Canvas pixel -> arena cell, clamped to the grid. */
    fun cellAt(px: Float, py: Float, gridPx: Float): Pair<Int, Int> {
        val cell = gridPx / Config.CELLS
        val x = (px / cell).toInt().coerceIn(0, Config.CELLS - 1)
        val row = (py / cell).toInt().coerceIn(0, Config.CELLS - 1)
        return x to toCanvasRow(row)
    }

    /**
     * Arena x -> canvas x in pixels, for the CONTINUOUS form of the same
     * coordinate [toCanvasRow] handles discretely.
     *
     * x is a cell INDEX, exactly as an obstacle's is - `5` is cell 5, and
     * decimals interpolate between cell centres. So the pixel result is the
     * centre of cell 5, half a cell in from its left edge; that half-cell is
     * the only thing these functions add.
     */
    fun toCanvasX(arenaX: Float, gridPx: Float): Float {
        val cell = gridPx / Config.CELLS
        return (arenaX + 0.5f) * cell
    }

    /**
     * Arena y -> canvas y in pixels, flipped, since arena y counts up and
     * canvas y counts down.
     *
     * Note it subtracts from `CELLS - 0.5`, where [toCanvasRow] subtracts from
     * `CELLS - 1`: this lands on the row's CENTRE where that one lands on its
     * top edge. Confusing the two shifts the robot half a cell, which looks
     * like a rounding bug rather than a coordinate bug.
     */
    fun toCanvasY(arenaY: Float, gridPx: Float): Float {
        val cell = gridPx / Config.CELLS
        return (Config.CELLS - 0.5f - arenaY) * cell
    }

    /** Canvas pixel -> arena point, in the same cell-index units, clamped. */
    fun pointAt(px: Float, py: Float, gridPx: Float): Pair<Float, Float> {
        val cell = gridPx / Config.CELLS
        val last = (Config.CELLS - 1).toFloat()
        val x = (px / cell - 0.5f).coerceIn(0f, last)
        val y = (Config.CELLS - 0.5f - py / cell).coerceIn(0f, last)
        return x to y
    }

    /** Arena cell -> centre of that cell in canvas pixels. */
    fun centreOf(cellX: Int, cellY: Int, gridPx: Float): Pair<Float, Float> {
        val cell = gridPx / Config.CELLS
        val cx = cellX * cell + cell / 2f
        val cy = toCanvasRow(cellY) * cell + cell / 2f
        return cx to cy
    }
}
