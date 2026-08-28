package com.mdp.grp11.protocol

/**
 * The four compass directions, and the headings they stand for.
 *
 * Faces are still how an OPERATOR expresses a direction - four keys on the
 * compass, one bar on an obstacle edge - but a heading on the wire is a
 * continuous angle. [degrees] is the bridge between the two, and it fixes the
 * convention: **0 is north, increasing clockwise**, matching the AMD tool and
 * the cardinal letters this enum already carried.
 */
enum class Face(val degrees: Float) {
    N(0f), E(90f), S(180f), W(270f);

    companion object {
        /** Returns null for anything that is not one of the four faces. */
        fun parse(s: String): Face? = when (s.trim().uppercase()) {
            "N" -> N
            "E" -> E
            "S" -> S
            "W" -> W
            else -> null
        }

        /**
         * The face lying EXACTLY at this heading, or null when the heading
         * falls between two.
         *
         * Deliberately not "nearest": this drives which compass key lights up,
         * and rounding 47 degrees to N would tell the operator the robot is
         * facing a direction it is not. No key lit is the honest reading.
         */
        fun atDegrees(deg: Float): Face? = entries.firstOrNull { it.degrees == deg }
    }
}

/**
 * Wraps any angle into [0,360). A heading is periodic, so 450 IS 90 - that is
 * modular arithmetic, not an error to reject, and odometry that accumulates
 * will hand you numbers outside the range eventually.
 */
fun normaliseDegrees(d: Float): Float = ((d % 360f) + 360f) % 360f
