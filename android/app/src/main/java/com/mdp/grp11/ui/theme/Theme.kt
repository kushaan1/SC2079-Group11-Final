package com.mdp.grp11.ui.theme

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp

object MdpTokens {
    val Ink = Color(0xFF201C2B)
    val Cream = Color(0xFFF2EBDC)
    val Paper = Color(0xFFFDFBF5)
    val Blue = Color(0xFF3E7BE8)
    val Pink = Color(0xFFE8557F)
    val Yellow = Color(0xFFEFC33F)
    val Green = Color(0xFF4FB86B)
    val Muted = Color(0xFF6E6880)

    /**
     * Ink at reduced weight, for captions ON the dark log panel. [Muted] is
     * tuned for dark-on-light and disappears against [Ink].
     */
    val MutedOnInk = Color(0xFFA79FBA)

    /**
     * Offset of the hard shadow. Offset with ZERO blur is the whole idea - a
     * blurred shadow reads as Material elevation, which is the look this
     * design is deliberately not.
     */
    val HardShadow: Dp = 4.dp

    /** Smaller offset for controls, so a row of buttons does not look like a stack of cards. */
    val HardShadowSmall: Dp = 3.dp

    /** Ink outline on every surface. The artboards use 2-3px; 2dp reads equivalently here. */
    val Border: Dp = 2.dp

    /** Heavier frame for the arena, which the artboards give a 3px border and a 6px shadow. */
    val BorderHeavy: Dp = 3.dp

    val CornerRadius: Dp = 8.dp

    /**
     * Every button in the app. Material resolves button shape from its
     * `CornerFull` token, which is hardcoded to `CircleShape` and does NOT read
     * `MaterialTheme.shapes` - so this cannot be applied by theming and has to
     * be passed at the call site. See [com.mdp.grp11.ui.MdpButton].
     */
    val ButtonShape: RoundedCornerShape = RoundedCornerShape(8.dp)

    /**
     * Inset of a button's label. Material's own is 24dp per side, which is most
     * of a narrow button - on the compass's ~80dp OK key that is 48dp of
     * padding, and the label wraps. Buttons here are laid out by weight rather
     * than sized by their text, so the padding is what decides whether a label
     * fits.
     */
    val ButtonPadding: PaddingValues = PaddingValues(horizontal = 10.dp, vertical = 4.dp)

    val GridStroke: Dp = 1.dp
    val GridMajorStroke: Dp = 2.dp
    val SelectionStroke: Dp = 3.dp

    /** Border weight for an arena-wide destructive-state flag (C.6's
     *  drag-outside-to-remove). Heavier than [SelectionStroke], which
     *  highlights a single block rather than the whole canvas. */
    val DangerStroke: Dp = 4.dp

    /**
     * Touch target floor for the movement, compass and task controls. Material's
     * minimum is 48dp; these are the controls operated under time pressure during
     * a run, so they get more headroom than that floor.
     */
    val TouchTarget: Dp = 56.dp
}

/**
 * EVERY role, not just the handful the design changes.
 *
 * Material fills any role left unset with its stock purple-grey, and the
 * components that matter here do not read the obvious ones: `Card` defaults to
 * `surfaceContainerLow`, **not** `surface`, and `OutlinedButton` to `outline` +
 * `surface`. Leave those out and half the screen renders in M3 lavender while
 * the correct tokens sit unused.
 */
private val Scheme = lightColorScheme(
    primary = MdpTokens.Blue,
    onPrimary = Color.White,
    primaryContainer = MdpTokens.Blue,
    onPrimaryContainer = Color.White,

    secondary = MdpTokens.Pink,
    onSecondary = Color.White,
    secondaryContainer = MdpTokens.Yellow,
    onSecondaryContainer = MdpTokens.Ink,

    tertiary = MdpTokens.Green,
    onTertiary = MdpTokens.Ink,

    background = MdpTokens.Cream,
    onBackground = MdpTokens.Ink,

    surface = MdpTokens.Paper,
    onSurface = MdpTokens.Ink,

    // The four Card/menu/sheet containers. All Paper: this design separates
    // surfaces with a border and a hard shadow, never with a tint ramp, so a
    // graduated set of greys here would fight the borders rather than help.
    surfaceContainerLowest = MdpTokens.Paper,
    surfaceContainerLow = MdpTokens.Paper,
    surfaceContainer = MdpTokens.Paper,
    surfaceContainerHigh = MdpTokens.Paper,
    surfaceContainerHighest = MdpTokens.Cream,

    surfaceVariant = MdpTokens.Cream,
    onSurfaceVariant = MdpTokens.Muted,

    outline = MdpTokens.Ink,
    outlineVariant = MdpTokens.Muted,

    inverseSurface = MdpTokens.Ink,
    inverseOnSurface = MdpTokens.Paper,

    error = MdpTokens.Pink,
    onError = Color.White,
    errorContainer = MdpTokens.Pink,
    onErrorContainer = Color.White,
)

/**
 * The artboards' scale, which is tighter and more deliberate than Material's:
 * heavy numerals with negative tracking, and wide-tracked mono for every
 * caption, coordinate, address and log line.
 *
 * Both families are bundled from `res/font/` - see [BricolageGrotesque] and
 * [DmMono] for why they are shipped rather than downloaded.
 */
private val Display = BricolageGrotesque
private val Mono = DmMono

private val MdpTypography = Typography(
    // Run clocks and any other large numeral. 800 weight with negative
    // tracking, per the artboards' 26px/800/-0.02em.
    headlineSmall = TextStyle(
        fontFamily = Mono,
        fontWeight = FontWeight.Bold,
        fontSize = 26.sp,
        letterSpacing = (-0.02).em,
    ),
    titleMedium = TextStyle(
        fontFamily = Mono,
        fontWeight = FontWeight.Bold,
        fontSize = 20.sp,
        letterSpacing = (-0.01).em,
    ),
    titleLarge = TextStyle(
        fontFamily = Display,
        fontWeight = FontWeight.ExtraBold,
        fontSize = 22.sp,
        letterSpacing = (-0.02).em,
    ),
    // Body text: the status line, device names, dialog copy.
    bodyLarge = TextStyle(fontFamily = Display, fontWeight = FontWeight.Normal, fontSize = 16.sp),
    bodyMedium = TextStyle(fontFamily = Display, fontWeight = FontWeight.Normal, fontSize = 14.sp),
    bodySmall = TextStyle(fontFamily = Display, fontWeight = FontWeight.Normal, fontSize = 13.sp),
    // Every button in the app. Wide tracking, since they are all short caps.
    labelLarge = TextStyle(
        fontFamily = Display,
        fontWeight = FontWeight.ExtraBold,
        fontSize = 14.sp,
        letterSpacing = 0.06.em,
    ),
    // Section captions - STATUS, BLUETOOTH LOG · RAW, PAIRED, FOUND.
    labelMedium = TextStyle(
        fontFamily = Mono,
        fontWeight = FontWeight.Medium,
        fontSize = 11.sp,
        letterSpacing = 0.1.em,
    ),
    labelSmall = TextStyle(
        fontFamily = Mono,
        fontWeight = FontWeight.Medium,
        fontSize = 10.sp,
        letterSpacing = 0.1.em,
    ),
)

/** Single light scheme by design - the tablet is used under lab lighting. */
@Composable
fun MdpTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = Scheme, typography = MdpTypography, content = content)
}
