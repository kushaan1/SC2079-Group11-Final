package com.mdp.grp11.ui.theme

import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import com.mdp.grp11.R

/**
 * The design's two typefaces, bundled rather than fetched. Downloadable Fonts
 * would save ~500 KB of APK but needs Play Services and a network round-trip
 * the first time a glyph is drawn - and this runs on a lab tablet that may be
 * in aeroplane mode during a timed assessment.
 *
 * Both are SIL Open Font License; the licences are in `docs/licenses/`.
 */

/**
 * A VARIABLE font: one file carrying the whole weight space rather than a
 * static file per weight. Each entry points at the same resource and pins
 * `wght`, so Compose picks the right instance instead of synthesising a fake
 * bold from the default master.
 */
val BricolageGrotesque = FontFamily(
    Font(
        R.font.bricolage_grotesque,
        FontWeight.Normal,
        variationSettings = FontVariation.Settings(FontVariation.weight(400)),
    ),
    Font(
        R.font.bricolage_grotesque,
        FontWeight.Medium,
        variationSettings = FontVariation.Settings(FontVariation.weight(500)),
    ),
    Font(
        R.font.bricolage_grotesque,
        FontWeight.Bold,
        variationSettings = FontVariation.Settings(FontVariation.weight(700)),
    ),
    Font(
        R.font.bricolage_grotesque,
        FontWeight.ExtraBold,
        variationSettings = FontVariation.Settings(FontVariation.weight(800)),
    ),
)

/**
 * DM Mono ships static instances, so no variation settings here. Only the two
 * weights the design actually uses are bundled - 400 for log lines and
 * addresses, 500 for captions and the run clocks - rather than the family's
 * six, which would have tripled the font payload for glyphs nothing draws.
 */
val DmMono = FontFamily(
    Font(R.font.dm_mono_regular, FontWeight.Normal),
    Font(R.font.dm_mono_medium, FontWeight.Medium),
    // The design never sets mono bolder than 500. Mapping Bold onto the
    // Medium file keeps `FontWeight.Bold` from synthesising a smeared fake
    // bold at the few call sites that ask for it.
    Font(R.font.dm_mono_medium, FontWeight.Bold),
)
