package app.mediaharvester

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities

/** Настройки загрузки; тема и качество хранятся в тех же SharedPreferences ("settings"). */
object Settings {
    const val DEFAULT_FOLDER = "MediaHarvester"
    val AUDIO_CODECS = listOf("mp3", "m4a", "opus")
    val SHARE_MODES = listOf("queue", "download", "open")

    private fun prefs(context: Context) =
        context.applicationContext.getSharedPreferences("settings", Context.MODE_PRIVATE)

    fun wifiOnly(context: Context): Boolean = prefs(context).getBoolean("wifi_only", false)
    fun setWifiOnly(context: Context, on: Boolean) = prefs(context).edit().putBoolean("wifi_only", on).apply()

    /** Сколько ссылок качается одновременно (1–3). */
    fun parallel(context: Context): Int = prefs(context).getInt("parallel", 1).coerceIn(1, 3)
    fun setParallel(context: Context, value: Int) = prefs(context).edit().putInt("parallel", value.coerceIn(1, 3)).apply()

    /** Формат звука для «Только аудио» и «Треков по списку»: mp3 (320 кбит/с), m4a или opus. */
    fun audioCodec(context: Context): String = prefs(context).getString("audio_codec", "mp3")?.takeIf { it in AUDIO_CODECS } ?: "mp3"
    fun setAudioCodec(context: Context, value: String) = prefs(context).edit().putString("audio_codec", value).apply()

    fun embedCover(context: Context): Boolean = prefs(context).getBoolean("embed_cover", true)
    fun setEmbedCover(context: Context, on: Boolean) = prefs(context).edit().putBoolean("embed_cover", on).apply()

    fun subtitles(context: Context): Boolean = prefs(context).getBoolean("subtitles", false)
    fun setSubtitles(context: Context, on: Boolean) = prefs(context).edit().putBoolean("subtitles", on).apply()

    /** Языки субтитров через запятую (ru,en); «all» — все доступные. */
    fun subtitleLangs(context: Context): String = prefs(context).getString("subtitle_langs", "ru,en").orEmpty().ifBlank { "ru,en" }
    fun setSubtitleLangs(context: Context, value: String) =
        prefs(context).edit().putString("subtitle_langs", value.filter { it.isLetterOrDigit() || it in ",-*." }.ifBlank { "ru,en" }).apply()

    /** Что делать со ссылкой из «Поделиться»: queue — добавить и остаться в другом приложении, download — ещё и скачать, open — открыть MediaHarvester. */
    fun shareMode(context: Context): String = prefs(context).getString("share_mode", "queue")?.takeIf { it in SHARE_MODES } ?: "queue"
    fun setShareMode(context: Context, value: String) = prefs(context).edit().putString("share_mode", value).apply()

    /** Предлагать добавить скопированную ссылку, когда приложение открывается. */
    fun clipboardPrompt(context: Context): Boolean = prefs(context).getBoolean("clipboard_prompt", true)
    fun setClipboardPrompt(context: Context, on: Boolean) = prefs(context).edit().putBoolean("clipboard_prompt", on).apply()

    /** Последняя предложенная ссылка: одну и ту же не показываем дважды. */
    fun lastOfferedClip(context: Context): String = prefs(context).getString("last_clip", "").orEmpty()
    fun setLastOfferedClip(context: Context, value: String) = prefs(context).edit().putString("last_clip", value).apply()

    fun autoUpdate(context: Context): Boolean = prefs(context).getBoolean("auto_update", true)
    fun setAutoUpdate(context: Context, on: Boolean) = prefs(context).edit().putBoolean("auto_update", on).apply()

    /** Имя папки внутри «Загрузок», куда попадают готовые файлы. */
    fun folderName(context: Context): String = sanitizeFolder(prefs(context).getString("folder", DEFAULT_FOLDER).orEmpty())

    fun setFolderName(context: Context, value: String) {
        prefs(context).edit().putString("folder", sanitizeFolder(value)).apply()
    }

    fun sanitizeFolder(value: String): String =
        value.replace(Regex("""[\\/:*?"<>|]"""), "").trim().trim('.').take(60).ifEmpty { DEFAULT_FOLDER }

    /** Сеть без лимита трафика (обычно Wi-Fi). Если определить нельзя, считаем, что можно качать. */
    fun onUnmeteredNetwork(context: Context): Boolean {
        val manager = context.applicationContext.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
            ?: return true
        val caps = manager.getNetworkCapabilities(manager.activeNetwork ?: return false) ?: return false
        return caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED)
    }
}
