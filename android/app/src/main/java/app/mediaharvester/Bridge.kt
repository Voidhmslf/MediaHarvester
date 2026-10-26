package app.mediaharvester

import android.content.Context
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

enum class ItemStatus { PENDING, WORKING, DONE, ERROR, CANCELLED }

data class QueueEntry(
    val id: Int,
    val url: String,
    val label: String,
    val status: ItemStatus,
    val text: String,
    val progress: Float?,
    val message: String,
    val hint: String,
    val files: List<String>,
    val isTracks: Boolean = false,
    val title: String = "",
    val thumbnail: String = "",
    val uploader: String = "",
    val duration: Int = 0,
    val quality: String = "",
    val qualityOptions: List<String> = emptyList(),
    val probing: Boolean = false,
    val playlist: Boolean = false,
    val playlistOptional: Boolean = false,
    val takePlaylist: Boolean = false,
    val playlistLimit: Int = 0,
    val playlistCount: Int = 0,
)

data class QueueSnapshot(val running: Boolean, val cancelling: Boolean, val items: List<QueueEntry>)

data class EngineInfo(val ytdlp: String, val pending: String, val gallery: String)
data class UpdateInfo(val status: String, val current: String, val latest: String, val message: String)

data class VkLoginResult(val ok: Boolean, val token: String = "", val name: String = "", val error: String = "")

/** Единственная точка доступа к Python-ядру (модуль mh_android). Вызовы могут блокироваться: не из UI-потока. */
object Bridge {
    private var module: PyObject? = null

    @Synchronized
    private fun mod(context: Context): PyObject {
        module?.let { return it }
        val app = context.applicationContext
        if (!Python.isStarted()) Python.start(AndroidPlatform(app))
        val m = Python.getInstance().getModule("mh_android")
        val ffmpeg = Ffmpeg.prepare(app)
        m.callAttr("init", app.filesDir.absolutePath, stagingDir(app).absolutePath, ffmpeg?.binDir ?: "", ffmpeg?.libDir ?: "", Settings.autoUpdate(app))
        module = m
        return m
    }

    /** Временная папка: сюда пишет Python, оттуда файлы переносятся в «Загрузки». */
    fun stagingDir(context: Context): File {
        val app = context.applicationContext
        return File(app.getExternalFilesDir(null) ?: app.filesDir, "staging")
    }

    fun version(context: Context): String = mod(context).callAttr("version").toString()

    fun qualities(context: Context): List<String> {
        val arr = JSONArray(mod(context).callAttr("qualities").toString())
        return List(arr.length()) { arr.getString(it) }
    }

    fun addLinks(context: Context, text: String): Int = mod(context).callAttr("add_links", text).toInt()
    fun engineInfo(context: Context): EngineInfo {
        val o = JSONObject(mod(context).callAttr("engine_versions").toString())
        return EngineInfo(o.optString("ytdlp"), o.optString("pending"), o.optString("gallery_dl"))
    }

    fun updateYtdlp(context: Context): UpdateInfo {
        val o = JSONObject(mod(context).callAttr("update_ytdlp").toString())
        return UpdateInfo(o.optString("status"), o.optString("current"), o.optString("latest"), o.optString("message"))
    }

    fun logTail(context: Context): String = mod(context).callAttr("log_tail").toString()

    fun setCookies(context: Context, path: String) { mod(context).callAttr("set_cookies", path) }

    fun vkAuthUrl(context: Context): String = mod(context).callAttr("vk_auth_url").toString()
    fun vkLogout(context: Context) { mod(context).callAttr("vk_logout") }

    /** Принимает адрес после входа или токен; validate=false — просто запомнить сохранённый токен. */
    fun vkLogin(context: Context, text: String, validate: Boolean = true): VkLoginResult {
        val o = JSONObject(mod(context).callAttr("vk_login", text, validate).toString())
        return VkLoginResult(o.getBoolean("ok"), o.optString("token"), o.optString("name"), o.optString("error"))
    }

    fun addTracks(context: Context, text: String): Int = mod(context).callAttr("add_tracks", text).toInt()
    fun setItemQuality(context: Context, id: Int, quality: String) { mod(context).callAttr("set_item_quality", id, quality) }
    fun setItemPlaylist(context: Context, id: Int, take: Boolean, limit: Int) {
        mod(context).callAttr("set_item_playlist", id, take, limit)
    }

    fun remove(context: Context, id: Int) { mod(context).callAttr("remove", id) }
    fun clearFinished(context: Context) { mod(context).callAttr("clear_finished") }
    fun start(context: Context, quality: String): Boolean = mod(context).callAttr("start", quality).toBoolean()
    fun cancel(context: Context) { mod(context).callAttr("cancel") }

    fun snapshot(context: Context): QueueSnapshot {
        val root = JSONObject(mod(context).callAttr("snapshot").toString())
        val arr = root.getJSONArray("items")
        val items = List(arr.length()) { i ->
            val o = arr.getJSONObject(i)
            val files = o.getJSONArray("files")
            QueueEntry(
                id = o.getInt("id"),
                url = o.getString("url"),
                label = o.getString("label"),
                status = ItemStatus.valueOf(o.getString("status").uppercase()),
                text = o.optString("text"),
                progress = if (o.isNull("progress")) null else o.getDouble("progress").toFloat(),
                message = o.optString("message"),
                hint = o.optString("hint"),
                files = List(files.length()) { files.getString(it) },
                isTracks = o.optString("kind") == "tracks",
                title = o.optString("title"),
                thumbnail = o.optString("thumbnail"),
                uploader = o.optString("uploader"),
                duration = o.optInt("duration"),
                quality = o.optString("quality"),
                qualityOptions = o.optJSONArray("quality_options")?.let { qa -> List(qa.length()) { qa.getString(it) } }.orEmpty(),
                probing = o.optBoolean("probing"),
                playlist = o.optBoolean("playlist"),
                playlistOptional = o.optBoolean("playlist_optional"),
                takePlaylist = o.optBoolean("take_playlist"),
                playlistLimit = o.optInt("playlist_limit"),
                playlistCount = o.optInt("playlist_count"),
            )
        }
        return QueueSnapshot(root.getBoolean("running"), root.getBoolean("cancelling"), items)
    }
}
