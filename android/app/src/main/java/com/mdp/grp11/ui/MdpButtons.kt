package com.mdp.grp11.ui

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.LocalIndication
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ProvideTextStyle
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.semantics.Role
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
 *
 * With [onLongClick] the button is built by hand on `combinedClickable` rather
 * than on `Button`, which has no long-press API. Stacking a gesture detector
 * on top of `Button` was rejected: whether the plain tap survives depends on
 * pointer-pass ordering between the two, and the one button that needs a long
 * press is the one that starts a scored run. See [LongPressButton].
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
    /**
     * A second, held gesture. Fires whether or not [enabled] - see
     * [LongPressButton] for why - so only give it to a button whose long
     * press is a setting rather than a transmission.
     */
    onLongClick: (() -> Unit)? = null,
    content: @Composable RowScope.() -> Unit,
) {
    if (onLongClick != null) {
        LongPressButton(
            onClick = onClick,
            onLongClick = onLongClick,
            modifier = modifier,
            enabled = enabled,
            container = container,
            contentColor = contentColor,
            shadow = shadow,
            contentPadding = contentPadding,
            content = content,
        )
        return
    }
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

/**
 * [MdpButton]'s look, rebuilt on `combinedClickable` so it can take a long
 * press. Mirrors what `Button` does inside: a surface in the container colour,
 * `labelLarge` content colour provided, Material's 58x40dp minimum, the
 * content padding, and a centred row.
 *
 * The long press is live even when [enabled] is false. [enabled] gates the
 * TAP, which transmits and so needs a link; a long press on this app's
 * buttons is a setting, and a setting that can only be reached while
 * connected and idle is one the operator cannot make while setting up. So
 * the gesture stays armed, the disabled look is kept, and a tap on a disabled
 * button does nothing - with no ripple, so it does not pretend otherwise.
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun LongPressButton(
    onClick: () -> Unit,
    onLongClick: () -> Unit,
    modifier: Modifier,
    enabled: Boolean,
    container: Color,
    contentColor: Color,
    shadow: Dp,
    contentPadding: PaddingValues,
    content: @Composable RowScope.() -> Unit,
) {
    val haptics = LocalHapticFeedback.current
    val indication = LocalIndication.current
    val interaction = remember { MutableInteractionSource() }
    Box(
        modifier
            .hardSurface(
                shadow = if (enabled) shadow else 0.dp,
                radius = MdpTokens.CornerRadius,
                borderColor = if (enabled) MdpTokens.Ink else MdpTokens.Muted,
            )
            .clip(MdpTokens.ButtonShape)
            .background(if (enabled) container else MdpTokens.Cream)
            .combinedClickable(
                interactionSource = interaction,
                // No ripple on a disabled look: the press is being accepted
                // for the sake of the long press, not the tap.
                indication = if (enabled) indication else null,
                role = Role.Button,
                onClick = { if (enabled) onClick() },
                onLongClick = {
                    haptics.performHapticFeedback(HapticFeedbackType.LongPress)
                    onLongClick()
                },
            )
            .defaultMinSize(minWidth = ButtonDefaults.MinWidth, minHeight = ButtonDefaults.MinHeight)
            .padding(contentPadding),
        contentAlignment = Alignment.Center,
    ) {
        CompositionLocalProvider(
            LocalContentColor provides (if (enabled) contentColor else MdpTokens.Muted),
        ) {
            ProvideTextStyle(MaterialTheme.typography.labelLarge) {
                Row(
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically,
                    content = content,
                )
            }
        }
    }
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
