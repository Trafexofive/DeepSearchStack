package com.substrate.ytlab.ui

import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

val DarkSurface = Color(0xFF0A0A11)
val DarkCard = Color(0xFF14141F)
val Accent = Color(0xFFE04040)
val AccentDim = Color(0xFF2A1515)
val Green = Color(0xFF4CAF50)
val Orange = Color(0xFFFF9800)
val TextPrimary = Color(0xFFE8E8ED)
val TextDim = Color(0xFF7C7C8A)
val TextMuted = Color(0xFF4A4A55)

val DarkColorScheme = darkColorScheme(
    primary = Accent,
    onPrimary = Color.White,
    surface = DarkSurface,
    surfaceVariant = DarkCard,
    onSurface = TextPrimary,
    onSurfaceVariant = TextDim,
    background = DarkSurface,
    onBackground = TextPrimary,
    outline = TextMuted,
)

@Composable
fun YtLabTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = DarkColorScheme, content = content)
}
