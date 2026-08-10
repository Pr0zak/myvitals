package app.myvitals.ui

import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import app.myvitals.ui.neon.NeonMV

/**
 * Shell-aware surface/text tokens for screens shared by both shells.
 *
 * The vitals detail screens are reached from BOTH the classic tab bar and
 * the neon shell, and they were hard-coded to the classic `MV` palette.
 * The result was a visible seam: opening HRV from the neon home landed on
 * a neon-styled screen (VitalsDetailScreen was already migrated), while
 * opening Sleep or Heart rate from the same grid landed on a classic navy
 * one. Same gesture, two different apps.
 *
 * Rather than fork each screen per theme, they read these tokens and the
 * shell decides. `Classic` holds the EXACT values the screens used before,
 * and it is the default, so a screen rendered outside the neon shell is
 * unchanged — the risk of this migration is confined to the neon shell.
 *
 * Only the six tokens those screens actually use are modelled. This is a
 * bridge for shared screens, not a second theme system; NeonMV and MV
 * remain the sources of truth for their own shells.
 */
@Immutable
data class AppTokens(
    /** Screen background. */
    val bg: Color,
    /** Default card / raised surface. */
    val surfaceContainer: Color,
    /** Primary reading text. */
    val onSurface: Color,
    /** Secondary text — labels, axis captions. */
    val onSurfaceVariant: Color,
    /** Tertiary text — the dimmest legible tier. */
    val onSurfaceDim: Color,
    /** Error / destructive. */
    val red: Color,
)

/** Byte-identical to the `MV` values these screens hard-coded before. */
val ClassicTokens = AppTokens(
    bg = Color(0xFF0B1018),
    surfaceContainer = Color(0xFF151D29),
    onSurface = Color(0xFFE6EAF2),
    onSurfaceVariant = Color(0xFF94A3B8),
    onSurfaceDim = Color(0xFF6B7689),
    red = Color(0xFFEF4444),
)

/**
 * Neon mapping. `Muted` covers both classic secondary tiers, so the dim
 * tier is darkened rather than collapsed into one — three text weights are
 * load-bearing on the charts, where axis labels must recede behind values.
 */
val NeonTokens = AppTokens(
    bg = NeonMV.Bg,
    surfaceContainer = NeonMV.Card,
    onSurface = NeonMV.Ink,
    onSurfaceVariant = NeonMV.Muted,
    onSurfaceDim = Color(0xFF6E6E82),
    red = NeonMV.Bad,
)

/**
 * Defaults to Classic so any screen not wrapped by the neon shell renders
 * exactly as it did. `staticCompositionLocalOf` because the value changes
 * only at shell boundaries — never mid-composition — so reads shouldn't
 * pay for change tracking.
 */
val LocalAppTokens = staticCompositionLocalOf { ClassicTokens }
