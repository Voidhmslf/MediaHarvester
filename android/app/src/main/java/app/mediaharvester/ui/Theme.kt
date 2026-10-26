package app.mediaharvester.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.mediaharvester.R

/** Палитра бренда — те же значения, что в src/ui/theme.py на компьютере. */
@Immutable
class Palette(
    val bg: Color,
    val card: Color,
    val cardBorder: Color,
    val inner: Color,
    val innerBorder: Color,
    val secondary: Color,
    val accent: Color,
    val accentTint: Color,
    val accentTintText: Color,
    val danger: Color,
    val green: Color,
    val amber: Color,
    val text: Color,
    val textSecondary: Color,
    val textMuted: Color,
)

val LightPalette = Palette(
    bg = Color(0xFFF4F2EE), card = Color(0xFFFFFFFF), cardBorder = Color(0xFFE8E4DE),
    inner = Color(0xFFF6F4F1), innerBorder = Color(0xFFD9D3CB), secondary = Color(0xFFEFEBE6),
    accent = Color(0xFFD9480F), accentTint = Color(0xFFFDE7DC), accentTintText = Color(0xFF9A3412),
    danger = Color(0xFFB3261E), green = Color(0xFF1B7F4B), amber = Color(0xFF8A5A00),
    text = Color(0xFF1A1A1A), textSecondary = Color(0xFF4B4B52), textMuted = Color(0xFF6E6E76),
)

val DarkPalette = Palette(
    bg = Color(0xFF121212), card = Color(0xFF1A1A1D), cardBorder = Color(0xFF2A2A2F),
    inner = Color(0xFF111113), innerBorder = Color(0xFF35353B), secondary = Color(0xFF2A2A2E),
    accent = Color(0xFFD9480F), accentTint = Color(0xFF3A1E12), accentTintText = Color(0xFFFFB38A),
    danger = Color(0xFFC0392E), green = Color(0xFF4CC287), amber = Color(0xFFE3AE45),
    text = Color(0xFFF2F2F2), textSecondary = Color(0xFFB8B8C0), textMuted = Color(0xFF8F8F98),
)

val LocalPalette = staticCompositionLocalOf { LightPalette }

val Inter = FontFamily(
    Font(R.font.inter_regular, FontWeight.Normal),
    Font(R.font.inter_medium, FontWeight.Medium),
    Font(R.font.inter_semibold, FontWeight.SemiBold),
    Font(R.font.inter_bold, FontWeight.Bold),
)

/** Размеры и отступы под телефон: поля экрана 16, карточки радиусом 14, элементы управления не ниже 48. */
object Dim {
    val gutter = 16.dp
    val cardPadding = 14.dp
    val gap = 12.dp
    val radiusCard = 14.dp
    val radiusControl = 10.dp
    val touch = 48.dp
}

private fun type(size: Int, line: Int, weight: FontWeight = FontWeight.Normal) =
    TextStyle(fontFamily = Inter, fontSize = size.sp, lineHeight = line.sp, fontWeight = weight)

private val AppTypography = Typography(
    headlineSmall = type(22, 28, FontWeight.Bold),
    titleMedium = type(16, 22, FontWeight.SemiBold),
    bodyLarge = type(16, 22),
    bodyMedium = type(14, 20),
    bodySmall = type(12, 16),
    labelLarge = type(15, 20, FontWeight.SemiBold),
    labelMedium = type(13, 16, FontWeight.Medium),
)

/** mode: "system" | "light" | "dark". */
@Composable
fun MediaHarvesterTheme(mode: String, content: @Composable () -> Unit) {
    val dark = when (mode) {
        "light" -> false
        "dark" -> true
        else -> isSystemInDarkTheme()
    }
    val p = if (dark) DarkPalette else LightPalette
    val scheme = if (dark) {
        darkColorScheme(primary = p.accent, onPrimary = Color.White, background = p.bg, surface = p.card,
            onBackground = p.text, onSurface = p.text, error = p.danger)
    } else {
        lightColorScheme(primary = p.accent, onPrimary = Color.White, background = p.bg, surface = p.card,
            onBackground = p.text, onSurface = p.text, error = p.danger)
    }
    CompositionLocalProvider(LocalPalette provides p) {
        MaterialTheme(colorScheme = scheme, typography = AppTypography, content = content)
    }
}
