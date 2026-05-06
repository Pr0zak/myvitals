package app.myvitals.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/**
 * Brand palette — matches the Claude Design handoff (myvitals Android).
 * The brand red (#EF4444) is intentionally `primary` so section headers
 * and accents pull it; amber lives outside the M3 scheme as a callable
 * token for the reset action.
 */
object MV {
    val Bg = Color(0xFF0B1018)              // brand navy
    val Surface = Color(0xFF0F1620)         // dim surface
    val SurfaceContainer = Color(0xFF151D29)
    val SurfaceContainerHigh = Color(0xFF1B2434)
    val SurfaceContainerLow = Color(0xFF121925)
    val Outline = Color(0xFF2A3447)
    val OutlineVariant = Color(0xFF1F2738)

    val OnSurface = Color(0xFFE6EAF2)
    val OnSurfaceVariant = Color(0xFF94A3B8)
    val OnSurfaceDim = Color(0xFF6B7689)

    val BrandRed = Color(0xFFEF4444)
    val Amber = Color(0xFFF59E0B)
    val AmberDim = Color(0xFFB97506)
    val AmberOn = Color(0xFF1A1305)
    val Green = Color(0xFF22C55E)
    val Red = Color(0xFFEF4444)
}

private val DarkPalette = darkColorScheme(
    primary = MV.BrandRed,
    onPrimary = Color.White,
    secondary = MV.Amber,
    onSecondary = MV.AmberOn,
    background = MV.Bg,
    onBackground = MV.OnSurface,
    surface = MV.Surface,
    onSurface = MV.OnSurface,
    surfaceContainer = MV.SurfaceContainer,
    surfaceContainerHigh = MV.SurfaceContainerHigh,
    surfaceContainerLow = MV.SurfaceContainerLow,
    surfaceVariant = MV.SurfaceContainer,
    onSurfaceVariant = MV.OnSurfaceVariant,
    error = MV.Red,
    onError = Color.White,
    outline = MV.Outline,
    outlineVariant = MV.OutlineVariant,
)

@Composable
fun MyVitalsTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = DarkPalette, content = content)
}
