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
import com.mdp.grp11.ui.theme.MdpTokens
import com.mdp.grp11.ui.theme.hardSurface

/**
 * The selective status readout: robot status messages and the last target
 * only, never the raw stream, which lives in [BtLogPanel]. Keeping the two
 * panels separate is what keeps this one filtered - nothing here ever renders
 * a [com.mdp.grp11.connection.TrafficLine] directly.
 */
@Composable
fun StatusPanel(status: String?, targetLine: String?, modifier: Modifier = Modifier) {
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
