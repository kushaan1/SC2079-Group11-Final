using System;
namespace ScriptNs
{
    public class ScriptContainer
    {
        // AMD's robot size in cells, from Settings -> Default Arena Settings
        // -> Robot size. AMD reports the robot's TOP-LEFT cell, the natural
        // anchor for its own top-left-origin system, and the app wants the
        // footprint's CENTRE - so half of this is added before the flip.
        //
        // This must match AMD'S setting. It no longer has to match
        // Config.ROBOT_SIZE_CELLS in the app: under centre anchoring a size
        // mismatch changes how big the box is DRAWN and never where it sits.
        // That used to be a three-way coupling where any disagreement shifted
        // every robot position.
        private const double ROBOT_SIZE = 3;

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
                // AMD reports the footprint's TOP-LEFT cell index; the app
                // wants the cell it is CENTRED on, in the same units an
                // obstacle coordinate uses. That is half a footprint further
                // in - a whole number for an odd robot size, so a 3-cell robot
                // still emits plain integers.
                //
                // The y flip is then the ordinary point flip, height - 1 - y,
                // because a centre IS a point: the footprint's own height has
                // already been accounted for by the offset above.
                double offset = (ROBOT_SIZE - 1) / 2.0;
                double x = robotPosition[0] + offset;
                double y = (height - 1) - (robotPosition[1] + offset);
                // Degrees, raw. AMD already gives an angle - North = 0,
                // increasing clockwise, the same convention the app uses - and
                // the old HeadingLetter() bucketed it into one of four letters,
                // throwing away every heading an arcing car actually holds.
                int deg = ((robotPosition[2] % 360) + 360) % 360;
                return "ROBOT," + Fmt(x) + "," + Fmt(y) + "," + deg;
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

        // InvariantCulture, not the default: on a machine set to a
        // comma-decimal locale, "6.5" would be written "6,5" and split the
        // message into an extra field on the way through the parser.
        private static string Fmt(double v)
        {
            return v.ToString("0.##", System.Globalization.CultureInfo.InvariantCulture);
        }
    }
}
