package com.mdp.grp11.protocol

/**
 * Image pool from the module briefing: ids 11-40, thirty images, with the
 * letters deliberately skipping I through R.
 *
 * Labels are for the status line and the reference chart. The block itself
 * always shows the numeric target id.
 */
private val IMAGE_LABELS: Map<Int, String> = buildMap {
    (11..19).forEach { put(it, "digit ${it - 10}") }
    "ABCDEFGH".forEachIndexed { i, c -> put(20 + i, "letter $c") }
    "STUVWXYZ".forEachIndexed { i, c -> put(28 + i, "letter $c") }
    put(36, "up arrow")
    put(37, "down arrow")
    put(38, "right arrow")
    put(39, "left arrow")
    put(40, "stop")
}

/**
 * Total: every [id] produces a non-empty label and this never throws. The
 * decoder does not range-check target ids, so out-of-range values do reach
 * here in real use and fall through to "unrecognised id".
 */
fun imageLabel(id: Int): String = IMAGE_LABELS[id] ?: "unrecognised id"

/** One row of the reference chart: the id the robot reports, and what it means. */
data class ImageEntry(val id: Int, val label: String)

/**
 * The whole pool in id order, for the on-screen reference chart. Derived from
 * the same map [imageLabel] reads, never a second hand-written list - a chart
 * that disagreed with the status line would be worse than no chart at all.
 */
val imagePool: List<ImageEntry> =
    IMAGE_LABELS.entries.sortedBy { it.key }.map { ImageEntry(it.key, it.value) }
