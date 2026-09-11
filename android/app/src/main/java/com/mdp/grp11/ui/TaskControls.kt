package com.mdp.grp11.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.mdp.grp11.session.Algorithm
import com.mdp.grp11.session.RunKind
import com.mdp.grp11.ui.theme.MdpTokens

/**
 * Task-level commands. Without these the app can drive the robot manually but
 * cannot tell it to begin a run, which is what a competition round consists of.
 *
 * This composable only signals intent - [onStart] carries the [RunKind] the
 * operator picked and [onSendArena] is a bare trigger. It never inlines a
 * command string; the caller (ArenaViewModel) is what turns a [RunKind] into
 * the image-rec start JSON or the `beginFastest` token, and [onSendArena]
 * into the layout JSON, so the wire vocabulary stays defined in exactly one
 * place.
 *
 * IMAGE REC also carries the image-rec [algorithm]: shown under the label so
 * the current pick is never hidden, and changed by holding the button, which
 * fires [onPickAlgorithm]. A hold rather than a visible control because this
 * column has no room left for one.
 */
@Composable
fun TaskControls(
    enabled: Boolean,
    running: RunKind?,
    algorithm: Algorithm,
    onStart: (RunKind) -> Unit,
    onStop: () -> Unit,
    onSendArena: () -> Unit,
    onPickAlgorithm: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            MdpButton(
                onClick = { onStart(RunKind.Exploration) },
                // The hold stays live while the tap is disabled - see
                // MdpButton - so the planner can be chosen before connecting.
                onLongClick = onPickAlgorithm,
                enabled = enabled && running == null,
                container = MdpTokens.Green,
                contentColor = MdpTokens.Ink,
                modifier = Modifier.weight(1f).height(MdpTokens.TouchTarget),
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("IMAGE REC", maxLines = 1)
                    // Small caps under the label, in the same colour the
                    // label takes, so it dims with the button when disabled.
                    Text(
                        algorithm.label.uppercase(),
                        style = MaterialTheme.typography.labelSmall.copy(
                            fontSize = 10.sp,
                            letterSpacing = 0.08.sp,
                        ),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
            MdpButton(
                onClick = { onStart(RunKind.FastestCar) },
                enabled = enabled && running == null,
                container = MdpTokens.Blue,
                modifier = Modifier.weight(1f).height(MdpTokens.TouchTarget),
            ) { Text("FASTEST", maxLines = 1) }
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            MdpOutlinedButton(
                onClick = onSendArena,
                enabled = enabled,
                modifier = Modifier.weight(1f).height(MdpTokens.TouchTarget),
            ) { Text("SEND ARENA", maxLines = 1) }
            MdpOutlinedButton(
                onClick = onStop,
                enabled = enabled && running != null,
                modifier = Modifier.weight(1f).height(MdpTokens.TouchTarget),
            ) { Text("END RUN", maxLines = 1) }
        }
    }
}
