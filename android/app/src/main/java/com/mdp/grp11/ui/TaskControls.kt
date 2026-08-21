package com.mdp.grp11.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.mdp.grp11.session.RunKind
import com.mdp.grp11.ui.theme.MdpTokens

/**
 * Task-level commands. Without these the app can drive the robot manually but
 * cannot tell it to begin a run, which is what a competition round consists of.
 *
 * This composable only signals intent - [onStart] carries the [RunKind] the
 * operator picked and [onSendArena] is a bare trigger. It never inlines a
 * command string; the caller (ArenaViewModel) is what maps a [RunKind] to
 * `Config.taskTokens.beginExploration` / `.beginFastest`, and maps
 * [onSendArena] to `Config.taskTokens.sendArena`, so the token vocabulary
 * stays defined in exactly one place.
 */
@Composable
fun TaskControls(
    enabled: Boolean,
    running: RunKind?,
    onStart: (RunKind) -> Unit,
    onStop: () -> Unit,
    onSendArena: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            MdpButton(
                onClick = { onStart(RunKind.Exploration) },
                enabled = enabled && running == null,
                container = MdpTokens.Green,
                contentColor = MdpTokens.Ink,
                modifier = Modifier.weight(1f).height(MdpTokens.TouchTarget),
            ) { Text("IMAGE REC", maxLines = 1) }
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
