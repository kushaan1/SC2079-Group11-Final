using System;
namespace ScriptNs
{
    public class ScriptContainer
    {
        // Robot footprint size in cells. AMD reports the robot's TOP-LEFT
        // cell (the natural anchor for its own top-left-origin coordinate
        // system); the app anchors and draws the robot at its BOTTOM-LEFT
        // cell, extending the footprint up-and-right
        // (ArenaCanvas.drawRobot). Converting a top-left anchor into a
        // bottom-left-origin system has to subtract the block's own height,
        // not just flip the point - see the y calculation below. This value
        // must agree with THREE places: AMD's Settings -> Default Arena
        // Settings -> Robot size, this constant, and Config.ROBOT_SIZE_CELLS
        // in the Android app. If any of the three disagree, every drawn
        // robot position is off by rows equal to the difference.
        private const int ROBOT_SIZE = 3;

        // Emits the checklist's own formats so the Android app needs no
        // AMD-specific parsing.
        //
        // Two conversions are required:
        //  1. AMD's origin is TOP-LEFT with y increasing downward; the arena's
        //     is BOTTOM-LEFT with y increasing upward.
        //  2. AMD's direction is an ANGLE in degrees, North = 0, increasing
        //     clockwise. The checklist wants a letter.
        public static string MainScript(
            int[,] gridLayout,
            int[] robotPosition,
            bool posTgridF,
            bool addObstacle,
            int[] obstaclePosition)
        {
            int height = gridLayout.GetLength(1);

            if (posTgridF)
            {
                int x = robotPosition[0];
                // A *point* flip (height - 1 - y) is wrong here: it flips
                // where the reported row sits, but the reported row is the
                // block's TOP-LEFT, not a dimensionless point. Flipping a
                // top-left anchor into a bottom-left-origin system must also
                // subtract the block's own height so the anchor ends up at
                // the footprint's bottom-left, matching how the app draws it.
                int y = height - ROBOT_SIZE - robotPosition[1];
                string dir = HeadingLetter(robotPosition[2]);
                return "ROBOT," + x + "," + y + "," + dir;
            }

            int ox = obstaclePosition[0];
            // Obstacles are 1x1 in the app's model (ArenaCanvas.drawObstacle
            // draws a single cell, no footprint offset), so top-left and
            // bottom-left are the same cell and a *point* flip is correct
            // here, unlike the robot above. height - 1 - y stays.
            int oy = height - 1 - obstaclePosition[1];
            // AMD gives no obstacle number, so send position only; the app logs
            // it as Unknown rather than guessing an id.
            return (addObstacle ? "AMDADD," : "AMDSUB,") + "(" + ox + "," + oy + ")";
        }

        private static string HeadingLetter(int degrees)
        {
            int d = ((degrees % 360) + 360) % 360;
            if (d >= 315 || d < 45) return "N";
            if (d < 135) return "E";
            if (d < 225) return "S";
            return "W";
        }
    }
}
