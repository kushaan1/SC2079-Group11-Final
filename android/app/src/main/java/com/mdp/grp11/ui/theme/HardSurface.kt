package com.mdp.grp11.ui.theme

import androidx.compose.foundation.border
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * The design's signature surface: an ink outline plus a hard offset shadow.
 *
 * Zero blur is the point, and it is why this is drawn by hand rather than with
 * `Modifier.shadow` - a blurred drop shadow reads as a floating Material card,
 * a crisp offset rectangle as the flat printed look this design is after.
 *
 * Order is fixed here so no call site can get it wrong: the offset block is
 * painted underneath, the outline on top of the content's own background.
 *
 * The shadow falls OUTSIDE the component's bounds and is not clipped, so the
 * parent must have room for it. Every call site sits in a gap-spaced column
 * that already covers the offset; one hugging a screen edge would need padding.
 *
 * @param shadow offset distance; pass 0.dp for a bordered surface with no lift
 * @param shadowColor coloured shadows carry meaning - green behind a running
 *   clock, pink behind the selection card - so it is a parameter
 */
fun Modifier.hardSurface(
    border: Dp = MdpTokens.Border,
    shadow: Dp = MdpTokens.HardShadow,
    radius: Dp = MdpTokens.CornerRadius,
    borderColor: Color = MdpTokens.Ink,
    shadowColor: Color = MdpTokens.Ink,
): Modifier = this
    .drawBehind {
        if (shadow > 0.dp) {
            val d = shadow.toPx()
            val r = radius.toPx()
            drawRoundRect(
                color = shadowColor,
                topLeft = Offset(d, d),
                size = Size(size.width, size.height),
                cornerRadius = CornerRadius(r, r),
            )
        }
    }
    .border(border, borderColor, RoundedCornerShape(radius))
