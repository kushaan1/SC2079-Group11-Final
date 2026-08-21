package com.mdp.grp11.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp
import com.mdp.grp11.config.Config
import com.mdp.grp11.ui.theme.MdpTokens
import com.mdp.grp11.ui.theme.hardSurface

/** One pad button: what the operator reads, and what goes on the wire. */
internal data class PadKey(val label: String, val token: String, val glyph: PadGlyph)

/**
 * The six movement glyphs, matching the artboards' stroked arrows.
 *
 * Curved for the four arcs and straight for forward/reverse, which is not
 * decoration: an Ackermann car has no rotate-on-the-spot and no strafe, so a
 * straight left arrow would promise a motion the chassis cannot perform. The
 * curve is the honest picture of what FL actually does.
 */
internal enum class PadGlyph { ForwardLeft, Forward, ForwardRight, BackLeft, Back, BackRight }

/**
 * The pad's layout and its wiring, as DATA rather than six call sites, so the
 * mapping is testable - there is no Compose UI test harness here, and as inline
 * arguments these six would be checkable only by reading them.
 *
 * Row order is screen order: forward arcs on top, reverse arcs below.
 */
internal fun padRows(t: Config.MoveTokens = Config.moveTokens): List<List<PadKey>> = listOf(
    listOf(
        PadKey("FL", t.forwardLeft, PadGlyph.ForwardLeft),
        PadKey("F", t.forward, PadGlyph.Forward),
        PadKey("FR", t.forwardRight, PadGlyph.ForwardRight),
    ),
    listOf(
        PadKey("BL", t.reverseLeft, PadGlyph.BackLeft),
        PadKey("B", t.reverse, PadGlyph.Back),
        PadKey("BR", t.reverseRight, PadGlyph.BackRight),
    ),
)

/**
 * Six-way, because the car is Ackermann - it cannot strafe or turn on the spot.
 * AMD's vocabulary has no forward-arc, so our six map onto its six slots and
 * every button still produces visible motion.
 *
 * The labels are the truth about the motion; the tokens are AMD's slot names.
 * See [Config.MoveTokens].
 */
@Composable
fun ControlPad(
    enabled: Boolean,
    onMove: (String) -> Unit,
    onStop: () -> Unit,
    modifier: Modifier = Modifier,
) {
    // The card is what makes the pad read as one instrument rather than seven
    // loose buttons, and it is the surface that carries the lift - the keys
    // take a border only, because a shadow inside a shadow reads as a rendering
    // fault instead of depth.
    Column(
        modifier
            .hardSurface(border = MdpTokens.BorderHeavy, shadow = MdpTokens.HardShadowSmall)
            .clip(RoundedCornerShape(MdpTokens.CornerRadius))
            .background(MdpTokens.Paper)
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        // Each row takes a SHARE of the card rather than a fixed height, so the
        // pad grows into whatever the column has left - these are the buttons
        // pressed most often and under the most time pressure. The floor keeps
        // them above Material's touch minimum if the card is ever given less
        // height than three rows need.
        padRows().forEach { row ->
            Row(
                Modifier.fillMaxWidth().heightIn(min = MdpTokens.TouchTarget).weight(1f),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                row.forEach { key ->
                    // F is the yellow key in the artboards - the one the
                    // operator reaches for most, and the only one they can find
                    // without looking down.
                    val highlight = key.glyph == PadGlyph.Forward
                    MdpButton(
                        onClick = { onMove(key.token) },
                        enabled = enabled,
                        // Cream on a Paper card, as the artboard has it - a
                        // key the same colour as its card has no edge.
                        container = if (highlight) MdpTokens.Yellow else MdpTokens.Cream,
                        contentColor = MdpTokens.Ink,
                        shadow = 0.dp,
                        modifier = Modifier.weight(1f).fillMaxHeight(),
                    ) {
                        PadArrow(
                            key.glyph,
                            if (enabled) MdpTokens.Ink else MdpTokens.Muted,
                        )
                    }
                }
            }
        }
        MdpButton(
            onClick = onStop,
            enabled = enabled,
            container = MdpTokens.Pink,
            contentColor = Color.White,
            shadow = 0.dp,
            modifier = Modifier.fillMaxWidth().heightIn(min = MdpTokens.TouchTarget).weight(1f),
        ) {
            // The artboards put a filled square beside the word - the
            // universal stop glyph, and what the eye finds before it reads.
            //
            // Tinted with `enabled`, like the arrows above. Material greys the
            // LABEL through disabledContentColor, but a Canvas draws exactly
            // the colour it is handed - so a literal white square stayed white
            // beside a greyed-out word, on a greyed-out fill.
            Canvas(Modifier.size(12.dp)) {
                drawRect(if (enabled) Color.White else MdpTokens.Muted)
            }
            Text("  STOP")
        }
    }
}

/**
 * Draws one movement arrow.
 *
 * Ported from the artboards' SVG paths on their own 24x24 viewport and scaled
 * here, rather than eyeballed, so the curve radius and arrowhead angle match
 * the design instead of approximating it.
 */
@Composable
private fun PadArrow(glyph: PadGlyph, tint: Color) {
    Canvas(Modifier.size(26.dp)) {
        val u = size.minDimension / 24f          // artboard unit -> px
        fun p(x: Float, y: Float) = Offset(x * u, y * u)
        val stroke = Stroke(
            width = 2.5f * u,
            cap = StrokeCap.Round,
            join = StrokeJoin.Round,
        )

        val body = Path()
        val head = Path()

        when (glyph) {
            PadGlyph.Forward -> {
                body.moveTo(12 * u, 20 * u); body.lineTo(12 * u, 5 * u)
                head.moveTo(6 * u, 11 * u); head.lineTo(12 * u, 5 * u); head.lineTo(18 * u, 11 * u)
            }
            PadGlyph.Back -> {
                body.moveTo(12 * u, 4 * u); body.lineTo(12 * u, 19 * u)
                head.moveTo(6 * u, 13 * u); head.lineTo(12 * u, 19 * u); head.lineTo(18 * u, 13 * u)
            }
            // M17 21 v-8 a6 6 0 0 0 -6 -6 H5   (arc centre 11,13)
            PadGlyph.ForwardLeft -> {
                body.moveTo(17 * u, 21 * u); body.lineTo(17 * u, 13 * u)
                body.arcTo(rectOf(p(11f, 13f), 6 * u), 0f, -90f, false)
                body.lineTo(5 * u, 7 * u)
                head.moveTo(8 * u, 4 * u); head.lineTo(5 * u, 7 * u); head.lineTo(8 * u, 10 * u)
            }
            // M7 21 v-8 a6 6 0 0 1 6 -6 H19    (arc centre 13,13)
            PadGlyph.ForwardRight -> {
                body.moveTo(7 * u, 21 * u); body.lineTo(7 * u, 13 * u)
                body.arcTo(rectOf(p(13f, 13f), 6 * u), 180f, 90f, false)
                body.lineTo(19 * u, 7 * u)
                head.moveTo(16 * u, 4 * u); head.lineTo(19 * u, 7 * u); head.lineTo(16 * u, 10 * u)
            }
            // M17 3 v8 a6 6 0 0 1 -6 6 H5      (arc centre 11,11)
            PadGlyph.BackLeft -> {
                body.moveTo(17 * u, 3 * u); body.lineTo(17 * u, 11 * u)
                body.arcTo(rectOf(p(11f, 11f), 6 * u), 0f, 90f, false)
                body.lineTo(5 * u, 17 * u)
                head.moveTo(8 * u, 20 * u); head.lineTo(5 * u, 17 * u); head.lineTo(8 * u, 14 * u)
            }
            // M7 3 v8 a6 6 0 0 0 6 6 H19       (arc centre 13,11)
            PadGlyph.BackRight -> {
                body.moveTo(7 * u, 3 * u); body.lineTo(7 * u, 11 * u)
                body.arcTo(rectOf(p(13f, 11f), 6 * u), 180f, -90f, false)
                body.lineTo(19 * u, 17 * u)
                head.moveTo(16 * u, 20 * u); head.lineTo(19 * u, 17 * u); head.lineTo(16 * u, 14 * u)
            }
        }

        drawPath(body, tint, style = stroke)
        drawPath(head, tint, style = stroke)
    }
}

/** Square bounding box for an arc of [radius] about [centre]. */
private fun DrawScope.rectOf(centre: Offset, radius: Float) = Rect(
    left = centre.x - radius,
    top = centre.y - radius,
    right = centre.x + radius,
    bottom = centre.y + radius,
)
