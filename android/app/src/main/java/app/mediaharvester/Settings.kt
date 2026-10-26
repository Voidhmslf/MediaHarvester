package app.mediaharvester

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities

/** Настройки загрузки; тема и качество хранятся в тех же SharedPreferences ("settings"). */
object Settings {
    const val DEFAULT_FOLDER = "MediaHarvester"

    private fun prefs(context: Context) =
        context.applicationContext.getSharedPreferences("settings", Context.MODE_PRIVATE)

    fun wifiOnly(context: Context): Boolean = prefs(context).getBoolean("wifi_only", false)
    fun setWifiOnly(context: Context, on: Boolean) = prefs(context).edit().putBoolean("wifi_only", on).apply()

    /** Сколько ссылок качается одновременно (1–3). */
    fun parallel(context: Context): Int = prefs(context).getInt("parallel", 1).coerceIn(1, 3)
    fun setParallel(context: Context, value: Int) = prefs(context).edit().putInt("parallel", value.coerceIn(1, 3)).apply()

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
