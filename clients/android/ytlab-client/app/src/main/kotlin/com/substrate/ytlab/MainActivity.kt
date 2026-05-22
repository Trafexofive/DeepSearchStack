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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.core.app.NotificationCompat
import androidx.lifecycle.lifecycleScope
import androidx.navigation.NavType
import androidx.navigation.compose.*
import androidx.navigation.navArgument
import com.substrate.ytlab.network.YtLabApi
import com.substrate.ytlab.screen.*
import com.substrate.ytlab.ui.*
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {

    private val api = YtLabApi()
    private val _pendingUrl = mutableStateOf<String?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        createNotificationChannel()
        _pendingUrl.value = extractSharedUrl(intent)

        setContent {
            YtLabTheme {
                var isProcessing by remember { mutableStateOf(false) }
                var processingStatus by remember { mutableStateOf("") }
                val snackbarHostState = remember { SnackbarHostState() }
                var libraryRefreshKey by remember { mutableIntStateOf(0) }

                fun refreshAndNotify(msg: String) {
                    libraryRefreshKey++
                    kotlinx.coroutines.MainScope().launch {
                        snackbarHostState.showSnackbar(msg)
                    }
                }

                @OptIn(kotlin.ExperimentalStdlibApi::class)
                val processor = remember {
                    { url: String ->
                        lifecycleScope.launch {
                            isProcessing = true
                            try {
                                if (YtLabApi.isChannelUrl(url)) {
                                    processingStatus = "Ingesting channel…"
                                    val r = api.ingestChannel(url, 10)
                                    refreshAndNotify("✅ ${r?.optInt("videos_found", 0) ?: 0} videos ingested")
                                    showNotification("📺 Channel", "${r?.optInt("videos_found", 0) ?: 0} videos")
                                } else if (YtLabApi.isVideoUrl(url)) {
                                    processingStatus = "Fetching metadata…"
                                    val meta = api.getVideoMetadata(url)
                                    val title = meta?.optString("title", "Unknown") ?: "Unknown"
                                    val transcript = meta?.optString("transcript", "") ?: ""

                                    if (transcript.length < 100) {
                                        refreshAndNotify("⚠️ No transcript: $title")
                                        return@launch
                                    }
                                    processingStatus = "Summarizing…"
                                    val summary = api.summarizeVideo(url, "bullet")
                                    val text = summary?.optString("summary", summary?.optString("text", "")) ?: ""
                                    if (text.isNotEmpty()) {
                                        refreshAndNotify("✅ $title")
                                        showNotification("✅ $title", text.take(200))
                                    } else {
                                        refreshAndNotify("❌ Summary failed: $title")
                                    }
                                }
                            } catch (e: Exception) {
                                refreshAndNotify("❌ ${e.message ?: "Error"}")
                            } finally {
                                isProcessing = false
                            }
                        }
                    }
                }

                Scaffold(
                    snackbarHost = {
                        SnackbarHost(snackbarHostState) { data ->
                            Snackbar(snackbarData = data, containerColor = DarkCard, contentColor = TextPrimary)
                        }
                    },
                ) { padding ->
                    Box(modifier = Modifier.padding(padding)) {
                        YtLabNavHost(api = api, refreshKey = libraryRefreshKey, onProcessUrl = processor)

                        if (isProcessing) {
                            Surface(
                                modifier = Modifier.fillMaxSize(),
                                color = DarkSurface.copy(alpha = 0.90f),
                            ) {
                                Box(contentAlignment = Alignment.Center) {
                                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                        CircularProgressIndicator(color = Accent, modifier = Modifier.size(48.dp))
                                        Spacer(Modifier.height(20.dp))
                                        Text(processingStatus, color = TextPrimary, style = MaterialTheme.typography.bodyLarge)
                                    }
                                }
                            }
                        }
                    }
                }

                // Process pending URL from share intent
                LaunchedEffect(_pendingUrl.value) {
                    val url = _pendingUrl.value
                    if (url != null && (YtLabApi.isVideoUrl(url) || YtLabApi.isChannelUrl(url))) {
                        _pendingUrl.value = null
                        processor(url)
                    }
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        extractSharedUrl(intent)?.let { url ->
            _pendingUrl.value = url
        }
    }

    private fun extractSharedUrl(intent: Intent): String? {
        if (intent.action != Intent.ACTION_SEND) return null
        return intent.getStringExtra(Intent.EXTRA_TEXT)?.trim()
    }

    private fun showNotification(title: String, body: String) {
        val pending = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java).apply { flags = Intent.FLAG_ACTIVITY_SINGLE_TOP },
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title).setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setContentIntent(pending).setAutoCancel(true)
            .build()
            .also { (getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager).notify(title.hashCode(), it) }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            (getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager)
                .createNotificationChannel(NotificationChannel(CHANNEL_ID, "yt-lab", NotificationManager.IMPORTANCE_HIGH))
        }
    }

    companion object { const val CHANNEL_ID = "ytlab_jobs" }
}

// ── Navigation ──────────────────────────────────────────────

sealed class Screen(val route: String, val icon: ImageVector, val label: String) {
    object Library : Screen("library", Icons.Filled.VideoLibrary, "Library")
    object Status : Screen("status", Icons.Filled.Dashboard, "Status")
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun YtLabNavHost(api: YtLabApi, refreshKey: Int = 0, onProcessUrl: (String) -> Any = {}) {
    val navController = rememberNavController()
    var currentScreen by remember { mutableStateOf<Screen>(Screen.Library) }
    var ingestedVideos by remember { mutableStateOf(listOf<IngestedVideo>()) }
    var isRefreshing by remember { mutableStateOf(false) }
    var fetchError by remember { mutableStateOf<String?>(null) }
    var showPaste by remember { mutableStateOf(false) }
    var pasteText by remember { mutableStateOf("") }

    fun refreshLibrary() {
        kotlinx.coroutines.MainScope().launch {
            isRefreshing = true
            fetchError = null
            try {
                val data = api.getIngestedVideos()
                if (data == null) {
                    fetchError = "yt-lab unreachable — is the host running?"
                } else {
                    val arr = data.optJSONArray("videos")
                    if (arr != null) {
                        ingestedVideos = (0 until arr.length()).map { i -> parseIngestedVideo(arr.getJSONObject(i)) }
                    }
                }
            } catch (e: Exception) {
                fetchError = "Connection error: ${e.message?.take(60)}"
            }
            isRefreshing = false
        }
    }

    LaunchedEffect(Unit) { refreshLibrary() }
    LaunchedEffect(refreshKey) { if (refreshKey > 0) refreshLibrary() }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("yt-lab", fontWeight = FontWeight.Bold) },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = DarkSurface, titleContentColor = Accent),
                actions = {
                    IconButton(onClick = { showPaste = true }) { Icon(Icons.Filled.AddLink, "Paste URL", tint = TextDim) }
                },
            )
        },
        bottomBar = {
            NavigationBar(containerColor = DarkCard) {
                listOf(Screen.Library, Screen.Status).forEach { screen ->
                    NavigationBarItem(
                        selected = currentScreen == screen,
                        onClick = {
                            currentScreen = screen
                            navController.navigate(screen.route) {
                                popUpTo(navController.graph.startDestinationId) { saveState = true }
                                launchSingleTop = true; restoreState = true
                            }
                        },
                        icon = { Icon(screen.icon, screen.label) },
                        label = { Text(screen.label) },
                        colors = NavigationBarItemDefaults.colors(selectedIconColor = Accent, indicatorColor = AccentDim),
                    )
                }
            }
        },
        containerColor = DarkSurface,
    ) { padding ->
        NavHost(navController = navController, startDestination = Screen.Library.route, modifier = Modifier.padding(padding)) {
            composable(Screen.Library.route) {
                LibraryScreen(videos = ingestedVideos, onVideoClick = { navController.navigate("video/${it.url.hashCode()}") }, onRefresh = { refreshLibrary() }, isRefreshing = isRefreshing, error = fetchError)
            }
            composable(Screen.Status.route) {
                StatusScreen(api = api, ingestedCount = ingestedVideos.size, onRefresh = { refreshLibrary() })
            }
            composable("video/{urlHash}", arguments = listOf(navArgument("urlHash") { type = NavType.IntType })) { backStackEntry ->
                val hash = backStackEntry.arguments?.getInt("urlHash") ?: 0
                ingestedVideos.find { it.url.hashCode() == hash }?.let { VideoDetailScreen(video = it, api = api, onBack = { navController.popBackStack() }) }
            }
        }

        if (showPaste) {
            AlertDialog(
                onDismissRequest = { showPaste = false },
                containerColor = DarkCard,
                title = { Text("Paste YouTube URL", fontWeight = FontWeight.SemiBold) },
                text = {
                    OutlinedTextField(
                        value = pasteText, onValueChange = { pasteText = it },
                        placeholder = { Text("https://youtube.com/watch?v=...", color = TextDim) },
                        modifier = Modifier.fillMaxWidth(), singleLine = true,
                        colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = Accent, unfocusedBorderColor = TextMuted, cursorColor = Accent),
                    )
                },
                confirmButton = {
                    TextButton(onClick = {
                        val u = pasteText.trim(); showPaste = false; pasteText = ""
                        if (YtLabApi.isVideoUrl(u) || YtLabApi.isChannelUrl(u)) onProcessUrl(u)
                    }) { Text("Go", color = Accent) }
                },
                dismissButton = { TextButton(onClick = { showPaste = false; pasteText = "" }) { Text("Cancel", color = TextDim) } },
            )
        }
    }
}
