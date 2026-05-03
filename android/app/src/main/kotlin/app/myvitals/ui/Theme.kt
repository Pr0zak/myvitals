package app.myvitals.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

// Single dark palette — the slate/sky combo the dashboard uses.
private val DarkPalette = darkColorScheme(
    primary = Color(0xFF38BDF8),         // sky-400
    onPrimary = Color(0xFF0F172A),       // slate-900
    secondary = Color(0xFFA78BFA),       // violet-400
    onSecondary = Color(0xFF0F172A),
    tertiary = Color(0xFF22D3EE),
    background = Color(0xFF0F172A),
    onBackground = Color(0xFFE2E8F0),    // slate-200
    surface = Color(0xFF1E293B),         // slate-800
    onSurface = Color(0xFFE2E8F0),
    surfaceVariant = Color(0xFF334155),  // slate-700
    onSurfaceVariant = Color(0xFF94A3B8),
    error = Color(0xFFEF4444),
    onError = Color(0xFFFFFFFF),
    outline = Color(0xFF334155),
)

@Composable
fun MyVitalsTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = DarkPalette, content = content)
}
