package com.mdp.grp11.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import com.mdp.grp11.connection.TrafficLine
import com.mdp.grp11.ui.theme.DmMono
import com.mdp.grp11.ui.theme.MdpTokens
import com.mdp.grp11.ui.theme.hardSurface

/**
 * Every line of traffic, both directions, unfiltered - the deliberate
 * counterpart to [StatusPanel], which is required to be selective. This is
 * also the debugging tool, so nothing here is dropped or summarised.
 *
 * Dark, which is legibility as much as style: TX lines are yellow, and on a
 * near-white card that is close to unreadable. An ink ground turns the same
 * two tokens into high-contrast terminal colours.
 *
 * [lines] is oldest-first. Movement commands stream fast during a run, so this
 * renders `reverseLayout = true` over the reversed list - the newest line is
 * anchored at the bottom and on screen by default, while the order still reads
 * oldest-to-newest like a normal log.
 *
 * `delivered == false` is flagged because it is a confirmed failure.
 * `delivered == true` is NOT a confirmed delivery: a write into a half-open
 * socket can report success for a line the peer never received. So the
 * successful case gets no decoration that would read as a receipt.
 */
@Composable
fun BtLogPanel(lines: List<TrafficLine>, modifier: Modifier = Modifier) {
    // Not a Card: Card would paint its own container colour under the ink and
    // bring its own elevation shadow, which is the blurred look hardSurface
    // exists to avoid. clip() before background() so the fill honours the same
    // radius the border is drawn at.
    Column(
        modifier
            .hardSurface()
            .clip(RoundedCornerShape(MdpTokens.CornerRadius))
            .background(MdpTokens.Ink)
            .padding(12.dp)
    ) {
        Text(
            "BLUETOOTH LOG",
            style = MaterialTheme.typography.labelMedium,
            color = MdpTokens.MutedOnInk,
            maxLines = 1,
        )
        // Both modifiers are load-bearing.
        //
        // weight(1f), so the list takes what is LEFT after the header rather
        // than competing with it: a Column measures non-weighted children
        // against the same upper bound, and an unconstrained LazyColumn fills
        // it - so the pair demanded a header's worth more height than there
        // was, and the overflow was clipped off the BOTTOM, which under
        // reverseLayout is where the newest line lives.
        //
        // fillMaxWidth(), because a LazyColumn's cross axis is wrap-content:
        // without it the list is only as wide as its widest line, and every
        // pixel right of that sits outside the scrolling container and
        // swallows the drag. Invisible on a flat-coloured panel.
        LazyColumn(Modifier.fillMaxWidth().weight(1f), reverseLayout = true) {
            items(lines.asReversed()) { line ->
                Row(Modifier.fillMaxWidth()) {
                    Text(
                        if (line.outbound) "TX " else "RX ",
                        fontFamily = DmMono,
                        style = MaterialTheme.typography.bodySmall,
                        color = if (line.outbound) MdpTokens.Yellow else MdpTokens.Green,
                    )
                    Text(
                        line.text,
                        fontFamily = DmMono,
                        style = MaterialTheme.typography.bodySmall,
                        // Paper, not onSurface: this panel inverts the ground,
                        // so the theme's dark-on-light body colour would be
                        // invisible here.
                        color = MdpTokens.Paper,
                        // Wrapped, not ellipsised. A truncated line is useless
                        // for the one job this panel has - a long ADD or FACE
                        // loses its coordinates to the ellipsis, which is
                        // exactly the part being debugged.
                        //
                        // Safe because of reverseLayout: the newest line is
                        // anchored at the BOTTOM, so a taller entry pushes
                        // older lines off the top, never the newest off the
                        // bottom.
                        modifier = Modifier.weight(1f),
                    )
                    if (!line.delivered) {
                        Text(
                            " UNSENT",
                            fontFamily = DmMono,
                            style = MaterialTheme.typography.bodySmall,
                            color = MdpTokens.Pink,
                            maxLines = 1,
                        )
                    }
                }
            }
        }
    }
}
