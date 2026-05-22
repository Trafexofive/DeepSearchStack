package com.substrate.ytlab.network

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

class YtLabApi(private val baseUrl: String = "http://localhost:8021") {

    data class IngestProgress(val video: Int, val total: Int, val title: String = "")

    companion object {
        fun isVideoUrl(url: String): Boolean {
            val u = url.lowercase()
            return u.contains("youtube.com/watch") ||
                   u.contains("youtu.be/") ||
                   u.contains("youtube.com/shorts/") ||
                   u.contains("m.youtube.com/watch")
        }
        fun isChannelUrl(url: String): Boolean {
            val u = url.lowercase()
            return u.contains("youtube.com/@") ||
                   u.contains("youtube.com/channel/") ||
                   u.contains("youtube.com/c/")
        }
    }

    suspend fun getVideoMetadata(url: String): JSONObject? = withContext(Dispatchers.IO) {
        val encoded = URLEncoder.encode(url, "UTF-8")
        get("/videos/metadata?video_url=$encoded")
    }

    suspend fun summarizeVideo(url: String, style: String = "bullet"): JSONObject? = withContext(Dispatchers.IO) {
        post("/videos/summarize", JSONObject().apply {
            put("video_url", url)
            put("style", style)
            put("humanize", false)
        })
    }

    suspend fun ingestChannel(url: String, limit: Int = 10): JSONObject? = withContext(Dispatchers.IO) {
        post("/channels/ingest", JSONObject().apply {
            put("channel_url", url)
            put("limit", limit)
        })
    }

    suspend fun ingestVideo(url: String): JSONObject? = withContext(Dispatchers.IO) {
        post("/videos/ingest", JSONObject().apply { put("video_url", url) })
    }

    suspend fun getIngestedVideos(limit: Int = 100, offset: Int = 0): JSONObject? = withContext(Dispatchers.IO) {
        get("/videos/ingested?limit=$limit&offset=$offset")
    }

    suspend fun deleteIngestedVideo(url: String): Boolean = withContext(Dispatchers.IO) {
        try {
            val encoded = URLEncoder.encode(url, "UTF-8")
            val conn = URL("$baseUrl/videos/ingested?url=$encoded").openConnection() as HttpURLConnection
            conn.requestMethod = "DELETE"
            conn.connectTimeout = 5000
            conn.readTimeout = 5000
            conn.responseCode in 200..299
        } catch (_: Exception) { false }
    }

    suspend fun addChannelWatch(url: String): JSONObject? = withContext(Dispatchers.IO) {
        post("/channels/watch", JSONObject().apply { put("channel_url", url) })
    }

    suspend fun getWatchingChannels(): JSONObject? = withContext(Dispatchers.IO) {
        get("/channels/watching")
    }

    suspend fun health(): JSONObject? = withContext(Dispatchers.IO) {
        get("/health")
    }

    suspend fun getBlogStats(): JSONObject? = withContext(Dispatchers.IO) {
        httpGet("http://localhost:8006/stats")
    }

    suspend fun getBlogHealth(): JSONObject? = withContext(Dispatchers.IO) {
        httpGet("http://localhost:8006/health")
    }

    private suspend fun httpGet(url: String): JSONObject? = withContext(Dispatchers.IO) {
        try {
            val conn = URL(url).openConnection() as HttpURLConnection
            conn.connectTimeout = 5000
            conn.readTimeout = 5000
            if (conn.responseCode !in 200..299) return@withContext null
            val text = BufferedReader(InputStreamReader(conn.inputStream)).readText()
            conn.disconnect()
            JSONObject(text)
        } catch (_: Exception) { null }
    }

    private fun get(path: String): JSONObject? {
        return try {
            val conn = URL("$baseUrl$path").openConnection() as HttpURLConnection
            conn.connectTimeout = 10_000
            conn.readTimeout = 30_000
            if (conn.responseCode !in 200..299) return null
            val text = BufferedReader(InputStreamReader(conn.inputStream)).readText()
            conn.disconnect()
            JSONObject(text)
        } catch (_: Exception) { null }
    }

    private suspend fun post(path: String, body: JSONObject): JSONObject? = withContext(Dispatchers.IO) {
        try {
            val conn = URL("$baseUrl$path").openConnection() as HttpURLConnection
            conn.connectTimeout = 10_000
            conn.readTimeout = 120_000
            conn.requestMethod = "POST"
            conn.setRequestProperty("Content-Type", "application/json")
            conn.doOutput = true
            OutputStreamWriter(conn.outputStream).use { it.write(body.toString()) }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val text = BufferedReader(InputStreamReader(stream ?: conn.inputStream)).readText()
            conn.disconnect()
            if (code in 200..299) JSONObject(text) else JSONObject().apply { put("error", text) }
        } catch (e: Exception) {
            JSONObject().apply { put("error", e.message ?: "Unknown") }
        }
    }
}
