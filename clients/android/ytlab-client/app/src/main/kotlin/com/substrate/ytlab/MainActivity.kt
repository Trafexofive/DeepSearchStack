package com.substrate.ytlab

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.core.app.NotificationCompat
import androidx.lifecycle.lifecycleScope
import androidx.navigation.NavType
import androidx.navigation.compose.*
import androidx.navigation.navArgument
import com.substrate.ytlab.data.AppDatabase
import com.substrate.ytlab.data.JobEntity
import com.substrate.ytlab.network.YtLabApi
import com.substrate.ytlab.screen.*
import com.substrate.ytlab.ui.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL

class MainActivity : ComponentActivity() {

    private val api = YtLabApi()
    private lateinit var db: AppDatabase

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        createNotificationChannel()
        db = AppDatabase.getInstance(this)

        val sharedUrl = extractSharedUrl(intent)

        setContent {
            YtLabTheme {
                YtLabNavHost(
                    api = api,
                    db = db,
                    initialUrl = sharedUrl,
                    onProcessUrl = { url -> processUrl(url) },
                )
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        val url = extractSharedUrl(intent)
        if (url != null) {
            lifecycleScope.launch { processUrl(url) }
        }
    }

    private fun extractSharedUrl(intent: Intent): String? {
        if (intent.action != Intent.ACTION_SEND) return null
        return intent.getStringExtra(Intent.EXTRA_TEXT)?.trim()
    }

    private fun processUrl(url: String) {
        lifecycleScope.launch {
            try {
                val job = JobEntity(url = url, type = if (YtLabApi.isChannelUrl(url)) "channel" else "video", status = "running")
                val jobId = withContext(Dispatchers.IO) { db.jobDao().insert(job) }

                if (YtLabApi.isChannelUrl(url)) {
                    showNotification("📺 Ingesting channel…", url.take(60))
                    val result = api.ingestChannel(url, 10)
                    val count = result?.optInt("count", result?.optInt("videos_found", 0) ?: 0) ?: 0
                    withContext(Dispatchers.IO) {
                        db.jobDao().update(job.copy(id = jobId, title = "Channel", result = "$count videos", status = "done"))
                    }
                    showNotification("✅ $count videos", url.take(60))
                } else if (YtLabApi.isVideoUrl(url)) {
                    showNotification("📹 Fetching video…", url.take(60))

                    val meta = api.getVideoMetadata(url)
                    val title = meta?.optString("title", "Unknown") ?: "Unknown"
                    val transcript = meta?.optString("transcript", "") ?: ""

                    if (transcript.length < 100) {
                        showNotification("⚠️ No transcript", title)
                        withContext(Dispatchers.IO) {
                            db.jobDao().update(job.copy(id = jobId, title = title, status = "error", result = "No transcript"))
                        }
                        return@launch
                    }

                    showNotification("📝 Summarizing…", title)
                    val summary = api.summarizeVideo(url, "bullet")
                    val summaryText = summary?.optString("summary", summary?.optString("text", "Failed")) ?: "Failed"

                    withContext(Dispatchers.IO) {
                        db.jobDao().update(job.copy(id = jobId, title = title, result = summaryText, status = "done"))
                    }
                    showNotification("✅ $title", summaryText.take(120))
                }
            } catch (e: Exception) {
                showNotification("❌ Error", e.message ?: "Unknown")
            }
        }
    }

    private fun showNotification(title: String, body: String) {
        val intent = Intent(this, MainActivity::class.java).apply { flags = Intent.FLAG_ACTIVITY_SINGLE_TOP }
        val pending = PendingIntent.getActivity(this, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setContentIntent(pending)
            .setAutoCancel(true)
            .build()
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.notify(title.hashCode(), notification)
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(CHANNEL_ID, "yt-lab", NotificationManager.IMPORTANCE_HIGH)
            val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            nm.createNotificationChannel(channel)
        }
    }

    companion object {
        const val CHANNEL_ID = "ytlab_jobs"
    }
}

// ── Navigation ──────────────────────────────────────────────

sealed class Screen(val route: String, val icon: ImageVector, val label: String) {
    object Library : Screen("library", Icons.Filled.VideoLibrary, "Library")
    object Status : Screen("status", Icons.Filled.Dashboard, "Status")
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun YtLabNavHost(
    api: YtLabApi,
    db: AppDatabase,
    initialUrl: String?,
    onProcessUrl: (String) -> Unit,
) {
    val navController = rememberNavController()
    val screens = listOf(Screen.Library, Screen.Status)
    var currentScreen by remember { mutableStateOf<Screen>(Screen.Library) }

    // Load ingested videos
    var ingestedVideos by remember { mutableStateOf(listOf<IngestedVideo>()) }
    var isRefreshing by remember { mutableStateOf(false) }

    fun refreshLibrary() {
        kotlinx.coroutines.MainScope().launch {
            isRefreshing = true
            try {
                val data = api.getIngestedVideos()
                val arr = data?.optJSONArray("videos")
                if (arr != null) {
                    ingestedVideos = (0 until arr.length()).map { i -> parseIngestedVideo(arr.getJSONObject(i)) }
                }
            } catch (_: Exception) {}
            isRefreshing = false
        }
    }

    LaunchedEffect(Unit) { refreshLibrary() }

    // Handle share URL
    LaunchedEffect(initialUrl) {
        if (initialUrl != null && YtLabApi.isVideoUrl(initialUrl)) {
            onProcessUrl(initialUrl)
            // Refresh library after short delay
            kotlinx.coroutines.delay(3000)
            refreshLibrary()
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
            )
        },
        bottomBar = {
            NavigationBar(containerColor = DarkCard) {
                screens.forEach { screen ->
                    NavigationBarItem(
                        selected = currentScreen == screen,
                        onClick = {
                            currentScreen = screen
                            navController.navigate(screen.route) {
                                popUpTo(navController.graph.startDestinationId) { saveState = true }
                                launchSingleTop = true
                                restoreState = true
                            }
                        },
                        icon = { Icon(screen.icon, screen.label) },
                        label = { Text(screen.label) },
                        colors = NavigationBarItemDefaults.colors(
                            selectedIconColor = Accent,
                            indicatorColor = AccentDim,
                        ),
                    )
                }
            }
        },
        containerColor = DarkSurface,
    ) { padding ->
        NavHost(
            navController = navController,
            startDestination = Screen.Library.route,
            modifier = Modifier.padding(padding),
        ) {
            composable(Screen.Library.route) {
                LibraryScreen(
                    videos = ingestedVideos,
                    onVideoClick = { video ->
                        navController.navigate("video/${video.url.hashCode()}")
                    },
                    onRefresh = { refreshLibrary() },
                    isRefreshing = isRefreshing,
                )
            }
            composable(Screen.Status.route) {
                StatusScreen(
                    api = api,
                    ingestedCount = ingestedVideos.size,
                    onRefresh = { refreshLibrary() },
                )
            }
            composable(
                "video/{urlHash}",
                arguments = listOf(navArgument("urlHash") { type = NavType.IntType }),
            ) { backStackEntry ->
                val urlHash = backStackEntry.arguments?.getInt("urlHash") ?: 0
                val video = ingestedVideos.find { it.url.hashCode() == urlHash }
                if (video != null) {
                    VideoDetailScreen(
                        video = video,
                        api = api,
                        onBack = { navController.popBackStack() },
                    )
                }
            }
        }
    }
}
