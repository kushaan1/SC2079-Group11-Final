package com.mdp.grp11.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.mdp.grp11.ui.theme.MdpTokens

/**
 * Save/load/reset controls for the arena layout, plus the image-pool chart.
 * Uses standard Material 3 APIs (MaterialTheme.colorScheme via the
 * button/dialog defaults) so it picks up MdpTheme automatically once that
 * lands; it must not invent its own colour constants ahead of it.
 *
 * IMAGES sits here rather than beside the status line it relates to because
 * this is the only row on the screen with room for another control, and a
 * chart the operator cannot find is a chart that does not exist.
 */
@Composable
fun ArenaToolbar(
    saved: List<String>,
    onSave: (String) -> Unit,
    onLoad: (String) -> Unit,
    onDelete: (String) -> Unit,
    onReset: () -> Unit,
    onShowImages: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var showSave by remember { mutableStateOf(false) }
    var showLoad by remember { mutableStateOf(false) }
    var confirmReset by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf<String?>(null) }
    var name by remember { mutableStateOf("") }

    Row(modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        MdpOutlinedButton(
            onClick = { name = ""; showSave = true },
            modifier = Modifier.weight(1f).height(MdpTokens.TouchTarget),
        ) { Text("SAVE") }

        MdpOutlinedButton(
            onClick = { showLoad = true },
            enabled = saved.isNotEmpty(),
            modifier = Modifier.weight(1f).height(MdpTokens.TouchTarget),
        ) { Text("LOAD") }

        MdpOutlinedButton(
            onClick = { confirmReset = true },
            modifier = Modifier.weight(1f).height(MdpTokens.TouchTarget),
        ) { Text("RESET") }

        MdpOutlinedButton(
            onClick = onShowImages,
            modifier = Modifier.weight(1f).height(MdpTokens.TouchTarget),
        ) { Text("IMAGES") }
    }

    if (showSave) {
        AlertDialog(
            onDismissRequest = { showSave = false },
            title = { Text("Save layout") },
            text = {
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    singleLine = true,
                    label = { Text("Name") },
                )
            },
            confirmButton = {
                TextButton(
                    onClick = { showSave = false; if (name.isNotBlank()) onSave(name.trim()) },
                ) { Text("SAVE") }
            },
            dismissButton = { TextButton(onClick = { showSave = false }) { Text("CANCEL") } },
        )
    }

    /*
     * A dialog, not the DropdownMenu this used to be. That menu was the fourth
     * child of the button Row, so it anchored to the ROW's edge rather than
     * under LOAD - and its items were default menu height, well under a touch
     * target, listing names that can be any length. Picking the wrong layout
     * costs the whole board. Full-width rows at TouchTarget height, and the
     * delete that ArenaStore has always implemented and nothing ever called.
     */
    if (showLoad) {
        AlertDialog(
            onDismissRequest = { showLoad = false },
            title = { Text("Load layout") },
            text = {
                Column(
                    Modifier
                        .fillMaxWidth()
                        // Bounded and scrollable: the list has no cap, and
                        // an unbounded Column would push the buttons off a
                        // 700dp-tall screen once a few runs' worth accumulate.
                        .heightIn(max = 360.dp)
                        .verticalScroll(rememberScrollState()),
                ) {
                    saved.forEachIndexed { i, n ->
                        if (i > 0) HorizontalDivider()
                        Row(
                            Modifier.fillMaxWidth(),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            TextButton(
                                onClick = { showLoad = false; onLoad(n) },
                                modifier = Modifier.weight(1f).height(MdpTokens.TouchTarget),
                            ) {
                                Text(
                                    n,
                                    modifier = Modifier.fillMaxWidth(),
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                )
                            }
                            TextButton(
                                onClick = { confirmDelete = n },
                                modifier = Modifier.height(MdpTokens.TouchTarget),
                            ) {
                                Text("DELETE", color = MaterialTheme.colorScheme.error)
                            }
                        }
                    }
                }
            },
            confirmButton = { TextButton(onClick = { showLoad = false }) { Text("CLOSE") } },
        )
    }

    // Deleting is confirmed for the same reason clearing is: it destroys a
    // layout that took real effort to enter, and the button sits one thumb-width
    // from the one that loads it.
    confirmDelete?.let { target ->
        AlertDialog(
            onDismissRequest = { confirmDelete = null },
            title = { Text("Delete \"$target\"?") },
            text = { Text("Removes this saved layout. The arena on screen is not affected.") },
            confirmButton = {
                TextButton(onClick = { confirmDelete = null; onDelete(target) }) { Text("DELETE") }
            },
            dismissButton = { TextButton(onClick = { confirmDelete = null }) { Text("CANCEL") } },
        )
    }

    // Reset wipes a layout that took real effort to enter, so it is confirmed.
    if (confirmReset) {
        AlertDialog(
            onDismissRequest = { confirmReset = false },
            title = { Text("Clear the arena?") },
            text = { Text("Removes every obstacle. This cannot be undone.") },
            confirmButton = {
                TextButton(onClick = { confirmReset = false; onReset() }) { Text("CLEAR") }
            },
            dismissButton = { TextButton(onClick = { confirmReset = false }) { Text("CANCEL") } },
        )
    }
}
