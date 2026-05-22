package com.substrate.ytlab.screen

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
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
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LibraryScreen(
    videos: List<IngestedVideo>,
    onVideoClick: (IngestedVideo) -> Unit,
    onRefresh: () -> Unit,
    isRefreshing: Boolean,
) {
    var searchQuery by remember { mutableStateOf("") }
    var filterChannel by remember { mutableStateOf<String?>(null) }

    val channels = remember(videos) { videos.map { it.channel }.distinct().sorted() }
    val filtered = remember(videos, searchQuery, filterChannel) {
        videos.filter { v ->
            (searchQuery.isEmpty() || v.title.contains(searchQuery, true) || v.channel.contains(searchQuery, true)) &&
            (filterChannel == null || v.channel == filterChannel)
        }
    }

    Column(modifier = Modifier.fillMaxSize()) {
        // Search bar
        OutlinedTextField(
            value = searchQuery,
            onValueChange = { searchQuery = it },
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 8.dp),
            placeholder = { Text("Search ${videos.size} videos…", color = TextDim) },
            leadingIcon = { Icon(Icons.Filled.Search, null, tint = TextDim) },
            trailingIcon = {
                if (searchQuery.isNotEmpty()) {
                    IconButton(onClick = { searchQuery = "" }) {
                        Icon(Icons.Filled.Close, "Clear", tint = TextDim)
                    }
                }
            },
            singleLine = true,
            shape = RoundedCornerShape(12.dp),
            colors = OutlinedTextFieldDefaults.colors(
                focusedBorderColor = Accent,
                unfocusedBorderColor = TextMuted,
                cursorColor = Accent,
                focusedContainerColor = DarkCard,
                unfocusedContainerColor = DarkCard,
            ),
        )

        // Channel filter chips
        if (channels.size > 1) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 4.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                FilterChip(
                    selected = filterChannel == null,
                    onClick = { filterChannel = null },
                    label = { Text("All") },
                    colors = FilterChipDefaults.filterChipColors(
                        selectedContainerColor = AccentDim,
                        selectedLabelColor = Accent,
                    ),
                )
                channels.take(4).forEach { ch ->
                    FilterChip(
                        selected = filterChannel == ch,
                        onClick = { filterChannel = if (filterChannel == ch) null else ch },
                        label = { Text(ch, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                        colors = FilterChipDefaults.filterChipColors(
                            selectedContainerColor = AccentDim,
                            selectedLabelColor = Accent,
                        ),
                    )
                }
            }
        }

        // Video list
        if (filtered.isEmpty() && !isRefreshing) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(Icons.Filled.VideoLibrary, null, tint = TextMuted, modifier = Modifier.size(64.dp))
                    Spacer(Modifier.height(12.dp))
                    Text(
                        if (videos.isEmpty()) "No videos ingested yet" else "No results",
                        color = TextDim,
                    )
                    if (videos.isEmpty()) {
                        Text("Share a YouTube link to start", color = TextMuted, style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        } else {
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                item {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            "${filtered.size} video${if (filtered.size != 1) "s" else ""}",
                            style = MaterialTheme.typography.labelMedium,
                            color = TextDim,
                        )
                        IconButton(onClick = onRefresh) {
                            Icon(Icons.Filled.Refresh, "Refresh", tint = TextDim)
                        }
                    }
                }
                items(filtered, key = { it.url }) { video ->
                    VideoCard(video, onClick = { onVideoClick(video) })
                }
                item { Spacer(Modifier.height(80.dp)) }
            }
        }
    }
}

@Composable
fun VideoCard(video: IngestedVideo, onClick: () -> Unit) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = DarkCard),
    ) {
        Row(
            modifier = Modifier.padding(16.dp),
            verticalAlignment = Alignment.Top,
        ) {
            // Duration badge
            Surface(
                shape = RoundedCornerShape(6.dp),
                color = AccentDim,
            ) {
                Text(
                    text = formatDuration(video.duration),
                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
                    style = MaterialTheme.typography.labelSmall,
                    color = Accent,
                    fontWeight = FontWeight.Bold,
                )
            }
            Spacer(Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    video.title,
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.Medium,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    color = TextPrimary,
                )
                Spacer(Modifier.height(4.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(video.channel, style = MaterialTheme.typography.labelSmall, color = TextDim)
                    Spacer(Modifier.width(8.dp))
                    Text("·", color = TextMuted)
                    Spacer(Modifier.width(8.dp))
                    Text(formatViews(video.viewCount), style = MaterialTheme.typography.labelSmall, color = TextDim)
                    Spacer(Modifier.width(8.dp))
                    Text("·", color = TextMuted)
                    Spacer(Modifier.width(8.dp))
                    Text(video.uploadDate, style = MaterialTheme.typography.labelSmall, color = TextDim)
                }
                if (video.transcriptPreview.isNotEmpty()) {
                    Spacer(Modifier.height(6.dp))
                    Text(
                        video.transcriptPreview.take(120),
                        style = MaterialTheme.typography.bodySmall,
                        maxLines = 3,
                        overflow = TextOverflow.Ellipsis,
                        color = TextMuted,
                    )
                }
            }
            Icon(Icons.Filled.ChevronRight, null, tint = TextMuted, modifier = Modifier.padding(top = 4.dp))
        }
    }
}

fun formatDuration(seconds: Int): String {
    val m = seconds / 60
    val s = seconds % 60
    return if (m > 0) "${m}:${s.toString().padStart(2, '0')}" else "0:${s.toString().padStart(2, '0')}"
}

fun formatViews(views: Long): String = when {
    views >= 1_000_000_000 -> "${"%.1f".format(views / 1_000_000_000.0)}B"
    views >= 1_000_000 -> "${"%.1f".format(views / 1_000_000.0)}M"
    views >= 1_000 -> "${"%.1f".format(views / 1_000.0)}K"
    else -> "$views"
}

fun parseIngestedVideo(json: JSONObject): IngestedVideo = IngestedVideo(
    url = json.optString("url"),
    title = json.optString("title", "Untitled"),
    channel = json.optString("channel", "Unknown"),
    duration = json.optInt("duration", 0),
    viewCount = json.optLong("view_count", 0),
    uploadDate = json.optString("upload_date", ""),
    transcriptPreview = json.optString("transcript_preview", ""),
    ingestedAt = json.optString("ingested_at", ""),
)
