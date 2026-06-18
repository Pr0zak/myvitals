@file:OptIn(androidx.compose.ui.text.ExperimentalTextApi::class)

package app.myvitals.ui.neon

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import app.myvitals.R

/**
 * Vitality Neon — the phone mirror of the web redesign theme. Obsidian
 * background with neon accents (cyan recovery/heart, magenta sleep/sober,
 * lime move/exercise, amber trails/warmth). Plus Jakarta Sans for body,
 * Space Grotesk for numerics. Lives ALONGSIDE the classic [MyVitalsTheme];
 * MainActivity picks one based on the Settings "Vitality Neon" toggle, so
 * the released classic shell is never touched by this code path.
 *
 * Palette + hexes are kept byte-identical to the web tokens in App.vue's
 * `[data-theme="neon"]` block so the two surfaces match exactly.
 */
object NeonMV {
    val Bg = Color(0xFF0F1118)              // obsidian
    val BgElevated = Color(0xFF161A2C)      // radial-gradient highlight
    val Card = Color(0xFF181B27)            // surface
    val CardHigh = Color(0xFF1E2230)
    val Track = Color(0xFF272A3B)           // ring tracks / gridlines
    val Line = Color(0xFF23263A)            // borders

    val Ink = Color(0xFFECECF5)             // primary text
    val Muted = Color(0xFF9B9BB0)           // secondary text

    val Cyan = Color(0xFF28E6FF)            // recovery / heart / HRV / BP
    val Magenta = Color(0xFFFF3AD8)         // sleep / sober
    val Lime = Color(0xFF5DFF3B)            // move / steps / good
    val Amber = Color(0xFFFFB52E)           // weight / trails / caution
    val Bad = Color(0xFFFF5D7A)             // high / closed / crisis
    val Periwinkle = Color(0xFF6F7BFF)      // sleep-light / zone-1 / secondary line

    val OnAccent = Color(0xFF06121A)        // dark ink for text on a neon fill
}

private val Jakarta = FontFamily(
    Font(R.font.plus_jakarta_sans, FontWeight.Normal,
        variationSettings = FontVariation.Settings(FontVariation.weight(400))),
    Font(R.font.plus_jakarta_sans, FontWeight.Medium,
        variationSettings = FontVariation.Settings(FontVariation.weight(500))),
    Font(R.font.plus_jakarta_sans, FontWeight.SemiBold,
        variationSettings = FontVariation.Settings(FontVariation.weight(600))),
    Font(R.font.plus_jakarta_sans, FontWeight.Bold,
        variationSettings = FontVariation.Settings(FontVariation.weight(700))),
    Font(R.font.plus_jakarta_sans, FontWeight.ExtraBold,
        variationSettings = FontVariation.Settings(FontVariation.weight(800))),
)

/** Space Grotesk — use for big numeric readouts (the web uses it for stats). */
val NeonNumberFamily = FontFamily(
    Font(R.font.space_grotesk, FontWeight.Medium,
        variationSettings = FontVariation.Settings(FontVariation.weight(500))),
    Font(R.font.space_grotesk, FontWeight.Bold,
        variationSettings = FontVariation.Settings(FontVariation.weight(700))),
)

private val NeonPalette = darkColorScheme(
    primary = NeonMV.Cyan,
    onPrimary = NeonMV.OnAccent,
    secondary = NeonMV.Magenta,
    onSecondary = NeonMV.OnAccent,
    tertiary = NeonMV.Lime,
    onTertiary = NeonMV.OnAccent,
    background = NeonMV.Bg,
    onBackground = NeonMV.Ink,
    surface = NeonMV.Card,
    onSurface = NeonMV.Ink,
    surfaceContainer = NeonMV.Card,
    surfaceContainerHigh = NeonMV.CardHigh,
    surfaceContainerLow = NeonMV.Bg,
    surfaceVariant = NeonMV.Card,
    onSurfaceVariant = NeonMV.Muted,
    error = NeonMV.Bad,
    onError = NeonMV.OnAccent,
    outline = NeonMV.Track,
    outlineVariant = NeonMV.Line,
)

private val NeonTypography = Typography().run {
    copy(
        displayLarge = displayLarge.copy(fontFamily = Jakarta),
        displayMedium = displayMedium.copy(fontFamily = Jakarta),
        displaySmall = displaySmall.copy(fontFamily = Jakarta),
        headlineLarge = headlineLarge.copy(fontFamily = Jakarta),
        headlineMedium = headlineMedium.copy(fontFamily = Jakarta),
        headlineSmall = headlineSmall.copy(fontFamily = Jakarta),
        titleLarge = titleLarge.copy(fontFamily = Jakarta),
        titleMedium = titleMedium.copy(fontFamily = Jakarta),
        titleSmall = titleSmall.copy(fontFamily = Jakarta),
        bodyLarge = bodyLarge.copy(fontFamily = Jakarta),
        bodyMedium = bodyMedium.copy(fontFamily = Jakarta),
        bodySmall = bodySmall.copy(fontFamily = Jakarta),
        labelLarge = labelLarge.copy(fontFamily = Jakarta),
        labelMedium = labelMedium.copy(fontFamily = Jakarta),
        labelSmall = labelSmall.copy(fontFamily = Jakarta),
    )
}

@Composable
fun NeonTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = NeonPalette,
        typography = NeonTypography,
        content = content,
    )
}
