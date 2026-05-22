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
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.runtime.*
import androidx.core.app.NotificationCompat
import androidx.lifecycle.lifecycleScope
import com.substrate.ytlab.data.AppDatabase
import com.substrate.ytlab.data.JobEntity
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : ComponentActivity() {

    private val api = YtLabApi("http://localhost:8021")
    private val blogApi = "http://localhost:8006"
    private lateinit var db: AppDatabase
    private var lastShareUrl: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        createNotificationChannel()
        db = AppDatabase.getInstance(this)

        val sharedUrl = extractSharedUrl(intent)
        if (sharedUrl != null) {
            lastShareUrl = sharedUrl
        }

        setContent {
            YtLabApp(
                api = api,
                db = db,
                blogApi = blogApi,
                initialUrl = lastShareUrl,
                onProcessUrl = { url -> processUrl(url) },
            )
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        val url = extractSharedUrl(intent)
        if (url != null) {
            lastShareUrl = url
            lifecycleScope.launch {
                processUrl(url)
            }
        }
    }

    private fun extractSharedUrl(intent: Intent): String? {
        if (intent.action != Intent.ACTION_SEND) return null
        return intent.getStringExtra(Intent.EXTRA_TEXT)?.trim()
    }

    private fun processUrl(url: String) {
        lifecycleScope.launch {
            try {
                if (YtLabApi.isChannelUrl(url)) {
                    val job = JobEntity(url = url, type = "channel", status = "running")
                    val jobId = withContext(Dispatchers.IO) { db.jobDao().insert(job) }

                    showNotification("📺 Ingesting channel…", url.take(60))
                    val result = api.ingestChannel(url, 10)
                    val count = result?.get("count")?.toString() ?: "?"

                    withContext(Dispatchers.IO) {
                        db.jobDao().update(job.copy(
                            id = jobId,
                            title = "Channel: $url".take(100),
                            result = "$count videos ingested",
                            status = "done",
                        ))
                    }
                    showNotification("✅ $count videos", url.take(60))
                } else if (YtLabApi.isVideoUrl(url)) {
                    val job = JobEntity(url = url, type = "video", status = "running")
                    val jobId = withContext(Dispatchers.IO) { db.jobDao().insert(job) }

                    showNotification("📹 Fetching…", url.take(60))
                    val meta = api.getVideoMetadata(url)
                    val title = meta?.get("title")?.toString() ?: "Unknown"
                    val channel = meta?.get("channel")?.toString() ?: "?"
                    val transcript = meta?.get("transcript")?.toString() ?: ""

                    if (transcript.length < 100) {
                        showNotification("⚠️ No transcript", title)
                        withContext(Dispatchers.IO) {
                            db.jobDao().update(job.copy(id = jobId, title = title, channel = channel, status = "error", result = "No transcript"))
                        }
                        return@launch
                    }

                    showNotification("📝 Summarizing…", title)
                    val summary = api.summarizeVideo(url, "bullet")
                    val summaryText: String = (summary?.get("summary") ?: summary?.get("text") ?: summary)?.toString() ?: "Failed"

                    withContext(Dispatchers.IO) {
                        db.jobDao().update(job.copy(
                            id = jobId,
                            title = title,
                            channel = channel,
                            result = summaryText,
                            status = "done",
                        ))
                    }
                    val lines = summaryText.split("\n").take(5).joinToString("\n")
                    showNotification("✅ $title", lines)
                }
            } catch (e: Exception) {
                showNotification("❌ Error", e.message ?: "Unknown")
            }
        }
    }

    private fun showNotification(title: String, body: String) {
        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP
        }
        val pending = PendingIntent.getActivity(
            this, 0, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
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
            val channel = NotificationChannel(
                CHANNEL_ID, "yt-lab", NotificationManager.IMPORTANCE_HIGH
            )
            val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            nm.createNotificationChannel(channel)
        }
    }

    companion object {
        const val CHANNEL_ID = "ytlab_jobs"
    }
}
