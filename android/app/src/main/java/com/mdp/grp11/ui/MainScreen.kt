package com.mdp.grp11.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.displayCutout
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBars
import androidx.compose.foundation.layout.union
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import com.mdp.grp11.config.Config
import com.mdp.grp11.connection.ConnectionState
import com.mdp.grp11.session.RunKind
import com.mdp.grp11.session.RunTimes
import com.mdp.grp11.ui.theme.DmMono
import com.mdp.grp11.ui.theme.MdpTokens
import com.mdp.grp11.ui.theme.hardSurface

/** Gap between the screen's major regions. */
private val RegionGap: Dp = 12.dp

/** Gap between stacked controls within a region. */
private val ControlGap: Dp = 8.dp

/**
 * Split of the panel column between the status/compass slot and the raw log.
 *
 * Both PROPORTIONAL: given `weight(1f)` after a stack of fixed-height children,
 * the log's share silently resolves to zero the moment those children
 * over-commit the height. A share of the remaining space cannot vanish that
 * way. The log takes the larger one - it is a scrolling list that gets more
 * useful with height, while the status card tops out at three lines.
 */
private const val STATUS_SLOT_WEIGHT = 1f
private const val LOG_SLOT_WEIGHT = 1.4f

/**
 * The operating surface for a run: arena on the left, everything the operator
 * drives the robot with on the right, nothing behind a menu.
 *
 * The right-hand side is TWO columns. As one stack its fixed children sum to
 * more than a landscape tablet's height, which left the raw log no space at all
 * and clipped the status card off the bottom edge. Splitting controls from
 * panels spends horizontal room, which this side has, rather than vertical,
 * which it does not - and without shrinking the arena or any touch target.
 *
 * Nothing here scrolls. A control that has to be scrolled back into view is a
 * control that is missing at the moment it is needed, and STOP is on this
 * screen.
 *
 * Every control that transmits is gated on a live link. A button that looks
 * armed but sends nothing is the worst thing to hand someone under a clock.
 */
@Composable
fun MainScreen(
    vm: ArenaViewModel,
    state: ConnectionState,
    onOpenPicker: () -> Unit,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val arena by vm.arena.collectAsState()
    val selected by vm.selectedId.collectAsState()
    val status by vm.statusText.collectAsState()
    val targetLine by vm.targetLine.collectAsState()
    val traffic by vm.traffic.collectAsState()
    val runTimes by vm.runTimes.collectAsState()
    val savedLayouts by vm.savedLayouts.collectAsState()

    val connected = state is ConnectionState.Connected

    var showImagePool by remember { mutableStateOf(false) }
    if (showImagePool) {
        ImagePoolDialog(
            // Read from the arena rather than a separate tally, so the chart
            // and the blocks can never disagree about what has been found.
            found = arena.obstacles.mapNotNull { it.target?.id }.toSet(),
            onDismiss = { showImagePool = false },
        )
    }

    // Back is destructive here: it finishes the Activity and takes every placed
    // obstacle and the whole traffic log with it, while the connection and the
    // run clocks are process-scoped and survive - so the app comes back looking
    // connected and mid-run over an empty board. Its trigger is a left-edge
    // swipe, the same motion used to drag a block. Swallowed, with a word to
    // the operator so a dead gesture does not read as a hung app.
    BackHandler {
        // Front-loaded: the status line is one line and this panel is narrow,
        // so the words that matter go before any ellipsis.
        vm.note("Back disabled - use Home to exit")
    }

    Row(
        modifier
            .fillMaxSize()
            // System bars and the cutout, but NOT the IME. Edge-to-edge is
            // enforced from Android 15, so without this the toolbar sits under
            // the status bar. The IME is excluded because the only text entry
            // is inside a dialog, which is its own window - including it would
            // let that keyboard squash this layout behind the dialog.
            .windowInsetsPadding(WindowInsets.systemBars.union(WindowInsets.displayCutout))
            .padding(RegionGap),
        horizontalArrangement = Arrangement.spacedBy(RegionGap),
    ) {
        // Sized by HEIGHT, not by a share of the width. A cell is only ~4.7mm
        // against Material's 7.6mm touch minimum, so every pixel of grid is
        // precision, and `weight(1f)` on a 16:10 tablet would size the arena by
        // half the width - 20% smaller linearly for nothing.
        //
        // The square is measured here rather than by `aspectRatio(1f)` on the
        // column: that claimed a full-height square of width while the canvas
        // inside only ever got the height left under the toolbar, leaving the
        // difference as blank margin either side of the grid.
        BoxWithConstraints(Modifier.fillMaxHeight()) {
            // Floored so a pathological viewport cannot ask for a negative
            // size. The manifest locks this to landscape and forbids resizing,
            // so in practice it is ~636dp.
            val side = (maxHeight - MdpTokens.TouchTarget - ControlGap)
                .coerceAtLeast(0.dp)
            Column(
                Modifier.fillMaxHeight().width(side),
                verticalArrangement = Arrangement.spacedBy(ControlGap),
            ) {
                ArenaToolbar(
                    saved = savedLayouts,
                    onSave = vm::saveLayout,
                    onLoad = vm::loadLayout,
                    onDelete = vm::deleteLayout,
                    onReset = vm::resetArena,
                    onShowImages = { showImagePool = true },
                )
                // Given the square explicitly: ArenaCanvas's own
                // min(width, height) would leave a strip of canvas outside the
                // drawn grid, and cell lookup clamps - so a tap in that strip
                // would silently place a block against the edge.
                ArenaCanvas(
                    arena = arena,
                    selectedId = selected,
                    onPlace = vm::place,
                    onSelect = vm::select,
                    onDragTo = vm::dragTo,
                    onDropOutside = vm::dropOutside,
                    onCommit = vm::commit,
                    modifier = Modifier.size(side),
                )
            }
        }

        Column(
            Modifier.fillMaxHeight().weight(1f),
            verticalArrangement = Arrangement.spacedBy(ControlGap),
        ) {
            ConnectionBar(
                state = state,
                obstacleCount = arena.obstacles.size,
                onOpenPicker = onOpenPicker,
                onRetry = onRetry,
            )

            Row(
                Modifier.fillMaxWidth().weight(1f),
                horizontalArrangement = Arrangement.spacedBy(ControlGap),
            ) {
                // Panels first, controls second, so the controls sit against
                // the screen's outer edge - what a thumb reaches without
                // regripping a tablet held in two hands. Everything in this
                // column is read-only.
                Column(
                    Modifier.fillMaxHeight().weight(1f),
                    verticalArrangement = Arrangement.spacedBy(ControlGap),
                ) {
                    // The compass replaces the status card rather than stacking
                    // with it - a permanent slot would cost the log a third of
                    // its height for something visible seconds at a time.
                    val sel = selected?.let { arena.obstacle(it) }
                    if (sel != null) {
                        FaceCompass(
                            label = "B${sel.id}",
                            current = sel.imageFace,
                            onPick = vm::pickFace,
                            onDone = vm::clearSelection,
                            modifier = Modifier.fillMaxWidth().weight(STATUS_SLOT_WEIGHT),
                        )
                    } else {
                        StatusPanel(
                            status,
                            targetLine,
                            Modifier.fillMaxWidth().weight(STATUS_SLOT_WEIGHT),
                        )
                    }
                    BtLogPanel(traffic, Modifier.fillMaxWidth().weight(LOG_SLOT_WEIGHT))
                }

                // The two fixed blocks take what they need and the pad takes
                // the rest, so this column can neither overflow nor leave a
                // band of empty screen under the last button.
                Column(
                    Modifier.fillMaxHeight().weight(1f),
                    verticalArrangement = Arrangement.spacedBy(ControlGap),
                ) {
                    // Directly above the buttons that start the runs they time.
                    RunTimesRow(runTimes, onReset = vm::resetRunClock)
                    TaskControls(
                        enabled = connected,
                        running = runTimes.running,
                        onStart = vm::startRun,
                        onStop = vm::endRun,
                        onSendArena = vm::sendArena,
                    )
                    ControlPad(
                        enabled = connected,
                        onMove = vm::move,
                        onStop = { vm.move(Config.moveTokens.stop) },
                        modifier = Modifier.fillMaxWidth().weight(1f),
                    )
                }
            }
        }
    }
}

/**
 * Fill, label and status-dot colour per connection state. Colour first and
 * words second, which is the right way round for something read at a glance
 * across a table - green is what the operator is looking for.
 *
 * Failed shares Reconnecting's red: both mean the link is not carrying traffic,
 * and the difference is already in the label and in the RETRY button beside it.
 */
private data class ConnectionStyle(val container: Color, val content: Color, val dot: Color)

private fun connectionStyle(state: ConnectionState): ConnectionStyle = when (state) {
    // Paper rather than the background's cream: cream on cream reads as a hole
    // rather than as a card.
    is ConnectionState.Idle -> ConnectionStyle(MdpTokens.Paper, MdpTokens.Ink, MdpTokens.Muted)
    is ConnectionState.Connecting -> ConnectionStyle(MdpTokens.Yellow, MdpTokens.Ink, MdpTokens.Ink)
    is ConnectionState.Connected -> ConnectionStyle(MdpTokens.Green, MdpTokens.Ink, MdpTokens.Ink)
    is ConnectionState.Reconnecting -> ConnectionStyle(MdpTokens.Pink, Color.White, Color.White)
    is ConnectionState.Failed -> ConnectionStyle(MdpTokens.Pink, Color.White, Color.White)
}

/**
 * Connection state, the retry escape hatch and the obstacle count, on one line.
 * The count is status rather than a control, and does not earn a row of its own.
 */
@Composable
private fun ConnectionBar(
    state: ConnectionState,
    obstacleCount: Int,
    onOpenPicker: () -> Unit,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val style = connectionStyle(state)

    Row(
        modifier.fillMaxWidth().height(MdpTokens.TouchTarget),
        horizontalArrangement = Arrangement.spacedBy(ControlGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        MdpButton(
            onClick = onOpenPicker,
            container = style.container,
            contentColor = style.content,
            modifier = Modifier.weight(1f).fillMaxHeight(),
        ) {
            // The status dot is what makes this read as a state readout rather
            // than as a button that happens to be coloured in.
            Box(Modifier.size(9.dp).clip(CircleShape).background(style.dot))
            Spacer(Modifier.width(10.dp))
            // Failed carries a raw exception message, unbounded by anything
            // this app controls, and the row is a fixed height - so an
            // unbounded label wraps and clips mid-word, taking the device name
            // with it.
            Text(
                connectionLabel(state),
                // Mono: this is an address, not prose.
                style = MaterialTheme.typography.labelMedium.copy(
                    fontSize = 13.sp,
                    letterSpacing = 0.04.em,
                ),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                // Takes the rest of the row so the dot stays pinned left and
                // the ellipsis lands at the true edge of the space.
                modifier = Modifier.weight(1f),
            )
        }

        // A permanently failed connect deliberately does not auto-retry:
        // retrying after an explicit attempt failed masks a real fault - wrong
        // device, radio off, peer not listening - instead of showing it. That
        // makes a visible way forward this screen's job, or the operator is
        // stranded with nothing to do but restart the app mid-run.
        if (state is ConnectionState.Failed) {
            MdpButton(
                onClick = onRetry,
                container = MdpTokens.Pink,
                modifier = Modifier.fillMaxHeight(),
            ) { Text("RETRY") }
        }

        // White, so it does not compete for the glance with a bar that is
        // already carrying colour as meaning. The one exception is the flip at
        // eight of eight: that is the moment placement stops being routine, and
        // this count is the only thing on screen that knows.
        val full = obstacleCount >= Config.MAX_OBSTACLES
        Row(
            Modifier
                .fillMaxHeight()
                .hardSurface(shadow = MdpTokens.HardShadowSmall)
                .clip(RoundedCornerShape(MdpTokens.CornerRadius))
                .background(if (full) MdpTokens.Pink else MdpTokens.Paper)
                .padding(horizontal = 14.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                "OBSTACLES $obstacleCount / ${Config.MAX_OBSTACLES}",
                style = MaterialTheme.typography.labelMedium.copy(
                    fontSize = 12.sp,
                    letterSpacing = 0.06.em,
                ),
                color = if (full) Color.White else MdpTokens.Ink,
                maxLines = 1,
            )
        }
    }
}

/** Both scored clocks side by side, with the running one called out. */
@Composable
private fun RunTimesRow(
    times: RunTimes,
    onReset: (RunKind) -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(ControlGap)) {
        RunTimeReadout(
            label = "IMAGE REC",
            elapsedMs = times.exploration,
            running = times.running == RunKind.Exploration,
            onReset = { onReset(RunKind.Exploration) },
            modifier = Modifier.weight(1f),
        )
        RunTimeReadout(
            label = "FASTEST",
            elapsedMs = times.fastestCar,
            running = times.running == RunKind.FastestCar,
            onReset = { onReset(RunKind.FastestCar) },
            modifier = Modifier.weight(1f),
        )
    }
}

/**
 * One clock. Long-press to zero it - a gesture rather than a button because two
 * cards already split ~260dp of width. The cost is discoverability, paid back
 * by the hint, which appears only when the gesture would do something.
 *
 * `combinedClickable` rather than `pointerInput`: it brings the ripple, the
 * accessibility long-click action and the correct touch slop with it.
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun RunTimeReadout(
    label: String,
    elapsedMs: Long,
    running: Boolean,
    onReset: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val haptics = LocalHapticFeedback.current
    // Resetting a running clock is refused in the ViewModel; the gesture is
    // withdrawn here too, so the hint never invites a press that does nothing.
    val resettable = !running && elapsedMs > 0L

    // The running clock takes a green shadow and an idle one plain ink, so
    // which task is live reads from across the room rather than only from the
    // colour of two small words.
    //
    // Light rather than dark: these sit in a column of pale controls, and dark
    // blocks in the middle of it pull the eye off the buttons.
    Column(
        modifier
            .hardSurface(
                shadow = MdpTokens.HardShadowSmall,
                shadowColor = if (running) MdpTokens.Green else MdpTokens.Ink,
            )
            .clip(RoundedCornerShape(MdpTokens.CornerRadius))
            .background(MdpTokens.Paper)
            .combinedClickable(
                enabled = resettable,
                onClick = {},   // tap does nothing - only the long-press resets
                onLongClick = {
                    haptics.performHapticFeedback(HapticFeedbackType.LongPress)
                    onReset()
                },
            )
    ) {
        // Stacked, not a SpaceBetween row: each card is only ~126dp wide, and
        // SpaceBetween anchors its children at either end whether or not they
        // collide. On separate lines the worst a large font scale can do is
        // ellipsise.
        Column(Modifier.fillMaxWidth().padding(ControlGap)) {
            Text(
                label,
                style = MaterialTheme.typography.labelMedium,
                maxLines = 1,
                color = if (running) MdpTokens.Green else MdpTokens.Muted,
            )
            Text(
                formatElapsed(elapsedMs),
                style = MaterialTheme.typography.titleMedium,
                fontFamily = DmMono,
                fontWeight = if (running) FontWeight.Bold else FontWeight.Normal,
                maxLines = 1,
                color = if (running) MdpTokens.Green else MdpTokens.Ink,
            )
            // Always laid out, only sometimes visible. Composed conditionally,
            // it grew the card the moment a clock stopped, shoving the pad down
            // the column under the operator's thumb. The same string and style
            // with the colour dropped reserves the space by construction -
            // unlike a blank string, which relies on how empty text measures.
            //
            // Hidden from the screen reader when invisible, so a gesture that
            // is refused is not announced as available.
            Text(
                "HOLD TO RESET",
                modifier = if (resettable) Modifier else Modifier.clearAndSetSemantics {},
                // Tracking dropped: labelSmall's 0.1em across 13 characters is
                // enough extra width to ellipsise the hint in a ~126dp card.
                style = MaterialTheme.typography.labelSmall.copy(letterSpacing = 0.sp),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                color = if (resettable) MdpTokens.Muted else Color.Transparent,
            )
        }
    }
}

/**
 * A run-timer reading, in milliseconds, as mm:ss.
 *
 * Minutes are not wrapped at 60: a clock left running for over an hour must
 * read 61:20, never 01:20, which would understate a run by a full hour.
 */
fun formatElapsed(elapsedMs: Long): String {
    val totalSeconds = elapsedMs / Config.MILLIS_PER_SECOND
    val minutes = totalSeconds / Config.SECONDS_PER_MINUTE
    val seconds = totalSeconds % Config.SECONDS_PER_MINUTE
    return "%02d:%02d".format(minutes, seconds)
}

private fun connectionLabel(state: ConnectionState): String = when (state) {
    is ConnectionState.Idle -> "NOT CONNECTED"
    is ConnectionState.Connecting -> "CONNECTING…"
    is ConnectionState.Connected -> state.device.name
    is ConnectionState.Reconnecting -> "RECONNECTING · RETRY ${state.attempt}"
    is ConnectionState.Failed -> "FAILED · ${state.reason}"
}
