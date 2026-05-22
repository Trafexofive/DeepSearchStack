package com.substrate.ytlab

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

class YtLabApi(private val baseUrl: String) {

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

        fun isYoutubeUrl(url: String) = isVideoUrl(url) || isChannelUrl(url)
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

    suspend fun addWatch(url: String): JSONObject? = withContext(Dispatchers.IO) {
        post("/channels/watch", JSONObject().apply {
            put("channel_url", url)
        })
    }

    suspend fun health(): JSONObject? = withContext(Dispatchers.IO) {
        get("/health")
    }

    private fun get(path: String): JSONObject? {
        return try {
            val conn = URL("$baseUrl$path").openConnection() as HttpURLConnection
            conn.connectTimeout = 10_000
            conn.readTimeout = 15_000
            conn.requestMethod = "GET"

            val code = conn.responseCode
            if (code !in 200..299) return null

            val text = BufferedReader(InputStreamReader(conn.inputStream)).readText()
            conn.disconnect()
            JSONObject(text)
        } catch (e: Exception) {
            null
        }
    }

    private fun post(path: String, body: JSONObject): JSONObject? {
        return try {
            val conn = URL("$baseUrl$path").openConnection() as HttpURLConnection
            conn.connectTimeout = 10_000
            conn.readTimeout = 120_000
            conn.requestMethod = "POST"
            conn.setRequestProperty("Content-Type", "application/json")
            conn.doOutput = true

            OutputStreamWriter(conn.outputStream).use { it.write(body.toString()) }

            val code = conn.responseCode
            if (code !in 200..299) {
                val err = BufferedReader(InputStreamReader(conn.errorStream)).readText()
                conn.disconnect()
                return JSONObject().apply { put("error", err) }
            }

            val text = BufferedReader(InputStreamReader(conn.inputStream)).readText()
            conn.disconnect()
            JSONObject(text)
        } catch (e: Exception) {
            JSONObject().apply { put("error", e.message) }
        }
    }
}
