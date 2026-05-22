package com.substrate.ytlab.screen

import android.content.Intent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.substrate.ytlab.network.YtLabApi
import com.substrate.ytlab.ui.*
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun VideoDetailScreen(
    video: IngestedVideo,
    api: YtLabApi,
    onBack: () -> Unit,
) {
    var summary by remember { mutableStateOf<String?>(null) }
    var isLoading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var metadata by remember { mutableStateOf<org.json.JSONObject?>(null) }
    var showFullTranscript by remember { mutableStateOf(false) }
    var fullTranscript by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    val context = LocalContext.current

    // Load full metadata on entry
    LaunchedEffect(video.url) {
        isLoading = true
        metadata = api.getVideoMetadata(video.url)
        fullTranscript = metadata?.optString("transcript", "")
        isLoading = false
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Video", maxLines = 1, overflow = TextOverflow.Ellipsis) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.Filled.ArrowBack, "Back")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = DarkSurface,
                    titleContentColor = TextPrimary,
                ),
                actions = {
                    IconButton(onClick = {
                        val intent = Intent(Intent.ACTION_SEND).apply {
                            type = "text/plain"
                            putExtra(Intent.EXTRA_TEXT, video.url)
                        }
                        context.startActivity(Intent.createChooser(intent, "Share URL"))
                    }) {
                        Icon(Icons.Filled.Share, "Share URL")
                    }
                }
            )
        },
        containerColor = DarkSurface,
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState()),
        ) {
            // Title section
            Column(modifier = Modifier.padding(16.dp)) {
                Text(
                    video.title,
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold,
                    color = TextPrimary,
                )
                Spacer(Modifier.height(8.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Surface(shape = RoundedCornerShape(6.dp), color = AccentDim) {
                        Text(
                            formatDuration(video.duration),
                            modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
                            color = Accent,
                            style = MaterialTheme.typography.labelSmall,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                    Spacer(Modifier.width(10.dp))
                    Text(video.channel, color = TextDim, style = MaterialTheme.typography.bodyMedium)
                    Spacer(Modifier.weight(1f))
                    Text(
                        formatViews(video.viewCount),
                        color = TextDim,
                        style = MaterialTheme.typography.labelMedium,
                    )
                }
                Spacer(Modifier.height(4.dp))
                Text("Uploaded ${video.uploadDate}", color = TextMuted, style = MaterialTheme.typography.labelSmall)
            }

            HorizontalDivider(color = TextMuted.copy(alpha = 0.3f))

            // Summarize button
            if (summary == null) {
                Button(
                    onClick = {
                        scope.launch {
                            isLoading = true
                            error = null
                            val result = api.summarizeVideo(video.url, "bullet")
                            if (result != null && !result.has("error")) {
                                summary = result.optString("summary", result.optString("text", "No summary returned"))
                            } else {
                                error = result?.optString("error", "Summary failed")
                            }
                            isLoading = false
                        }
                    },
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(16.dp),
                    enabled = !isLoading,
                    colors = ButtonDefaults.buttonColors(containerColor = Accent),
                    shape = RoundedCornerShape(12.dp),
                ) {
                    if (isLoading) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(20.dp),
                            color = TextPrimary,
                            strokeWidth = 2.dp,
                        )
                        Spacer(Modifier.width(8.dp))
                        Text("Summarizing…")
                    } else {
                        Icon(Icons.Filled.Summarize, null)
                        Spacer(Modifier.width(8.dp))
                        Text("Generate AI Summary")
                    }
                }
            }

            // Error
            if (error != null) {
                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp),
                    colors = CardDefaults.cardColors(containerColor = AccentDim),
                ) {
                    Row(modifier = Modifier.padding(12.dp)) {
                        Icon(Icons.Filled.ErrorOutline, null, tint = Accent)
                        Spacer(Modifier.width(8.dp))
                        Text(error!!, color = Accent, style = MaterialTheme.typography.bodySmall)
                    }
                }
            }

            // Summary section
            if (summary != null) {
                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(16.dp),
                    shape = RoundedCornerShape(12.dp),
                    colors = CardDefaults.cardColors(containerColor = DarkCard),
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Filled.Summarize, null, tint = Green, modifier = Modifier.size(20.dp))
                            Spacer(Modifier.width(8.dp))
                            Text("AI Summary", fontWeight = FontWeight.SemiBold, color = Green)
                            Spacer(Modifier.weight(1f))
                            IconButton(onClick = {
                                val sendIntent = Intent(Intent.ACTION_SEND).apply {
                                    type = "text/plain"
                                    putExtra(Intent.EXTRA_TEXT, "${video.title}\n\n$summary")
                                }
                                context.startActivity(Intent.createChooser(sendIntent, "Share Summary"))
                            }) {
                                Icon(Icons.Filled.Share, "Share summary", tint = TextDim, modifier = Modifier.size(20.dp))
                            }
                        }
                        Spacer(Modifier.height(8.dp))
                        Text(summary!!, color = TextPrimary, style = MaterialTheme.typography.bodyMedium)
                    }
                }
            }

            // Transcript section
            val transcript = fullTranscript ?: video.transcriptPreview
            if (transcript.isNotEmpty()) {
                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 8.dp),
                    shape = RoundedCornerShape(12.dp),
                    colors = CardDefaults.cardColors(containerColor = DarkCard),
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Filled.Description, null, tint = TextDim, modifier = Modifier.size(20.dp))
                            Spacer(Modifier.width(8.dp))
                            Text("Transcript", fontWeight = FontWeight.SemiBold, color = TextDim)
                            Spacer(Modifier.weight(1f))
                            IconButton(onClick = { showFullTranscript = !showFullTranscript }) {
                                Icon(
                                    if (showFullTranscript) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore,
                                    "Toggle",
                                    tint = TextDim,
                                    modifier = Modifier.size(20.dp),
                                )
                            }
                        }
                        Spacer(Modifier.height(4.dp))
                        Text(
                            transcript,
                            maxLines = if (showFullTranscript) Int.MAX_VALUE else 8,
                            style = MaterialTheme.typography.bodySmall,
                            color = TextDim,
                        )
                    }
                }
            }

            // Metadata
            Card(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 8.dp),
                shape = RoundedCornerShape(12.dp),
                colors = CardDefaults.cardColors(containerColor = DarkCard),
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text("Details", fontWeight = FontWeight.SemiBold, color = TextDim)
                    Spacer(Modifier.height(8.dp))
                    MetadataRow("URL", video.url)
                    MetadataRow("Channel", video.channel)
                    MetadataRow("Duration", formatDuration(video.duration))
                    MetadataRow("Views", formatViews(video.viewCount))
                    MetadataRow("Uploaded", video.uploadDate)
                    MetadataRow("Ingested", video.ingestedAt.take(16))
                }
            }

            Spacer(Modifier.height(80.dp))
        }
    }
}

@Composable
fun MetadataRow(label: String, value: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 3.dp),
    ) {
        Text(label, color = TextMuted, style = MaterialTheme.typography.labelSmall, modifier = Modifier.width(80.dp))
        Text(value, color = TextPrimary, style = MaterialTheme.typography.bodySmall)
    }
}
