package com.mdp.grp11.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.mdp.grp11.arena.RobotPose
import com.mdp.grp11.protocol.Face
import com.mdp.grp11.ui.theme.MdpTokens
import com.mdp.grp11.ui.theme.hardSurface
import kotlin.math.roundToInt

/**
 * The robot's pose as one line, for the status card.
 *
 * Trailing `.0` is trimmed, so a robot sitting squarely on a cell reads
 * `(7, 2)` rather than `(7.0, 2.0)` - most of a run is spent on whole cells,
 * and the decimals only matter when they are actually saying something.
 * Anything finer than two places is noise at 10cm per cell.
 *
 * The cardinal letter is appended only when the heading is exactly on one, for
 * the same reason the compass lights no key otherwise: a car mid-arc is not
 * facing north, and saying so would be a small lie repeated constantly.
 */
fun formatPose(pose: RobotPose): String {
    val heading = pose.headingDegrees.roundToInt()
    val face = Face.atDegrees(pose.headingDegrees)?.let { " ${it.name}" } ?: ""
    return "Robot (${cell(pose.x)}, ${cell(pose.y)}) · $heading°$face"
}

private fun cell(v: Float): String {
    val rounded = (v * 100).roundToInt() / 100f
    return if (rounded == rounded.toInt().toFloat()) {
        rounded.toInt().toString()
    } else {
        rounded.toString()
    }
}

/**
 * The selective status readout: robot status messages, the last target and the
 * robot's own pose - never the raw stream, which lives in [BtLogPanel].
 * Keeping the two panels separate is what keeps this one filtered - nothing
 * here ever renders a [com.mdp.grp11.connection.TrafficLine] directly.
 */
@Composable
fun StatusPanel(
    status: String?,
    targetLine: String?,
    robot: RobotPose,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier
            .hardSurface()
            .clip(RoundedCornerShape(MdpTokens.CornerRadius))
            .background(MdpTokens.Paper)
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text(
            "STATUS",
            style = MaterialTheme.typography.labelMedium,
            color = MdpTokens.Muted,
        )
        // A dot per line, and not decoration: the two lines come from DIFFERENT
        // sources - the live status the robot relays, and the last target it
        // reported - and otherwise read as one paragraph of robot output.
        DotLine(
            dot = MdpTokens.Pink,
            text = status ?: "Idle",
            // A raw payload off the link, so its length is not this app's to
            // bound at the source. Being selective includes truncating a
            // pathological line rather than letting it overflow the slot.
            style = MaterialTheme.typography.bodyLarge,
            color = MdpTokens.Ink,
        )
        // Bounded for the same reason, and because a wrap here would push the
        // card past the height its slot was proportioned for.
        if (targetLine != null) {
            DotLine(
                dot = MdpTokens.Muted,
                text = targetLine,
                style = MaterialTheme.typography.bodySmall,
                color = MdpTokens.Muted,
            )
        }
        // Always present, unlike the target line: the robot always has a pose,
        // and a readout that comes and goes is one the operator has to hunt
        // for. Last so it sits at the card's bottom edge whether or not a
        // target has been reported, rather than shifting when one arrives.
        DotLine(
            dot = MdpTokens.Muted,
            text = formatPose(robot),
            style = MaterialTheme.typography.bodySmall,
            color = MdpTokens.Muted,
        )
    }
}

@Composable
private fun DotLine(
    dot: Color,
    text: String,
    style: TextStyle,
    color: Color,
) {
    Row(
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(8.dp).clip(CircleShape).background(dot))
        Text(text, style = style, color = color, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}
