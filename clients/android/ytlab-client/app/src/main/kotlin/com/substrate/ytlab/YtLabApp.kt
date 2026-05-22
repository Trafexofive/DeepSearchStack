package com.substrate.ytlab

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch

// ── Theme ───────────────────────────────────────────────────────

private val DarkSurface = Color(0xFF0F0F16)
private val DarkCard = Color(0xFF1A1A24)
private val Accent = Color(0xFFE04040)
private val AccentDim = Color(0xFF2A1515)
private val TextPrimary = Color(0xFFE8E8ED)
private val TextDim = Color(0xFF8B8B96)

// ── App Entry ───────────────────────────────────────────────────

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun YtLabApp(
    api: YtLabApi,
    initialUrl: String?,
    onProcessUrl: (String) -> Unit,
) {
    val colorScheme = darkColorScheme(
        primary = Accent,
        surface = DarkSurface,
        surfaceVariant = DarkCard,
        onSurface = TextPrimary,
        onSurfaceVariant = TextDim,
    )

    MaterialTheme(colorScheme = colorScheme) {
        var selectedTab by remember { mutableIntStateOf(0) }
        var historyItems by remember { mutableStateOf(listOf<HistoryItem>()) }
        var showUrlDialog by remember { mutableStateOf(initialUrl != null) }
        var dialogUrl by remember { mutableStateOf(initialUrl ?: "") }
        var ytLabHealth by remember { mutableStateOf<Map<String, String>>(emptyMap()) }
        val scope = rememberCoroutineScope()

        LaunchedEffect(Unit) {
            try {
                val health = api.health()
                health?.let { json ->
                    val deps = json.optJSONObject("dependencies") ?: json
                    val map = mutableMapOf<String, String>()
                    deps.keys().forEach { key -> map[key] = deps.optString(key) }
                    ytLabHealth = map
                }
            } catch (_: Exception) {}
        }

        // Handle initial share URL
        LaunchedEffect(initialUrl) {
            if (initialUrl != null && YtLabApi.isYoutubeUrl(initialUrl)) {
                val item = HistoryItem(initialUrl, "Processing…", System.currentTimeMillis())
                historyItems = listOf(item) + historyItems
                onProcessUrl(initialUrl)
            }
        }

        Scaffold(
            topBar = {
                TopAppBar(
                    title = { Text("yt-lab", fontWeight = FontWeight.Bold) },
                    colors = TopAppBarDefaults.topAppBarColors(
                        containerColor = DarkSurface,
                        titleContentColor = Accent,
                    ),
                    actions = {
                        IconButton(onClick = { showUrlDialog = true }) {
                            Icon(Icons.Filled.AddLink, contentDescription = "Add URL", tint = TextDim)
                        }
                    }
                )
            },
            bottomBar = {
                NavigationBar(containerColor = DarkCard) {
                    NavigationBarItem(
                        selected = selectedTab == 0,
                        onClick = { selectedTab = 0 },
                        icon = { Icon(Icons.Filled.Dashboard, contentDescription = null) },
                        label = { Text("Status") },
                        colors = NavigationBarItemDefaults.colors(
                            selectedIconColor = Accent,
                            indicatorColor = AccentDim,
                        )
                    )
                    NavigationBarItem(
                        selected = selectedTab == 1,
                        onClick = { selectedTab = 1 },
                        icon = { Icon(Icons.Filled.History, contentDescription = null) },
                        label = { Text("History") },
                        colors = NavigationBarItemDefaults.colors(
                            selectedIconColor = Accent,
                            indicatorColor = AccentDim,
                        )
                    )
                }
            },
            containerColor = DarkSurface,
        ) { padding ->
            Box(modifier = Modifier.padding(padding)) {
                when (selectedTab) {
                    0 -> StatusTab(ytLabHealth, historyItems)
                    1 -> HistoryTab(historyItems)
                }
            }
        }

        // URL input dialog
        if (showUrlDialog) {
            UrlInputDialog(
                initialUrl = dialogUrl,
                onDismiss = { showUrlDialog = false },
                onSubmit = { url ->
                    showUrlDialog = false
                    dialogUrl = ""
                    historyItems = listOf(HistoryItem(url, "Processing…", System.currentTimeMillis())) + historyItems
                    onProcessUrl(url)
                }
            )
        }
    }
}

// ── Status Tab ──────────────────────────────────────────────────

@Composable
fun StatusTab(health: Map<String, String>, history: List<HistoryItem>) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        // System status card
        item {
            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(16.dp),
                colors = CardDefaults.cardColors(containerColor = DarkCard),
            ) {
                Column(modifier = Modifier.padding(20.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Filled.Memory, contentDescription = null, tint = Accent, modifier = Modifier.size(24.dp))
                        Spacer(Modifier.width(10.dp))
                        Text("yt-lab Status", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                    }
                    Spacer(Modifier.height(16.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceEvenly,
                    ) {
                        StatusChip("Extractor", health["extractor"] ?: "—")
                        StatusChip("Inference", health["inference"] ?: "—")
                        StatusChip("Humanizer", health["humanizer"] ?: "—")
                    }
                    Spacer(Modifier.height(8.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceEvenly,
                    ) {
                        StatusChip("Warehouse", health["warehouse"] ?: "—")
                        StatusChip("Watching", if (health.isEmpty()) "—" else "0")
                    }
                }
            }
        }

        // Quick actions
        item {
            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(16.dp),
                colors = CardDefaults.cardColors(containerColor = DarkCard),
            ) {
                Column(modifier = Modifier.padding(20.dp)) {
                    Text("Share from YouTube →", style = MaterialTheme.typography.titleSmall, color = TextDim)
                    Spacer(Modifier.height(12.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        ActionChip("📹 Video", "Auto-summarize") { }
                        ActionChip("📺 Channel", "Ingest 10 videos") { }
                    }
                }
            }
        }
    }
}

@Composable
fun StatusChip(label: String, status: String) {
    val isHealthy = status.contains(":") || status.contains("localhost") || status.contains("http")
    val color = if (isHealthy) Color(0xFF4CAF50) else Color(0xFFFF7043)
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                modifier = Modifier
                    .size(8.dp)
                    .background(color, RoundedCornerShape(4.dp))
            )
            Spacer(Modifier.width(6.dp))
            Text(label, style = MaterialTheme.typography.labelSmall, color = TextDim)
        }
        Text(
            if (isHealthy) "Online" else status,
            style = MaterialTheme.typography.labelMedium,
            color = color,
            fontWeight = FontWeight.Medium,
        )
    }
}

@Composable
fun ActionChip(icon: String, label: String, onClick: () -> Unit) {
    Surface(
        onClick = onClick,
        shape = RoundedCornerShape(12.dp),
        color = AccentDim,
        modifier = Modifier.height(64.dp),
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Text(icon, style = MaterialTheme.typography.titleMedium)
            Text(label, style = MaterialTheme.typography.labelSmall, color = TextDim)
        }
    }
}

// ── History Tab ─────────────────────────────────────────────────

data class HistoryItem(
    val url: String,
    val status: String,
    val timestamp: Long,
)

@Composable
fun HistoryTab(items: List<HistoryItem>) {
    if (items.isEmpty()) {
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Icon(Icons.Filled.OndemandVideo, contentDescription = null, tint = TextDim, modifier = Modifier.size(64.dp))
                Spacer(Modifier.height(12.dp))
                Text("No videos processed yet", color = TextDim, style = MaterialTheme.typography.bodyLarge)
                Text("Share a YouTube link to get started", color = TextDim, style = MaterialTheme.typography.bodySmall)
            }
        }
    } else {
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items(items) { item ->
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(12.dp),
                    colors = CardDefaults.cardColors(containerColor = DarkCard),
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(16.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(
                            if (YtLabApi.isChannelUrl(item.url)) Icons.Filled.Tv else Icons.Filled.PlayArrow,
                            contentDescription = null,
                            tint = Accent,
                            modifier = Modifier.size(28.dp),
                        )
                        Spacer(Modifier.width(12.dp))
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = item.url,
                                style = MaterialTheme.typography.bodySmall,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                color = TextPrimary,
                            )
                            Text(
                                text = item.status,
                                style = MaterialTheme.typography.labelSmall,
                                color = TextDim,
                            )
                        }
                    }
                }
            }
        }
    }
}

// ── URL Input Dialog ────────────────────────────────────────────

@Composable
fun UrlInputDialog(initialUrl: String, onDismiss: () -> Unit, onSubmit: (String) -> Unit) {
    var url by remember { mutableStateOf(initialUrl) }
    val focusManager = LocalFocusManager.current

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = DarkCard,
        title = { Text("Paste YouTube URL", fontWeight = FontWeight.SemiBold) },
        text = {
            OutlinedTextField(
                value = url,
                onValueChange = { url = it },
                placeholder = { Text("https://youtube.com/watch?v=...", color = TextDim) },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Go),
                keyboardActions = KeyboardActions(
                    onGo = {
                        focusManager.clearFocus()
                        if (YtLabApi.isYoutubeUrl(url)) onSubmit(url) else onDismiss()
                    }
                ),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = Accent,
                    unfocusedBorderColor = TextDim,
                    cursorColor = Accent,
                ),
            )
        },
        confirmButton = {
            TextButton(
                onClick = { if (YtLabApi.isYoutubeUrl(url)) onSubmit(url) else onDismiss() },
                enabled = url.isNotBlank(),
            ) { Text("Go", color = if (url.isNotBlank()) Accent else TextDim) }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancel", color = TextDim) }
        },
    )
}
