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

    /** Arena cell -> centre of that cell in canvas pixels. */
    fun centreOf(cellX: Int, cellY: Int, gridPx: Float): Pair<Float, Float> {
        val cell = gridPx / Config.CELLS
        val cx = cellX * cell + cell / 2f
        val cy = toCanvasRow(cellY) * cell + cell / 2f
        return cx to cy
    }
}
