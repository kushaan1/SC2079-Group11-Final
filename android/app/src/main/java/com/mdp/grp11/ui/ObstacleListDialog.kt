package com.mdp.grp11.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.LocalTextStyle
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.DialogProperties
import com.mdp.grp11.arena.Arena
import com.mdp.grp11.arena.Cell
import com.mdp.grp11.config.Config
import com.mdp.grp11.ui.theme.DmMono
import com.mdp.grp11.ui.theme.MdpTokens

/**
 * The arena's eight obstacle slots as a form: B1 to B8, each with an X and a
 * Y field, whether or not the block currently exists. A slot with a cell in
 * it is a block on the arena; a slot left blank is not. Setting a blank slot
 * creates the block, setting an existing one moves it, and blanking both
 * fields removes it.
 *
 * The arena is the primary way to position a block, and a drag is precise to
 * the cell - but a cell is ~4.7mm on this screen, and the briefing hands the
 * team obstacle positions as numbers, one per id. A fixed form with a row per
 * id reads against that sheet line for line: no counting rows, no add button,
 * no wondering which id a new block will get.
 *
 * A dialog, like the image pool and for the same reason: consulted for
 * seconds, then wanted gone. Opened from the obstacle count, which is the one
 * thing on screen that already says how many of these slots are filled.
 *
 * Two columns, row-major - B1 B2 / B3 B4 / B5 B6 / B7 B8 - because eight rows
 * of text field in one column outgrow the window and have to scroll, while a
 * landscape tablet has width to spare. Four rows, all in view at once.
 *
 * Each row applies on its own - the SET button, or the keyboard's Done - and
 * never as you type, because "15" passes through "1" on the way in and a
 * block that jumps mid-keystroke also puts a spurious ADD on the link. A
 * refused cell says why under the row and changes nothing; the rules are
 * [Arena.canOccupy]'s, the same ones a drag is held to.
 */
@Composable
fun ObstacleListDialog(
    arena: Arena,
    onSet: (id: Int, cell: Cell?) -> Unit,
    onDismiss: () -> Unit,
) {
    val placed = arena.obstacles.size
    // One requester per slot, so Done on a row can hand focus to the next
    // row's X. Held here rather than in the rows because the hand-off crosses
    // rows, and remembered once because the slots never come or go.
    val focusX = remember { List(Config.MAX_OBSTACLES) { FocusRequester() } }
    val focusManager = LocalFocusManager.current
    val keyboard = LocalSoftwareKeyboardController.current

    AlertDialog(
        onDismissRequest = onDismiss,
        // Material caps its own dialog at 560dp, which two columns of these
        // rows do not fit inside. An outer width modifier overrides that cap
        // (sizeIn cannot shrink below the constraints it is handed), and the
        // platform default width has to be released too, or the window itself
        // stays narrow.
        modifier = Modifier.width(DialogWidth),
        properties = DialogProperties(usePlatformDefaultWidth = false),
        title = { Text("Obstacles") },
        text = {
            Column {
                Text(
                    "$placed of ${Config.MAX_OBSTACLES} placed. " +
                        "Cells 0-${Config.CELLS - 1}, (0,0) bottom-left. " +
                        "Blank both fields to remove.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MdpTokens.Muted,
                    modifier = Modifier.padding(bottom = 8.dp),
                )
                // Four rows, so this never needs to scroll on the tablet - the
                // scroll is a safety net for the keyboard shrinking the
                // dialog's window, so a focused field can pull itself into
                // view rather than sit clipped behind the IME.
                Column(
                    Modifier.verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(RowGap),
                ) {
                    (1..Config.MAX_OBSTACLES).chunked(COLUMNS).forEach { ids ->
                        // Top-aligned, so a refusal under one slot does not
                        // drag its neighbour down to centre against it.
                        Row(
                            horizontalArrangement = Arrangement.spacedBy(ColumnGap),
                            verticalAlignment = Alignment.Top,
                        ) {
                            ids.forEach { id ->
                                SlotRow(
                                    arena = arena,
                                    id = id,
                                    onSet = onSet,
                                    focusRequester = focusX[id - 1],
                                    // Done walks down the sheet: the next
                                    // slot's X, or off the form after the last.
                                    onAdvance = {
                                        if (id < Config.MAX_OBSTACLES) {
                                            focusX[id].requestFocus()
                                        } else {
                                            focusManager.clearFocus()
                                            keyboard?.hide()
                                        }
                                    },
                                )
                            }
                        }
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("CLOSE") } },
    )
}

private const val COLUMNS = 2

/** Width of the B-id label; "B8" in bold mono with a little air. */
private val LabelWidth: Dp = 32.dp

/** Width of one coordinate field - room for two digits and the label. */
private val FieldWidth: Dp = 88.dp

/** Fixed rather than the button's natural width, so the two columns line up exactly. */
private val ButtonWidth: Dp = 64.dp

/** Between the parts of one row. */
private val InnerGap: Dp = 8.dp

/** Between stacked rows. */
private val RowGap: Dp = 8.dp

/** Between the two columns - wider than [InnerGap] so the columns read as two. */
private val ColumnGap: Dp = 24.dp

/** One row's width: label, two fields, the button, and the three gaps between. */
private val RowWidth: Dp = LabelWidth + FieldWidth * 2 + ButtonWidth + InnerGap * 3

/**
 * Material's inset from the dialog edge to its content. Not exposed by the
 * library, so restated here; if it drifts the only symptom is a few dp of
 * slack or wrap at the right edge.
 */
private val DialogPadding: Dp = 24.dp

/** Sized to the grid exactly, so the dialog has no dead space either side. */
private val DialogWidth: Dp = RowWidth * COLUMNS + ColumnGap + DialogPadding * 2

/**
 * One slot. Its draft is the two field strings; the arena's truth for the slot
 * is [Arena.obstacle]'s cell, or null for an empty slot.
 */
@Composable
private fun SlotRow(
    arena: Arena,
    id: Int,
    onSet: (id: Int, cell: Cell?) -> Unit,
    focusRequester: FocusRequester,
    onAdvance: () -> Unit,
) {
    val cell: Cell? = arena.obstacle(id)?.cell
    val currentX = cell?.x?.toString().orEmpty()
    val currentY = cell?.y?.toString().orEmpty()
    // Remembered against the CELL: a successful SET changes it - to a new
    // cell, or to null, or from null - which resets the draft to what the
    // arena now holds, so the row can never show a state the arena has moved
    // on from. Typing alone leaves the cell where it is, so a draft in
    // progress is kept.
    var x by remember(cell) { mutableStateOf(currentX) }
    var y by remember(cell) { mutableStateOf(currentY) }
    // Also keyed on the whole arena: a refusal names another block, and once
    // that block moves or goes the message is stale. The draft is kept.
    var error by remember(cell, arena) { mutableStateOf<String?>(null) }
    val keyboard = LocalSoftwareKeyboardController.current

    // Compared as text, so a half-typed field arms SET the moment it differs
    // and the operator is never left wondering whether the button is dead.
    val dirty = x.trim() != currentX || y.trim() != currentY

    /** Applies the draft. True if the arena was asked to change or nothing needed to. */
    fun apply(): Boolean {
        if (x.isBlank() && y.isBlank()) {
            // Both blank is the remove case, not a validation failure.
            if (cell != null) onSet(id, null)
            return true
        }
        val refusal = obstacleCellError(arena, id, x, y)
        if (refusal != null) {
            error = refusal
            return false
        }
        val target = Cell(x.trim().toInt(), y.trim().toInt())
        if (target == cell) {
            // "012" for 12: legal, nothing to move, so just tidy the text.
            x = currentX
            y = currentY
        } else {
            onSet(id, target)
        }
        return true
    }

    Column(Modifier.width(RowWidth)) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(InnerGap),
        ) {
            Text(
                "B$id",
                fontFamily = DmMono,
                fontWeight = FontWeight.Bold,
                style = MaterialTheme.typography.bodyMedium,
                color = MdpTokens.Ink,
                modifier = Modifier.width(LabelWidth),
            )
            CoordinateField(
                value = x,
                onValueChange = { x = it; error = null },
                label = "X",
                // Next rather than Done: a coordinate is a pair, and the
                // focus should walk to Y on its own. So Done never fires
                // here; the handler is the same one Y uses for symmetry.
                imeAction = ImeAction.Next,
                onDone = { if (apply()) onAdvance() },
                modifier = Modifier.focusRequester(focusRequester),
            )
            CoordinateField(
                value = y,
                onValueChange = { y = it; error = null },
                label = "Y",
                imeAction = ImeAction.Done,
                // Done walks on to the next slot, so a sheet can be typed
                // straight through without touching the screen. A refusal
                // stays put, with its message.
                onDone = { if (apply()) onAdvance() },
            )
            MdpButton(
                // The button is the touch path, and a touch is one slot at a
                // time: apply, and put the keyboard away.
                onClick = { if (apply()) keyboard?.hide() },
                enabled = dirty,
                modifier = Modifier.width(ButtonWidth).height(MdpTokens.TouchTarget),
            ) { Text("SET") }
        }
        error?.let {
            Text(
                it,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.padding(start = LabelWidth + InnerGap, top = 2.dp),
            )
        }
    }
}

@Composable
private fun CoordinateField(
    value: String,
    onValueChange: (String) -> Unit,
    label: String,
    imeAction: ImeAction,
    onDone: () -> Unit,
    modifier: Modifier = Modifier,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        label = { Text(label) },
        singleLine = true,
        // Mono, so 1 and 7 are unmistakable at a glance.
        textStyle = LocalTextStyle.current.copy(fontFamily = DmMono),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number, imeAction = imeAction),
        // Next is left to the default action, which moves focus to the Y
        // field; only Done is ours.
        keyboardActions = KeyboardActions(onDone = { onDone() }),
        // Fixed rather than Material's 280dp minimum, which would make each
        // row wider than the whole dialog has any reason to be.
        modifier = modifier.width(FieldWidth),
    )
}

/**
 * Why a typed coordinate cannot go in slot [id], or null when it can.
 * [Arena.canOccupy] is the arbiter - the same call the drag path makes - so
 * the form and the canvas can never disagree about which cells are legal;
 * what follows it only explains a refusal, in the order it checks.
 *
 * Works for an empty slot as well as a placed one: with no block carrying
 * [id], nothing is excused from the occupancy check, which is right.
 *
 * [x] and [y] are raw field text rather than parsed ints so that "nothing
 * typed" and "not a number" get a message like any other refusal, instead of
 * a SET button that is silently dead. Both blank is not an error - that is
 * the remove case, and the caller decides it before asking here.
 */
fun obstacleCellError(arena: Arena, id: Int, x: String, y: String): String? {
    val last = Config.CELLS - 1
    val cx = x.trim().toIntOrNull()
    val cy = y.trim().toIntOrNull()
    if (cx == null || cy == null) return "Enter 0-$last"
    val cell = Cell(cx, cy)
    if (arena.canOccupy(cell, ignoreId = id)) return null
    if (cx !in 0..last || cy !in 0..last) return "Out of range"
    if (cx < Config.TASK1_START_ZONE_CELLS && cy < Config.TASK1_START_ZONE_CELLS) return "In the start zone"
    val holder = arena.obstacles.firstOrNull { it.id != id && it.cell == cell }
    // The fallback only fires if canOccupy grows a rule this list does not
    // know about - better a vague message than "Occupied by Bnull".
    return holder?.let { "Occupied by B${it.id}" } ?: "Not allowed here"
}
