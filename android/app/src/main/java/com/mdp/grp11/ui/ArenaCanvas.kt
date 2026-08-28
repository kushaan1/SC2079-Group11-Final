package com.mdp.grp11.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.text.TextMeasurer
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import com.mdp.grp11.arena.Arena
import com.mdp.grp11.arena.Cell
import com.mdp.grp11.arena.Grid
import com.mdp.grp11.arena.Obstacle
import com.mdp.grp11.arena.RobotPose
import com.mdp.grp11.config.Config
import com.mdp.grp11.protocol.Face
import com.mdp.grp11.ui.theme.MdpTokens
import kotlin.math.min

/**
 * A rendered cell (~33px) is only ~4.7mm across - about 61% of Material's
 * 48dp (~7.6mm) minimum touch target - so the tappable radius has to reach
 * further than the cell it draws. [hitTest] is a pure function with no
 * [androidx.compose.ui.unit.Density] to convert a real dp constant into
 * pixels, so the radius is instead expressed as a ratio of the rendered
 * cell size: half of 48dp in mm (~3.8mm) over the cell's physical size
 * (~4.7mm).
 */
private const val HIT_RADIUS_RATIO = 0.82f

/** Cell index step between heavier gridlines. Purely a visual aid. */
private const val MAJOR_GRIDLINE_INTERVAL = 5

/** Face bar thickness as a fraction of the cell it is drawn against. */
private const val FACE_BAR_THICKNESS_RATIO = 0.18f

/** Target id label size as a fraction of the cell it is drawn in. */
private const val TARGET_LABEL_SIZE_RATIO = 0.5f

/** Minor gridline alpha, dimmed relative to the major lines. */
private const val MINOR_GRIDLINE_ALPHA = 0.25f

/** Start zone tint alpha over its base colour. */
private const val START_ZONE_ALPHA = 0.3f

/**
 * T1 START label size as a fraction of the cell. Sits in the one-cell band
 * between the top of the robot's starting footprint and the top of the zone,
 * so it cannot grow much.
 */
private const val START_ZONE_LABEL_SIZE_RATIO = 0.3f

/**
 * Axis label size as a fraction of the cell. Smaller than the target label -
 * this is reference ruling, not primary content - but two digits still have to
 * fit inside a single ~33px cell.
 */
private const val AXIS_LABEL_SIZE_RATIO = 0.3f

/** Gap between an axis label and the grid edge it rules, as a cell fraction. */
private const val AXIS_LABEL_INSET_RATIO = 0.08f

/**
 * Obstacle id badge size as a fraction of the cell. One size in every state:
 * a label that resizes when a target arrives is one the operator has to
 * re-find, and the badge answers "which block is this" either way.
 *
 * KNOWN COST: [TARGET_LABEL_SIZE_RATIO] centres two digits across half the
 * cell, leaving about a fifth either side, so at this size the badge clips the
 * corner of those digits once a target is found. Accepted in favour of a
 * constant size.
 */
private const val OBSTACLE_ID_SIZE_RATIO = 0.34f

/** Gap between the obstacle id badge and the cell corner it sits in. */
private const val OBSTACLE_ID_INSET_RATIO = 0.06f

/** Drag-out tint alpha over the whole canvas. */
private const val DRAG_OUT_TINT_ALPHA = 0.14f

/** RELEASE TO REMOVE label size as a fraction of gridPx (the whole canvas,
 *  not a cell - this banner spans the arena, not one block). */
private const val DRAG_OUT_LABEL_SIZE_RATIO = 0.045f

/** RELEASE TO REMOVE pill padding, horizontal and vertical, as gridPx fractions. */
private const val DRAG_OUT_PILL_PAD_H_RATIO = 0.025f
private const val DRAG_OUT_PILL_PAD_V_RATIO = 0.012f

/**
 * Nearest obstacle whose centre is within the touch radius, or null.
 * Radius scales with the grid so it stays a constant physical size.
 */
fun hitTest(arena: Arena, px: Float, py: Float, gridPx: Float): Obstacle? {
    val cellPx = gridPx / Config.CELLS
    val radius = cellPx * HIT_RADIUS_RATIO
    var best: Obstacle? = null
    var bestD = radius * radius
    arena.obstacles.forEach { o ->
        val (cx, cy) = Grid.centreOf(o.cell.x, o.cell.y, gridPx)
        val d = (px - cx) * (px - cx) + (py - cy) * (py - cy)
        if (d <= bestD) { bestD = d; best = o }
    }
    return best
}

/**
 * Canvas pixels of the robot footprint's top-left corner. Shared by the
 * drawing and the hit test on purpose - two copies of this arithmetic would
 * drift, and the failure mode is a robot you can see but cannot grab.
 */
private fun robotTopLeft(pose: RobotPose, gridPx: Float): Offset {
    // The pose names the footprint's CENTRE, so back off half a footprint in
    // each direction. Going through Grid keeps the y-flip in the one place
    // that is allowed to know about it.
    val half = Config.ROBOT_SIZE_CELLS / 2f
    return Offset(
        Grid.toCanvasX(pose.x - half, gridPx),
        Grid.toCanvasY(pose.y + half, gridPx),
    )
}

/**
 * Whether a touch lands on the robot. Plain rectangle containment, with none
 * of [hitTest]'s generous radius: the footprint is 3x3 cells - about 14mm
 * square, comfortably past Material's touch minimum - so nothing needs to
 * reach beyond it, and a radius would let the robot steal taps meant for the
 * ground beside it.
 *
 * Stays AXIS-ALIGNED even though the body is drawn rotated. A rotated square's
 * corner tips fall outside this box, so at a diagonal heading the very tips
 * are not grabbable - a few pixels on a 99px target, and not worth the
 * arithmetic.
 */
fun hitsRobot(pose: RobotPose, px: Float, py: Float, gridPx: Float): Boolean {
    val (left, top) = robotTopLeft(pose, gridPx)
    val side = gridPx / Config.CELLS * Config.ROBOT_SIZE_CELLS
    return px >= left && px < left + side && py >= top && py < top + side
}

/** What a touch landed on. Null is bare ground. */
sealed interface ArenaHit {
    data class Block(val id: Int) : ArenaHit
    data object Robot : ArenaHit
}

/**
 * Resolves a touch against everything drawn on the arena, obstacles first.
 *
 * A block is one cell against the robot's nine, so ranking the robot higher
 * would make any block beneath it unreachable, while ranking it lower costs
 * the robot eight-ninths of a grab area it has in abundance.
 *
 * Both gestures go through here rather than each ranking for itself - a tap
 * and a drag that disagreed about what is under the finger would be a very
 * confusing thing to debug.
 */
fun hitArena(arena: Arena, px: Float, py: Float, gridPx: Float): ArenaHit? {
    hitTest(arena, px, py, gridPx)?.let { return ArenaHit.Block(it.id) }
    if (hitsRobot(arena.robot, px, py, gridPx)) return ArenaHit.Robot
    return null
}

/**
 * The arena. A tap on empty ground places a new block; a tap on a block
 * selects it (opening the face compass, C.7) without transmitting anything.
 * Dragging moves a block locally; [onCommit] fires only on finger-lift,
 * which is the sole place C.6's coordinates are sent - never mid-drag.
 *
 * The robot is draggable on the same terms, and [onSelectRobot] binds the
 * compass to its heading. What a touch lands on is decided by [hitArena],
 * which both gestures share.
 */
@Composable
fun ArenaCanvas(
    arena: Arena,
    selection: Selection?,
    onPlace: (Cell) -> Unit,
    onSelect: (Int) -> Unit,
    onDragTo: (Int, Cell) -> Unit,
    onDropOutside: (Int) -> Unit,
    onCommit: (Int) -> Unit,
    onSelectRobot: () -> Unit,
    onDragRobotTo: (Float, Float) -> Unit,
    onCommitRobot: () -> Unit,
    modifier: Modifier = Modifier,
) {
    // Captured in onSizeChanged, not the draw lambda: pointerInput reads this
    // to hit-test taps, and it runs at a different time than drawing does. A
    // value assigned during drawing would be stale/uninitialised on first touch.
    var gridPx by remember { mutableStateOf(0f) }
    var dragging by remember { mutableStateOf<ArenaHit?>(null) }
    var outside by remember { mutableStateOf(false) }
    val textMeasurer = rememberTextMeasurer()

    // arena is deliberately NOT a pointerInput key. A drag produces a new Arena
    // on every cell it crosses, and detectDragGestures is one long coroutine
    // per gesture - so keying on arena cancels and relaunches it mid-drag, and
    // the relaunch waits on awaitFirstDown(), which never fires again while the
    // same finger is down. The block stops tracking, and onDragEnd (hence the
    // only path that transmits coordinates) never runs. gridPx stays a key,
    // since a resize genuinely should reset gestures.
    val currentArena by rememberUpdatedState(arena)

    Box(modifier) {
        Canvas(
            Modifier
                .fillMaxSize()
                .onSizeChanged { gridPx = min(it.width, it.height).toFloat() }
                .pointerInput(gridPx) {
                    detectTapGestures { pos ->
                        when (val hit = hitArena(currentArena, pos.x, pos.y, gridPx)) {
                            is ArenaHit.Block -> onSelect(hit.id)
                            ArenaHit.Robot -> onSelectRobot()
                            null -> onPlace(cellOf(pos, gridPx))
                        }
                    }
                }
                .pointerInput(gridPx) {
                    detectDragGestures(
                        onDragStart = { pos ->
                            dragging = hitArena(currentArena, pos.x, pos.y, gridPx)
                            outside = false
                        },
                        onDrag = { change, _ ->
                            val p = change.position
                            when (val t = dragging) {
                                null -> Unit
                                is ArenaHit.Block -> {
                                    outside = p.x < 0 || p.y < 0 || p.x > gridPx || p.y > gridPx
                                    if (!outside) onDragTo(t.id, cellOf(p, gridPx))
                                }
                                // No drag-out for the robot: there is no such
                                // thing as removing it, so a finger past the
                                // edge parks it against the wall instead
                                // (Arena.moveRobot clamps the footprint).
                                ArenaHit.Robot -> {
                                    // A continuous point, not a cell: the robot
                                    // is drawn at fractional positions, so
                                    // snapping the drag would make it stutter
                                    // between cells for no reason.
                                    val (rx, ry) = Grid.pointAt(p.x, p.y, gridPx)
                                    onDragRobotTo(rx, ry)
                                }
                            }
                        },
                        onDragEnd = {
                            when (val t = dragging) {
                                null -> Unit
                                is ArenaHit.Block ->
                                    if (outside) onDropOutside(t.id) else onCommit(t.id)
                                ArenaHit.Robot -> onCommitRobot()
                            }
                            dragging = null
                            outside = false
                        },
                        onDragCancel = { dragging = null; outside = false },
                    )
                }
        ) {
            val g = min(size.width, size.height)
            drawGrid(g)
            drawStartZone(g, textMeasurer)
            drawAxisLabels(g, textMeasurer)
            arena.obstacles.forEach {
                drawObstacle(it, g, selection == Selection.Obstacle(it.id), textMeasurer)
            }
            drawRobot(arena.robot, g, selection == Selection.Robot)
            // Signalled arena-wide on purpose: a ~33px block is far too
            // small an affordance, so this flags the whole square the operator
            // is already looking at rather than the dragged block.
            if (outside) drawDragOutOverlay(g, textMeasurer)
        }
    }
}

private fun cellOf(pos: Offset, gridPx: Float): Cell {
    val (x, y) = Grid.cellAt(pos.x, pos.y, gridPx)
    return Cell(x, y)
}

private fun DrawScope.drawGrid(gridPx: Float) {
    val cell = gridPx / Config.CELLS
    drawRect(MdpTokens.Paper, size = Size(gridPx, gridPx))
    val majorStroke = MdpTokens.GridMajorStroke.toPx()
    val minorStroke = MdpTokens.GridStroke.toPx()
    for (i in 0..Config.CELLS) {
        val major = i % MAJOR_GRIDLINE_INTERVAL == 0
        val colour = if (major) MdpTokens.Muted else MdpTokens.Muted.copy(alpha = MINOR_GRIDLINE_ALPHA)
        val w = if (major) majorStroke else minorStroke
        drawLine(colour, Offset(i * cell, 0f), Offset(i * cell, gridPx), w)
        drawLine(colour, Offset(0f, i * cell), Offset(gridPx, i * cell), w)
    }
    // Drawn INSIDE the grid's own bounds: the canvas box is sized exactly to
    // the grid, so an outset frame would be clipped, and insetting by half the
    // stroke keeps the whole line visible without moving a cell. A frame only -
    // no outer gutters, which would shrink the playable area.
    val frame = MdpTokens.BorderHeavy.toPx()
    drawRect(
        MdpTokens.Ink,
        topLeft = Offset(frame / 2, frame / 2),
        size = Size(gridPx - frame, gridPx - frame),
        style = Stroke(frame),
    )
}

private fun DrawScope.drawStartZone(gridPx: Float, textMeasurer: TextMeasurer) {
    val cell = gridPx / Config.CELLS
    val side = cell * Config.TASK1_START_ZONE_CELLS
    val top = gridPx - side
    drawRect(
        MdpTokens.Yellow.copy(alpha = START_ZONE_ALPHA),
        topLeft = Offset(0f, top),
        size = Size(side, side),
    )
    // Dashed on its top and right edges only - the other two are the arena
    // frame. The tint alone reads as a slightly yellow corner; the dashes say
    // "reserved", which is what it is, and a solid line would be mistaken for
    // an obstacle boundary.
    val stroke = MdpTokens.GridMajorStroke.toPx()
    val dash = PathEffect.dashPathEffect(floatArrayOf(cell / 4f, cell / 4f))
    drawLine(
        MdpTokens.Ink, Offset(0f, top), Offset(side, top),
        strokeWidth = stroke, pathEffect = dash,
    )
    drawLine(
        MdpTokens.Ink, Offset(side, top), Offset(side, gridPx),
        strokeWidth = stroke, pathEffect = dash,
    )

    // Labelled because this square is TASK 1's 40cm start zone specifically.
    // Task 2 starts in a carpark with no arena position at all, so during a
    // fastest-car run an unlabelled shaded corner would read as "the start is
    // here" - a claim nothing in the briefing supports.
    val label = textMeasurer.measure(
        "Task 1",
        TextStyle(
            color = MdpTokens.Muted,
            fontSize = (cell * START_ZONE_LABEL_SIZE_RATIO).toDp().toSp(),
            fontWeight = FontWeight.Normal,
        ),
    )
    val inset = cell * AXIS_LABEL_INSET_RATIO
    drawText(label, topLeft = Offset(inset, top + inset))
}

/**
 * 0..19 rulers along the bottom (columns, x) and left (rows, y) edges, drawn
 * inset from the outer gridline rather than in a margin - the canvas box is
 * sized exactly to the grid, so there is no space outside it for labels
 * without shrinking the playable area.
 */
private fun DrawScope.drawAxisLabels(gridPx: Float, textMeasurer: TextMeasurer) {
    val cell = gridPx / Config.CELLS
    val inset = cell * AXIS_LABEL_INSET_RATIO
    val style = TextStyle(
        color = MdpTokens.Muted,
        fontSize = (cell * AXIS_LABEL_SIZE_RATIO).toDp().toSp(),
        fontWeight = FontWeight.Bold,
    )

    // Columns (x): not y, so no Grid lookup - x reads the same in arena and
    // canvas space. Row 0 in arena terms is the BOTTOM edge on screen.
    val bottomRowTop = Grid.toCanvasRow(0) * cell
    for (x in 0 until Config.CELLS) {
        val layout = textMeasurer.measure(x.toString(), style)
        drawText(
            layout,
            topLeft = Offset(
                x * cell + (cell - layout.size.width) / 2f,
                bottomRowTop + cell - layout.size.height - inset,
            ),
        )
    }

    // Rows (y): MUST run in arena order (0 at the bottom, 19 at the top),
    // not canvas order - Grid.toCanvasRow is the only place that flip
    // happens, so the loop itself stays a plain 0..19 arena-space count.
    for (y in 0 until Config.CELLS) {
        val layout = textMeasurer.measure(y.toString(), style)
        val rowTop = Grid.toCanvasRow(y) * cell
        drawText(layout, topLeft = Offset(inset, rowTop + (cell - layout.size.height) / 2f))
    }
}

private fun DrawScope.drawObstacle(
    o: Obstacle,
    gridPx: Float,
    selected: Boolean,
    textMeasurer: TextMeasurer,
) {
    val cell = gridPx / Config.CELLS
    val left = o.cell.x * cell
    val top = Grid.toCanvasRow(o.cell.y) * cell
    val fill = if (o.target != null) MdpTokens.Pink else MdpTokens.Blue
    drawRect(fill, Offset(left, top), Size(cell, cell))
    // Ink outline, as every block, card and chip in the design carries. On a
    // 29px cell this is also what separates two adjacent blocks from one
    // double-wide smear, which the flat fill alone did not.
    val edge = MdpTokens.GridMajorStroke.toPx()
    drawRect(
        MdpTokens.Ink,
        Offset(left + edge / 2, top + edge / 2),
        Size(cell - edge, cell - edge),
        style = Stroke(edge),
    )
    if (selected) {
        val s = MdpTokens.SelectionStroke.toPx()
        drawRect(
            MdpTokens.Yellow,
            Offset(left - s, top - s),
            Size(cell + 2 * s, cell + 2 * s),
            style = Stroke(s),
        )
    }
    // What WE annotated (C.7), outbound.
    o.imageFace?.let { face -> drawFaceBar(face, left, top, cell, MdpTokens.Yellow) }
    o.target?.let { target ->
        // What the ROBOT reported (C.9), inbound - distinct from imageFace above.
        target.face?.let { face -> drawFaceBar(face, left, top, cell, MdpTokens.Green) }
        // C.9: the recognised numeric target id must appear on its block.
        drawTargetLabel(target.id, left, top, cell, textMeasurer)
    }
    // C.5 requires every block to be numbered, always - not only once a
    // target is found. Drawn last, on top of everything above, so it stays
    // legible over a face bar it happens to share a corner with.
    drawObstacleIdLabel(o, left, top, cell, textMeasurer)
}

/**
 * One edge of a block, coloured by WHO said so: Yellow for the face the
 * operator annotated, Green for the one the robot reported alongside a target.
 *
 * Two facts that look alike and are not - the whole point of keeping
 * `imageFace` and `target.face` as separate fields - so drawing both in one
 * colour made the block claim agreement it might not have. When the two
 * disagree, two differently coloured edges now say so at a glance.
 *
 * If they name the SAME face, Green lands on top: the robot's own report is
 * the one that matters once it exists.
 */
private fun DrawScope.drawFaceBar(
    face: Face,
    left: Float,
    top: Float,
    cell: Float,
    colour: Color,
) {
    val t = cell * FACE_BAR_THICKNESS_RATIO
    val (offset, s) = when (face) {
        Face.N -> Offset(left, top) to Size(cell, t)
        Face.S -> Offset(left, top + cell - t) to Size(cell, t)
        Face.W -> Offset(left, top) to Size(t, cell)
        Face.E -> Offset(left + cell - t, top) to Size(t, cell)
    }
    drawRect(colour, offset, s)
}

private fun DrawScope.drawTargetLabel(
    id: Int,
    left: Float,
    top: Float,
    cell: Float,
    textMeasurer: TextMeasurer,
) {
    val style = TextStyle(
        color = MdpTokens.Paper,
        fontSize = (cell * TARGET_LABEL_SIZE_RATIO).toDp().toSp(),
        fontWeight = FontWeight.Bold,
    )
    val layout = textMeasurer.measure(id.toString(), style)
    drawText(
        layout,
        topLeft = Offset(
            left + (cell - layout.size.width) / 2f,
            top + (cell - layout.size.height) / 2f,
        ),
    )
}

/**
 * C.5: the obstacle's OWN id (1..MAX_OBSTACLES), always drawn - distinct
 * from [drawTargetLabel]'s recognised image id (11..40), which only exists
 * once a TARGET arrives. Small and cornered rather than centred: once a target
 * is found the target id takes the middle and this moves aside, rather than
 * the two competing for the same centred space.
 *
 * Always top-right, always Paper, always the same size. A fixed position,
 * colour and size beat ones that move with state - the operator learns to look
 * in one place for one thing.
 *
 * KNOWN COST: an N or E face bar paints under this corner, and Paper measures
 * 1.62:1 on Yellow and 2.42:1 on Green against a 4.5:1 floor, so the badge is
 * faint on those two faces. Accepted deliberately in favour of one consistent
 * colour. If it needs fixing, inset the badge past FACE_BAR_THICKNESS_RATIO so
 * it clears the bar entirely, rather than reintroducing a colour that changes
 * underneath the operator.
 */
private fun DrawScope.drawObstacleIdLabel(
    o: Obstacle,
    left: Float,
    top: Float,
    cell: Float,
    textMeasurer: TextMeasurer,
) {
    val style = TextStyle(
        color = MdpTokens.Paper,
        fontSize = (cell * OBSTACLE_ID_SIZE_RATIO).toDp().toSp(),
        // Bold, not Medium. This is a small glyph on a saturated fill, and at
        // this size weight buys more legibility than another point of size
        // would - size is what runs into the target digits.
        fontWeight = FontWeight.Bold,
    )
    val layout = textMeasurer.measure(o.id.toString(), style)
    val inset = cell * OBSTACLE_ID_INSET_RATIO
    drawText(layout, topLeft = Offset(left + cell - layout.size.width - inset, top + inset))
}

private fun DrawScope.drawRobot(
    pose: RobotPose,
    gridPx: Float,
    selected: Boolean,
) {
    val c = gridPx / Config.CELLS
    val (left, top) = robotTopLeft(pose, gridPx)
    val side = c * Config.ROBOT_SIZE_CELLS
    val edge = MdpTokens.BorderHeavy.toPx()
    val pivot = Offset(left + side / 2f, top + side / 2f)
    val deg = pose.headingDegrees

    // No drop shadow, unlike every card off-canvas and unlike the blocks: a
    // rotating shadow reads as the robot lifting off the arena rather than
    // driving on it, and the heavy Ink outline already separates it from the
    // grid underneath.
    //
    // Body, arrow and selection ring turn as one, so they cannot drift apart.
    rotate(deg, pivot = pivot) {
        drawRect(MdpTokens.Yellow, Offset(left, top), Size(side, side))
        drawRect(
            MdpTokens.Ink,
            Offset(left + edge / 2, top + edge / 2),
            Size(side - edge, side - edge),
            style = Stroke(edge),
        )
        drawHeadingArrow(left, top, side)

        // Pink, where a selected block gets Yellow: the robot's own fill IS
        // Yellow, so that ring would be invisible on it. Pink also matches the
        // compass card the selection opens.
        if (selected) {
            val sel = MdpTokens.SelectionStroke.toPx()
            drawRect(
                MdpTokens.Pink,
                Offset(left - sel, top - sel),
                Size(side + 2 * sel, side + 2 * sel),
                style = Stroke(sel),
            )
        }
    }
}

/**
 * The heading arrow, drawn pointing NORTH. Its caller rotates it along with
 * the body, so this never needs to know the angle.
 *
 * One triangle rather than four hardcoded paths: a car mid-arc is at an
 * arbitrary angle, and four cases could only round it. It spans the whole
 * footprint rather than sitting inside it, so the heading reads across a room
 * on a projector - do not shrink it.
 *
 * The rotation at the call site needs no y-flip correction, which is worth
 * stating because it looks like an omission: arena headings run clockwise from
 * north, and Compose rotates clockwise on a y-down canvas, so the two senses
 * already agree.
 *
 * NOT covered by a unit test - it is a claim about Compose's rotation sense
 * inside a DrawScope, and there is no Compose test harness in this module. It
 * fails invisibly, being correct at 0/90/180/270 and mirrored everywhere
 * between, so the on-device script checks 45 degrees specifically.
 */
private fun DrawScope.drawHeadingArrow(left: Float, top: Float, side: Float) {
    val path = Path().apply {
        moveTo(left + side / 2f, top)
        lineTo(left + side, top + side)
        lineTo(left, top + side)
        close()
    }
    drawPath(path, MdpTokens.Ink)
}

/**
 * A drag held outside the grid is about to delete its block on release.
 *
 * Tints and outlines the WHOLE canvas with a centred RELEASE TO REMOVE pill,
 * rather than marking the dragged block - which is already off-grid and, at a
 * ~33px cell, too small an affordance regardless. Pink because that is already
 * this app's danger colour.
 */
private fun DrawScope.drawDragOutOverlay(gridPx: Float, textMeasurer: TextMeasurer) {
    drawRect(MdpTokens.Pink.copy(alpha = DRAG_OUT_TINT_ALPHA), size = Size(gridPx, gridPx))
    drawRect(
        MdpTokens.Pink,
        size = Size(gridPx, gridPx),
        style = Stroke(MdpTokens.DangerStroke.toPx()),
    )

    val style = TextStyle(
        color = MdpTokens.Paper,
        fontSize = (gridPx * DRAG_OUT_LABEL_SIZE_RATIO).toDp().toSp(),
        fontWeight = FontWeight.Bold,
    )
    val layout = textMeasurer.measure("RELEASE TO REMOVE", style)
    val padH = gridPx * DRAG_OUT_PILL_PAD_H_RATIO
    val padV = gridPx * DRAG_OUT_PILL_PAD_V_RATIO
    val pillSize = Size(layout.size.width + padH * 2, layout.size.height + padV * 2)
    val pillTopLeft = Offset((gridPx - pillSize.width) / 2f, (gridPx - pillSize.height) / 2f)
    drawRoundRect(
        MdpTokens.Pink,
        topLeft = pillTopLeft,
        size = pillSize,
        cornerRadius = CornerRadius(pillSize.height / 2f, pillSize.height / 2f),
    )
    drawText(layout, topLeft = pillTopLeft + Offset(padH, padV))
}
