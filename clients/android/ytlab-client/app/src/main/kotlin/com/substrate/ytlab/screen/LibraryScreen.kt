package com.substrate.ytlab.screen

import android.content.Intent
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.SwipeToDismissBox
import androidx.compose.material3.SwipeToDismissBoxValue
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.runtime.*
import kotlinx.coroutines.launch
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.substrate.ytlab.ui.*
import org.json.JSONObject

data class IngestedVideo(
    val url: String,
    val title: String,
    val channel: String,
    val duration: Int,
    val viewCount: Long,
    val uploadDate: String,
    val transcriptPreview: String,
    val ingestedAt: String,
    val audioUrl: String = "",
    val videoUrl: String = "",
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LibraryScreen(
    videos: List<IngestedVideo>,
    onVideoClick: (IngestedVideo) -> Unit,
    onRefresh: () -> Unit,
    isRefreshing: Boolean,
    error: String? = null,
    onSummarizeVideo: (suspend (String) -> String)? = null,
    onDeleteVideo: ((String) -> Unit)? = null,
    onPlayAudio: ((String) -> Unit)? = null,
) {
    var searchQuery by remember { mutableStateOf("") }
    var filterChannel by remember { mutableStateOf<String?>(null) }
    var timeFilter by remember { mutableStateOf("all") } // "all", "recent", "old"
    var summaries by remember { mutableStateOf(mapOf<String, String>()) }
    var loadingSummaries by remember { mutableStateOf(setOf<String>()) }
    var deletingUrl by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    val ctx = LocalContext.current

    val channels = remember(videos) { videos.map { it.channel }.distinct().sorted() }
    val filtered = remember(videos, searchQuery, filterChannel, timeFilter) {
        val now = System.currentTimeMillis()
        val sevenDaysMs = 7L * 24 * 60 * 60 * 1000
        videos.filter { v ->
            // Search: match title, channel, or transcript preview
            val q = searchQuery.lowercase()
            val matchesSearch = searchQuery.isEmpty() ||
                v.title.lowercase().contains(q) ||
                v.channel.lowercase().contains(q) ||
                v.transcriptPreview.lowercase().contains(q)
            // Channel filter
            val matchesChannel = filterChannel == null || v.channel == filterChannel
            // Time filter (based on ingestedAt if parseable, otherwise always include)
            val matchesTime = when (timeFilter) {
                "recent" -> {
                    try {
                        val parsed = java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", java.util.Locale.US).parse(v.ingestedAt.take(19))
                        parsed?.time?.let { now - it < sevenDaysMs } ?: true
                    } catch (_: Exception) { true }
                }
                "old" -> {
                    try {
                        val parsed = java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", java.util.Locale.US).parse(v.ingestedAt.take(19))
                        parsed?.time?.let { now - it >= sevenDaysMs } ?: true
                    } catch (_: Exception) { false }
                }
                else -> true
            }
            matchesSearch && matchesChannel && matchesTime
        }
    }

    Column(modifier = Modifier.fillMaxSize()) {
        // Error banner
        if (error != null) {
            Surface(modifier = Modifier.fillMaxWidth(), color = AccentDim) {
                Row(modifier = Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Filled.ErrorOutline, null, tint = Accent, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(8.dp))
                    Text(error, color = Accent, style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
                    TextButton(onClick = onRefresh) { Text("Retry", color = Accent) }
                }
            }
        }

        PullToRefreshBox(isRefreshing = isRefreshing, onRefresh = onRefresh) {
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                // Search bar
                item {
                    OutlinedTextField(
                        value = searchQuery, onValueChange = { searchQuery = it },
                        modifier = Modifier.fillMaxWidth(),
                        placeholder = { Text("Search ${videos.size} videos…", color = TextDim) },
                        leadingIcon = { Icon(Icons.Filled.Search, null, tint = TextDim) },
                        trailingIcon = {
                            if (searchQuery.isNotEmpty()) IconButton(onClick = { searchQuery = "" }) { Icon(Icons.Filled.Close, "Clear", tint = TextDim) }
                        },
                        singleLine = true, shape = RoundedCornerShape(12.dp),
                        colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = Accent, unfocusedBorderColor = TextMuted, cursorColor = Accent, focusedContainerColor = DarkCard, unfocusedContainerColor = DarkCard),
                    )
                }

                // Filter chips
                item {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        // Time filters
                        FilterChip(selected = timeFilter == "all", onClick = { timeFilter = "all" }, label = { Text("All") }, colors = FilterChipDefaults.filterChipColors(selectedContainerColor = AccentDim, selectedLabelColor = Accent))
                        FilterChip(selected = timeFilter == "recent", onClick = { timeFilter = if (timeFilter == "recent") "all" else "recent" }, label = { Text("Recent") }, colors = FilterChipDefaults.filterChipColors(selectedContainerColor = AccentDim, selectedLabelColor = Accent))
                        FilterChip(selected = timeFilter == "old", onClick = { timeFilter = if (timeFilter == "old") "all" else "old" }, label = { Text("Old") }, colors = FilterChipDefaults.filterChipColors(selectedContainerColor = AccentDim, selectedLabelColor = Accent))
                        // Channel filters (scrollable if many)
                        if (channels.size > 1) {
                            channels.take(3).forEach { ch ->
                                FilterChip(selected = filterChannel == ch, onClick = { filterChannel = if (filterChannel == ch) null else ch }, label = { Text(ch, maxLines = 1, overflow = TextOverflow.Ellipsis) }, colors = FilterChipDefaults.filterChipColors(selectedContainerColor = AccentDim, selectedLabelColor = Accent))
                            }
                        }
                    }
                }

                // Count
                item {
                    Text("${filtered.size} video${if (filtered.size != 1) "s" else ""}", style = MaterialTheme.typography.labelMedium, color = TextDim)
                }

                if (filtered.isEmpty() && !isRefreshing) {
                    item {
                        Box(Modifier.fillMaxWidth().height(300.dp), contentAlignment = Alignment.Center) {
                            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                Icon(if (error != null) Icons.Filled.CloudOff else Icons.Filled.VideoLibrary, null, tint = TextMuted, modifier = Modifier.size(64.dp))
                                Spacer(Modifier.height(12.dp))
                                Text(if (error != null) "Could not connect to yt-lab" else if (videos.isEmpty()) "No videos ingested yet" else "No results", color = TextDim)
                                if (videos.isEmpty() && error == null) Text("Share a YouTube link to start", color = TextMuted, style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                } else {
                    items(filtered, key = { it.url }) { video ->
                        val dismissState = rememberSwipeToDismissBoxState(
                            confirmValueChange = { value ->
                                when (value) {
                                    SwipeToDismissBoxValue.EndToStart -> {
                                        // Swipe left → Summarize
                                        if (onSummarizeVideo != null && video.url !in loadingSummaries) {
                                            scope.launch {
                                                loadingSummaries = loadingSummaries + video.url
                                                val result = onSummarizeVideo(video.url)
                                                summaries = summaries + (video.url to result)
                                                loadingSummaries = loadingSummaries - video.url
                                            }
                                        }
                                    }
                                    SwipeToDismissBoxValue.StartToEnd -> {
                                        // Swipe right → Share
                                        val intent = Intent(Intent.ACTION_SEND).apply {
                                            type = "text/plain"
                                            putExtra(Intent.EXTRA_TEXT, "${video.title}\n${video.url}\n\n${summaries[video.url] ?: ""}")
                                        }
                                        ctx.startActivity(Intent.createChooser(intent, "Share"))
                                    }
                                    else -> {}
                                }
                                false // Don't dismiss
                            }
                        )
                        SwipeToDismissBox(
                            state = dismissState,
                            backgroundContent = {},
                            enableDismissFromStartToEnd = true,
                            enableDismissFromEndToStart = true,
                        ) {
                            VideoCard(
                                video = video,
                                onClick = { onVideoClick(video) },
                                summary = summaries[video.url],
                                isSummarizing = video.url in loadingSummaries,
                                onSummarize = if (onSummarizeVideo != null) {
                                    {
                                        scope.launch {
                                            loadingSummaries = loadingSummaries + video.url
                                            val result = onSummarizeVideo(video.url)
                                            summaries = summaries + (video.url to result)
                                            loadingSummaries = loadingSummaries - video.url
                                        }
                                    }
                                } else null,
                                onShare = {
                                    val intent = Intent(Intent.ACTION_SEND).apply {
                                        type = "text/plain"
                                        putExtra(Intent.EXTRA_TEXT, "${video.title}\n${video.url}\n\n${summaries[video.url] ?: ""}")
                                    }
                                    ctx.startActivity(Intent.createChooser(intent, "Share"))
                                },
                                onDelete = if (onDeleteVideo != null) {{ deletingUrl = video.url }} else null,
                                onPlayAudio = if (onPlayAudio != null) {{ onPlayAudio(video.url) }} else null,
                            )
                        }
                    }
                }

                item { Spacer(Modifier.height(80.dp)) }
            }
        }
    }

    // Delete confirmation dialog
    if (deletingUrl != null) {
        AlertDialog(
            onDismissRequest = { deletingUrl = null },
            containerColor = DarkCard,
            title = { Text("Delete video?") },
            text = { Text("This removes it from yt-lab.", color = TextDim) },
            confirmButton = {
                TextButton(onClick = {
                    val url = deletingUrl!!
                    deletingUrl = null
                    onDeleteVideo?.invoke(url)
                }) { Text("Delete", color = Accent) }
            },
            dismissButton = { TextButton(onClick = { deletingUrl = null }) { Text("Cancel", color = TextDim) } },
        )
    }
}

@Composable
fun VideoCard(
    video: IngestedVideo,
    onClick: () -> Unit,
    summary: String? = null,
    isSummarizing: Boolean = false,
    onSummarize: (() -> Unit)? = null,
    onShare: (() -> Unit)? = null,
    onDelete: (() -> Unit)? = null,
    onPlayAudio: (() -> Unit)? = null,
) {
    val ctx = LocalContext.current
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
        shape = RoundedCornerShape(14.dp),
        colors = CardDefaults.cardColors(containerColor = DarkCard),
    ) {
        Column(Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.Top) {
                // Channel avatar
                Surface(Modifier.size(40.dp), shape = CircleShape, color = AccentDim) {
                    Box(contentAlignment = Alignment.Center) {
                        Text(video.channel.take(1).uppercase(), color = Accent, fontWeight = FontWeight.Bold)
                    }
                }
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Surface(shape = RoundedCornerShape(5.dp), color = AccentDim) {
                            Text(formatDuration(video.duration), Modifier.padding(horizontal = 6.dp, vertical = 2.dp), color = Accent, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                        }
                        Spacer(Modifier.width(8.dp))
                        Text(video.title, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis, color = TextPrimary, modifier = Modifier.weight(1f))
                    }
                    Spacer(Modifier.height(4.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(video.channel, style = MaterialTheme.typography.labelSmall, color = TextDim)
                        Spacer(Modifier.width(6.dp)); Text("·", color = TextMuted); Spacer(Modifier.width(6.dp))
                        Text(formatViews(video.viewCount), style = MaterialTheme.typography.labelSmall, color = TextDim)
                        Spacer(Modifier.width(6.dp)); Text("·", color = TextMuted); Spacer(Modifier.width(6.dp))
                        Text(video.uploadDate, style = MaterialTheme.typography.labelSmall, color = TextDim)
                    }
                    if (video.transcriptPreview.isNotEmpty() && summary == null) {
                        Spacer(Modifier.height(6.dp))
                        Text(video.transcriptPreview.take(120), style = MaterialTheme.typography.bodySmall, maxLines = 3, overflow = TextOverflow.Ellipsis, color = TextMuted)
                    }
                    // Summary card
                    if (summary != null) {
                        Spacer(Modifier.height(6.dp))
                        Surface(shape = RoundedCornerShape(8.dp), color = Color(0xFF1B2E1B)) {
                            Text(summary.take(200), Modifier.padding(10.dp), color = Color(0xFF4CAF50), style = MaterialTheme.typography.bodySmall, lineHeight = 18.sp)
                        }
                    }
                }
                Icon(Icons.Filled.ChevronRight, null, tint = TextMuted, modifier = Modifier.padding(top = 4.dp))
            }
            // Action chips
            if (onSummarize != null || onShare != null || onDelete != null || onPlayAudio != null) {
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    if (onPlayAudio != null) {
                        Surface(onClick = onPlayAudio, shape = RoundedCornerShape(8.dp), color = Color.White.copy(alpha = 0.06f)) {
                            Row(Modifier.padding(horizontal = 10.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                                Icon(Icons.Filled.PlayArrow, null, tint = Color(0xFF4CAF50), modifier = Modifier.size(14.dp))
                                Spacer(Modifier.width(4.dp))
                                Text("Play", color = Color(0xFF4CAF50), style = MaterialTheme.typography.labelSmall)
                            }
                        }
                    }
                    if (onSummarize != null) {
                        Surface(
                            onClick = { if (!isSummarizing) onSummarize() },
                            shape = RoundedCornerShape(8.dp),
                            color = Color.White.copy(alpha = 0.06f),
                            enabled = !isSummarizing,
                        ) {
                            Row(Modifier.padding(horizontal = 10.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                                if (isSummarizing) {
                                    CircularProgressIndicator(Modifier.size(14.dp), color = Accent, strokeWidth = 2.dp)
                                } else {
                                    Icon(Icons.Filled.Summarize, null, tint = TextDim, modifier = Modifier.size(14.dp))
                                }
                                Spacer(Modifier.width(4.dp))
                                Text(if (isSummarizing) "Summarizing…" else "Summarize", color = TextDim, style = MaterialTheme.typography.labelSmall)
                            }
                        }
                    }
                    if (onShare != null) {
                        Surface(onClick = onShare, shape = RoundedCornerShape(8.dp), color = Color.White.copy(alpha = 0.06f)) {
                            Row(Modifier.padding(horizontal = 10.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                                Icon(Icons.Filled.Share, null, tint = TextDim, modifier = Modifier.size(14.dp))
                                Spacer(Modifier.width(4.dp))
                                Text("Share", color = TextDim, style = MaterialTheme.typography.labelSmall)
                            }
                        }
                    }
                    if (onDelete != null) {
                        Surface(onClick = onDelete, shape = RoundedCornerShape(8.dp), color = Color.White.copy(alpha = 0.06f)) {
                            Row(Modifier.padding(horizontal = 10.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                                Icon(Icons.Filled.Delete, null, tint = TextDim, modifier = Modifier.size(14.dp))
                                Spacer(Modifier.width(4.dp))
                                Text("Delete", color = TextDim, style = MaterialTheme.typography.labelSmall)
                            }
                        }
                    }
                }
            }
        }
    }
}

fun formatDuration(seconds: Int): String {
    val m = seconds / 60; val s = seconds % 60
    return if (m > 0) "${m}:${s.toString().padStart(2, '0')}" else "0:${s.toString().padStart(2, '0')}"
}

fun formatViews(views: Long): String = when {
    views >= 1_000_000_000 -> "${"%.1f".format(views / 1_000_000_000.0)}B"
    views >= 1_000_000 -> "${"%.1f".format(views / 1_000_000.0)}M"
    views >= 1_000 -> "${"%.1f".format(views / 1_000.0)}K"
    else -> "$views"
}

fun parseIngestedVideo(json: JSONObject): IngestedVideo = IngestedVideo(
    url = json.optString("url"), title = json.optString("title", "Untitled"), channel = json.optString("channel", "Unknown"),
    duration = json.optInt("duration", 0), viewCount = json.optLong("view_count", 0), uploadDate = json.optString("upload_date", ""),
    transcriptPreview = json.optString("transcript_preview", ""), ingestedAt = json.optString("ingested_at", ""),
    audioUrl = json.optString("audio_url", ""), videoUrl = json.optString("video_url", ""),
)
