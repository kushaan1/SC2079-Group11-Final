package com.mdp.grp11.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import com.mdp.grp11.protocol.Face
import com.mdp.grp11.ui.theme.MdpTokens
import com.mdp.grp11.ui.theme.hardSurface

/**
 * C.7 alternative interaction. A block face is 4.7mm x 1mm on this screen, so
 * edge-tapping is impossible; the checklist explicitly allows another method
 * provided it stays touch-based.
 *
 * Tapping a face key always calls [onPick] with that face - it does not decide
 * set-vs-clear itself. The caller compares against [current] and toggles the
 * face off if it was already active (see ArenaViewModel.pickFace), which is
 * how an operator recovers from a mis-tap: tap the same face again to clear it.
 */
/**
 * Each of the three key rows takes an equal share of whatever height the slot
 * gives, rather than demanding a fixed 3 x TouchTarget. The fixed version
 * overflowed its card on the real tablet and clipped the S key clean off -
 * the compass sits in a PROPORTIONAL slot (see MainScreen's weight constants),
 * so its height is whatever the screen has left, not a number this file can
 * assume. A heightIn floor keeps the keys above Material's touch minimum.
 */
@Composable
fun FaceCompass(
    label: String,
    current: Face?,
    onPick: (Face) -> Unit,
    onDone: () -> Unit,
    modifier: Modifier = Modifier,
    /**
     * What the four keys mean here. The same compass drives two different
     * things - a block's image face and the robot's heading - and the operator
     * has to be able to tell which one a tap is about to move.
     */
    title: String = "IMAGE FACE",
) {
    // Pink border and pink shadow, unlike every other card on the screen.
    // This one is modal in spirit - it replaces the status panel only while a
    // block is selected - so it is deliberately the loudest surface up, and
    // the colour matches the selection ring drawn around the block itself.
    Column(
        modifier
            .hardSurface(borderColor = MdpTokens.Pink, shadowColor = MdpTokens.Pink)
            .clip(RoundedCornerShape(MdpTokens.CornerRadius))
            .background(MdpTokens.Paper)
            .padding(12.dp)
            .fillMaxHeight(),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text(
            "$title · $label",
            style = MaterialTheme.typography.labelMedium,
            color = MdpTokens.Muted,
        )
        Row(
            Modifier.fillMaxWidth().heightIn(min = 48.dp).weight(1f),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Box(Modifier.weight(1f))
            FaceKey("N", current == Face.N, Modifier.weight(1f)) { onPick(Face.N) }
            Box(Modifier.weight(1f))
        }
        Row(
            Modifier.fillMaxWidth().heightIn(min = 48.dp).weight(1f),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            FaceKey("W", current == Face.W, Modifier.weight(1f)) { onPick(Face.W) }
            MdpButton(
                onClick = onDone,
                container = MdpTokens.Green,
                contentColor = MdpTokens.Ink,
                modifier = Modifier.weight(1f).fillMaxHeight(),
            ) { Text("OK", maxLines = 1) }
            FaceKey("E", current == Face.E, Modifier.weight(1f)) { onPick(Face.E) }
        }
        Row(
            Modifier.fillMaxWidth().heightIn(min = 48.dp).weight(1f),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Box(Modifier.weight(1f))
            FaceKey("S", current == Face.S, Modifier.weight(1f)) { onPick(Face.S) }
            Box(Modifier.weight(1f))
        }
    }
}

@Composable
private fun FaceKey(
    label: String,
    active: Boolean,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    MdpButton(
        onClick = onClick,
        container = if (active) MdpTokens.Yellow else MdpTokens.Paper,
        contentColor = MdpTokens.Ink,
        modifier = modifier.fillMaxHeight(),
    ) { Text(label, maxLines = 1) }
}
