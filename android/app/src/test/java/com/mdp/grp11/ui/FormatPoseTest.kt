package com.mdp.grp11.ui

import com.mdp.grp11.arena.RobotPose
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The status card's pose line. Pinned because it is the only place an operator
 * reads the robot's position as NUMBERS rather than as a block on the grid -
 * it is what they would quote to the robot side when something looks wrong.
 */
class FormatPoseTest {

    @Test fun `a whole-cell pose drops the decimal point`() {
        assertEquals("Robot (7, 2) · 0° N", formatPose(RobotPose(7f, 2f, 0f)))
    }

    @Test fun `the start pose reads as the corner cell`() {
        assertEquals("Robot (1, 1) · 0° N", formatPose(RobotPose(1f, 1f, 0f)))
    }

    @Test fun `a fractional pose keeps two places`() {
        assertEquals("Robot (5.55, 6.55) · 20°", formatPose(RobotPose(5.55f, 6.55f, 20f)))
    }

    /** 10cm per cell, so a third decimal is a tenth of a millimetre of arena. */
    @Test fun `anything finer than two places is rounded away`() {
        assertEquals("Robot (5.55, 6.5) · 20°", formatPose(RobotPose(5.5549f, 6.4999f, 20f)))
    }

    /**
     * The cardinal letter appears only at an exact heading, matching the
     * compass, which lights no key when the robot is between two. Claiming
     * "N" at 47 degrees would be a small lie repeated on every message.
     */
    @Test fun `the cardinal letter appears only when the heading is exact`() {
        assertEquals("Robot (5, 5) · 90° E", formatPose(RobotPose(5f, 5f, 90f)))
        assertEquals("Robot (5, 5) · 270° W", formatPose(RobotPose(5f, 5f, 270f)))
        assertEquals("Robot (5, 5) · 47°", formatPose(RobotPose(5f, 5f, 47f)))
        assertEquals("Robot (5, 5) · 89°", formatPose(RobotPose(5f, 5f, 89.4f)))
    }

    @Test fun `a fractional heading is rounded to a whole degree`() {
        assertEquals("Robot (5, 5) · 143°", formatPose(RobotPose(5f, 5f, 142.6f)))
    }
}
