package com.mdp.grp11.session

/**
 * Which planner the image-recognition run should use. Chosen by the operator
 * on the tablet; the RPi is what acts on it.
 *
 * Reaches the RPi inside the image-rec start JSON. The wire spelling lives in
 * `Config.algorithmTokens` beside the other tokens, not on this enum.
 *
 * [label] is the human name, used both in the chooser and (upper-cased) on
 * the IMAGE REC button that shows the current pick.
 */
enum class Algorithm(val label: String) {
    Greedy("Greedy"),
    Optimal("Optimal"),
    TurnInPlace("Turn in-place"),
}
