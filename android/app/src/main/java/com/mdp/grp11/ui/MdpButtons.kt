package com.mdp.grp11.ui

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.RowScope
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.mdp.grp11.ui.theme.MdpTokens
import com.mdp.grp11.ui.theme.hardSurface

/**
 * The app's button, because Material's cannot be reshaped from the theme.
 *
 * `Button` resolves its shape from the `CornerFull` token, which maps to
 * `CircleShape` unconditionally rather than through `MaterialTheme.shapes` - so
 * a shape scheme on the theme changes nothing and every button stays a stock M3
 * pill. The shape has to be passed per call site; this wrapper is that call
 * site, once.
 *
 * It also kills Material's elevation: a blurred shadow under a crisp offset one
 * reads as a rendering bug rather than as either style.
 *
 * Disabled buttons lose the shadow and take a muted outline - a hard lift on a
 * control that does nothing advertises itself as pressable, and half the
 * controls here are gated on a live link.
 */
@Composable
fun MdpButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    container: Color = MdpTokens.Blue,
    contentColor: Color = Color.White,
    /**
     * Offset of the hard lift. Pass 0.dp inside an already-lifted surface -
     * the pad's card carries the shadow and its keys take a border only,
     * because a lift on a lift reads as a rendering fault rather than depth.
     */
    shadow: Dp = MdpTokens.HardShadowSmall,
    /** See [MdpTokens.ButtonPadding] - Material's default is wide enough to
     *  wrap a two-letter label on this screen. */
    contentPadding: PaddingValues = MdpTokens.ButtonPadding,
    content: @Composable RowScope.() -> Unit,
) {
    Button(
        onClick = onClick,
        enabled = enabled,
        shape = MdpTokens.ButtonShape,
        contentPadding = contentPadding,
        elevation = ButtonDefaults.buttonElevation(0.dp, 0.dp, 0.dp, 0.dp, 0.dp),
        colors = ButtonDefaults.buttonColors(
            containerColor = container,
            contentColor = contentColor,
            disabledContainerColor = MdpTokens.Cream,
            disabledContentColor = MdpTokens.Muted,
        ),
        modifier = modifier.hardSurface(
            shadow = if (enabled) shadow else 0.dp,
            radius = MdpTokens.CornerRadius,
            borderColor = if (enabled) MdpTokens.Ink else MdpTokens.Muted,
        ),
        content = content,
    )
}

/** The quieter variant: paper fill rather than a colour, same frame. */
@Composable
fun MdpOutlinedButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    shadow: Dp = MdpTokens.HardShadowSmall,
    contentPadding: PaddingValues = MdpTokens.ButtonPadding,
    content: @Composable RowScope.() -> Unit,
) = MdpButton(
    onClick = onClick,
    modifier = modifier,
    enabled = enabled,
    container = MdpTokens.Paper,
    contentColor = MdpTokens.Ink,
    shadow = shadow,
    contentPadding = contentPadding,
    content = content,
)
