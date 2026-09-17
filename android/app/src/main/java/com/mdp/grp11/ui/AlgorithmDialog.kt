package com.mdp.grp11.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import com.mdp.grp11.session.Algorithm
import com.mdp.grp11.ui.theme.MdpTokens

/**
 * What IMAGE REC does, as a single-choice list: one of the three planners
 * for the image-rec run, or the checklist A.5 face search in its place.
 *
 * Reached by holding IMAGE REC. A long press rather than a visible control
 * because the right-hand column has no room left for one, and because the
 * choice is made once per session, not once per run - the button itself
 * shows the current pick, so nothing is hidden. The face search lives here
 * for the same reason: it is demonstrated once, and a fourth button would
 * cost every other button width for the rest of the term.
 *
 * Tapping a row picks it and closes the dialog. There is no confirm step: the
 * pick changes nothing on the robot yet, and a two-tap flow for a four-item
 * radio list is ceremony without protection.
 */
@Composable
fun AlgorithmDialog(
    current: Algorithm,
    onPick: (Algorithm) -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Image rec mode") },
        text = {
            Column(Modifier.selectableGroup()) {
                Text(
                    "The planner the image-rec run will use, or the A.5 face search: " +
                        "place one block, set the bullseye's face, then tap IMAGE REC.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MdpTokens.Muted,
                    modifier = Modifier.padding(bottom = 8.dp),
                )
                Algorithm.entries.forEach { algorithm ->
                    // The whole row is the target, at touch-target height.
                    // The radio itself has no click of its own, so the
                    // accessibility tree sees one selectable per option
                    // rather than a row and a button that do the same thing.
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .height(MdpTokens.TouchTarget)
                            .selectable(
                                selected = algorithm == current,
                                role = Role.RadioButton,
                                onClick = { onPick(algorithm); onDismiss() },
                            ),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        RadioButton(selected = algorithm == current, onClick = null)
                        Spacer(Modifier.width(12.dp))
                        Text(
                            algorithm.label,
                            style = MaterialTheme.typography.bodyLarge,
                            color = MdpTokens.Ink,
                        )
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("CANCEL") } },
    )
}
