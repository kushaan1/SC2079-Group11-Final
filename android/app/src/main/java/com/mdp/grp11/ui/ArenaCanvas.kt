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
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
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
 * Axis label size as a fraction of the cell. Smaller than the target label -
 * this is reference ruling, not primary content - but two digits still have to
 * fit inside a single ~33px cell.
 */
private const val AXIS_LABEL_SIZE_RATIO = 0.3f

/** Gap between an axis label and the grid edge it rules, as a cell fraction. */
private const val AXIS_LABEL_INSET_RATIO = 0.08f

/**
 * Obstacle id badge size as a fraction of the cell, with no target found. The
 * badge is the block's only label then, so it takes a readable share of it.
 */
private const val OBSTACLE_ID_SIZE_RATIO = 0.34f

/**
 * And the size once a target is found. Target ids are always TWO digits and
 * [TARGET_LABEL_SIZE_RATIO] centres them across half the cell, leaving about a
 * fifth either side - anything larger overlaps those digits rather than sitting
 * beside them, which is why this cannot be a single ratio.
 */
private const val OBSTACLE_ID_SIZE_RATIO_WITH_TARGET = 0.20f

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
 * The arena. A tap on empty ground places a new block; a tap on a block
 * selects it (opening the face compass, C.7) without transmitting anything.
 * Dragging moves a block locally; [onCommit] fires only on finger-lift,
 * which is the sole place C.6's coordinates are sent - never mid-drag.
 */
@Composable
fun ArenaCanvas(
    arena: Arena,
    selectedId: Int?,
    onPlace: (Cell) -> Unit,
    onSelect: (Int) -> Unit,
    onDragTo: (Int, Cell) -> Unit,
    onDropOutside: (Int) -> Unit,
    onCommit: (Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    // Captured in onSizeChanged, not the draw lambda: pointerInput reads this
    // to hit-test taps, and it runs at a different time than drawing does. A
    // value assigned during drawing would be stale/uninitialised on first touch.
    var gridPx by remember { mutableStateOf(0f) }
    var draggingId by remember { mutableStateOf<Int?>(null) }
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
                        val hit = hitTest(currentArena, pos.x, pos.y, gridPx)
                        if (hit != null) onSelect(hit.id)
                        else onPlace(cellOf(pos, gridPx))
                    }
                }
                .pointerInput(gridPx) {
                    detectDragGestures(
                        onDragStart = { pos ->
                            draggingId = hitTest(currentArena, pos.x, pos.y, gridPx)?.id
                            outside = false
                        },
                        onDrag = { change, _ ->
                            val id = draggingId ?: return@detectDragGestures
                            val p = change.position
                            outside = p.x < 0 || p.y < 0 || p.x > gridPx || p.y > gridPx
                            if (!outside) onDragTo(id, cellOf(p, gridPx))
                        },
                        onDragEnd = {
                            val id = draggingId ?: return@detectDragGestures
                            if (outside) onDropOutside(id) else onCommit(id)
                            draggingId = null
                            outside = false
                        },
                        onDragCancel = { draggingId = null; outside = false },
                    )
                }
        ) {
            val g = min(size.width, size.height)
            drawGrid(g)
            drawStartZone(g)
            drawAxisLabels(g, textMeasurer)
            arena.obstacles.forEach { drawObstacle(it, g, it.id == selectedId, textMeasurer) }
            arena.robot?.let { drawRobot(it, g) }
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

private fun DrawScope.drawStartZone(gridPx: Float) {
    val cell = gridPx / Config.CELLS
    val side = cell * Config.START_ZONE_CELLS
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
    o.imageFace?.let { face -> drawFaceBar(face, left, top, cell) }
    o.target?.let { target ->
        // What the ROBOT reported (C.9), inbound - distinct from imageFace above.
        target.face?.let { face -> drawFaceBar(face, left, top, cell) }
        // C.9: the recognised numeric target id must appear on its block.
        drawTargetLabel(target.id, left, top, cell, textMeasurer)
    }
    // C.5 requires every block to be numbered, always - not only once a
    // target is found. Drawn last, on top of everything above, so it stays
    // legible over a face bar it happens to share a corner with.
    drawObstacleIdLabel(o, left, top, cell, textMeasurer)
}

private fun DrawScope.drawFaceBar(face: Face, left: Float, top: Float, cell: Float) {
    val t = cell * FACE_BAR_THICKNESS_RATIO
    val (offset, s) = when (face) {
        Face.N -> Offset(left, top) to Size(cell, t)
        Face.S -> Offset(left, top + cell - t) to Size(cell, t)
        Face.W -> Offset(left, top) to Size(t, cell)
        Face.E -> Offset(left + cell - t, top) to Size(t, cell)
    }
    drawRect(MdpTokens.Yellow, offset, s)
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
 * once a TARGET arrives. Small and cornered rather than centred: per
 * once a target is found the target id takes the middle and this moves aside,
 * rather than the two competing for the same centred space.
 *
 * Always top-right; a fixed position beats one that moves with state. Only two
 * face bars can reach that corner - N and E - and either paints Yellow under
 * the badge, where Paper text measures about 1.6:1 against a 4.5:1 floor, so
 * it is invisible rather than merely crowded. Switching to Ink whenever N or E
 * is active covers every face that can geometrically touch the corner.
 */
private fun DrawScope.drawObstacleIdLabel(
    o: Obstacle,
    left: Float,
    top: Float,
    cell: Float,
    textMeasurer: TextMeasurer,
) {
    val barFaces = setOfNotNull(o.imageFace, o.target?.face)
    val onFaceBar = Face.N in barFaces || Face.E in barFaces
    val ratio =
        if (o.target == null) OBSTACLE_ID_SIZE_RATIO else OBSTACLE_ID_SIZE_RATIO_WITH_TARGET
    val style = TextStyle(
        color = if (onFaceBar) MdpTokens.Ink else MdpTokens.Paper,
        fontSize = (cell * ratio).toDp().toSp(),
        // Bold, not Medium. This is a small glyph on a saturated fill, and at
        // this size weight buys more legibility than another point of size
        // would - size is what runs into the target digits.
        fontWeight = FontWeight.Bold,
    )
    val layout = textMeasurer.measure(o.id.toString(), style)
    val inset = cell * OBSTACLE_ID_INSET_RATIO
    drawText(layout, topLeft = Offset(left + cell - layout.size.width - inset, top + inset))
}

private fun DrawScope.drawRobot(pose: RobotPose, gridPx: Float) {
    val c = gridPx / Config.CELLS
    val left = pose.cell.x * c
    // Anchored at its bottom-left cell; the footprint extends up-and-right.
    val top = (Grid.toCanvasRow(pose.cell.y) - (Config.ROBOT_SIZE_CELLS - 1)) * c
    val side = c * Config.ROBOT_SIZE_CELLS
    // Hard offset shadow, then fill, then outline - the same three-part
    // treatment every surface off-canvas gets from Modifier.hardSurface,
    // hand-drawn here because this is inside a Canvas.
    val lift = MdpTokens.HardShadowSmall.toPx()
    drawRect(MdpTokens.Ink, Offset(left + lift, top + lift), Size(side, side))
    drawRect(MdpTokens.Yellow, Offset(left, top), Size(side, side))
    val edge = MdpTokens.BorderHeavy.toPx()
    drawRect(
        MdpTokens.Ink,
        Offset(left + edge / 2, top + edge / 2),
        Size(side - edge, side - edge),
        style = Stroke(edge),
    )
    // The arrow spans the whole 3x3 footprint rather than sitting inside it,
    // so the heading reads across a room on a projector. Do not shrink it.
    drawHeadingArrow(pose.heading, left, top, side)
}

/**
 * The heading must be visible, not just the position. A filled arrowhead
 * spanning the footprint reads unambiguously where a small icon would not.
 *
 * Canvas pixels only flip on y, and that flip already happened wherever [top]
 * came from - so N/S/E/W line up with up/down/left/right here exactly as they
 * do in [drawFaceBar].
 */
private fun DrawScope.drawHeadingArrow(heading: Face, left: Float, top: Float, side: Float) {
    val right = left + side
    val bottom = top + side
    val midX = left + side / 2f
    val midY = top + side / 2f
    val path = Path().apply {
        when (heading) {
            Face.N -> { moveTo(midX, top); lineTo(right, bottom); lineTo(left, bottom) }
            Face.S -> { moveTo(midX, bottom); lineTo(right, top); lineTo(left, top) }
            Face.W -> { moveTo(left, midY); lineTo(right, bottom); lineTo(right, top) }
            Face.E -> { moveTo(right, midY); lineTo(left, top); lineTo(left, bottom) }
        }
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
