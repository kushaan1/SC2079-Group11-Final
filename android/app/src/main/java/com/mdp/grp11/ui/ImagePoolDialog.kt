package com.mdp.grp11.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.mdp.grp11.protocol.imagePool
import com.mdp.grp11.ui.theme.DmMono
import com.mdp.grp11.ui.theme.MdpTokens

/**
 * The image pool as a lookup chart: which target id means which symbol.
 *
 * C.9 puts the numeric id on the block and nothing else, so without this the
 * only way to judge whether a recognition was CORRECT is the briefing PDF - on
 * a different screen, during a timed run. The status line already spells out
 * the one most recent target; this is the other thirty.
 *
 * A dialog rather than a permanent panel: the tablet gives the app about 700dp
 * of height and every one of them is already spoken for. A chart is consulted
 * for a few seconds and then wants to be gone.
 *
 * [found] are the ids the robot has actually reported this session. They are
 * marked, so a supervisor can see at a glance what has been confirmed rather
 * than counting blocks on the arena.
 */
@Composable
fun ImagePoolDialog(
    found: Set<Int>,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Image pool") },
        text = {
            Column {
                Text(
                    if (found.isEmpty()) {
                        "Ids 11-40. Nothing reported yet."
                    } else {
                        "Ids 11-40. ${found.size} reported so far, highlighted."
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = MdpTokens.Muted,
                    modifier = Modifier.padding(bottom = 8.dp),
                )
                // Fixed count, not adaptive: the chart is a stable shape the
                // operator learns the position of, and a grid that reflows
                // between openings has to be re-read every time.
                LazyVerticalGrid(
                    columns = GridCells.Fixed(3),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                    // Bounded so the dialog cannot grow past the screen on a
                    // short window; the grid scrolls inside instead.
                    modifier = Modifier.heightIn(max = 420.dp),
                ) {
                    items(imagePool, key = { it.id }) { entry ->
                        PoolRow(
                            id = entry.id,
                            label = entry.label,
                            reported = entry.id in found,
                        )
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("CLOSE") } },
    )
}

@Composable
private fun PoolRow(id: Int, label: String, reported: Boolean) {
    Row(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(6.dp))
            .background(if (reported) MdpTokens.Green else MaterialTheme.colorScheme.surfaceVariant)
            .padding(horizontal = 8.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        // Monospace and fixed-width so the ids form a readable column rather
        // than jittering with the label beside them.
        Text(
            id.toString(),
            fontFamily = DmMono,
            fontWeight = FontWeight.Bold,
            style = MaterialTheme.typography.bodyMedium,
            modifier = Modifier.width(24.dp),
        )
        Text(
            label,
            style = MaterialTheme.typography.bodyMedium,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}
