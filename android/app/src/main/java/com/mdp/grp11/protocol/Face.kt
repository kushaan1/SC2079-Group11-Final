package com.mdp.grp11.protocol

enum class Face {
    N, E, S, W;

    companion object {
        /** Returns null for anything that is not one of the four faces. */
        fun parse(s: String): Face? = when (s.trim().uppercase()) {
            "N" -> N
            "E" -> E
            "S" -> S
            "W" -> W
            else -> null
        }
    }
}
