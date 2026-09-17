package com.mdp.grp11.session

/**
 * What the IMAGE REC button does: which planner the image-recognition run
 * should use, or the checklist A.5 face search instead of a run. Chosen by
 * the operator on the tablet; the RPi is what acts on it.
 *
 * The three planners reach the RPi inside the image-rec start JSON; the
 * face search is a different start message with no planner in it. The wire
 * spellings live in `Config.algorithmTokens` and `Config.taskTokens` beside
 * the other tokens, not on this enum.
 *
 * [label] is the human name, used both in the chooser and (upper-cased) on
 * the IMAGE REC button that shows the current pick.
 */
enum class Algorithm(val label: String) {
    Greedy("Greedy"),
    Optimal("Optimal"),
    TurnInPlace("Turn in-place"),
    FaceSearch("Face search"),
}
