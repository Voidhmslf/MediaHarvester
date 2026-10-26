package app.mediaharvester

import android.content.Context
import android.net.Uri
import android.webkit.CookieManager
import java.io.File

/** Сервис, в который можно войти во встроенном браузере. keyCookies — признак того, что вход действительно выполнен. */
data class Site(
    val id: String,
    val name: String,
    val loginUrl: String,
    val roots: List<String>,
    val keyCookies: List<String>,
    val note: String = "",
)

val SITES = listOf(
    Site("instagram", "Instagram", "https://www.instagram.com/accounts/login/", listOf("instagram.com"), listOf("sessionid"),
        "Закрытые аккаунты, истории, возрастные ограничения"),
    Site("youtube", "YouTube", "https://accounts.google.com/ServiceLogin?service=youtube&continue=https%3A%2F%2Fwww.youtube.com%2F",
        listOf("youtube.com", "google.com"), listOf("__Secure-3PSID", "SID"),
        "18+, «подтвердите, что вы не бот». Google может не пустить во встроенный браузер: тогда импортируйте cookies.txt"),
    Site("tiktok", "TikTok", "https://www.tiktok.com/login", listOf("tiktok.com"), listOf("sessionid"),
        "Закрытые и возрастные видео"),
    Site("x", "X (Twitter)", "https://x.com/i/flow/login", listOf("x.com", "twitter.com"), listOf("auth_token"),
        "Посты с ограничением"),
    Site("reddit", "Reddit", "https://www.reddit.com/login/", listOf("reddit.com"), listOf("reddit_session"),
        "NSFW и закрытые сообщества"),
    Site("pinterest", "Pinterest", "https://www.pinterest.com/login/", listOf("pinterest.com"), listOf("_pinterest_sess"),
        "Секретные доски"),
)

/**
 * Cookies входа хранятся по файлу на сервис (формат Netscape) и склеиваются в один cookies.txt для yt-dlp и gallery-dl.
 * Файлы лежат в закрытой папке приложения.
 */
object Cookies {
    private const val IMPORT_ID = "import"
    private const val HEADER = "# Netscape HTTP Cookie File"
    private const val YEAR_SECONDS = 365L * 24 * 3600

    private fun dir(context: Context) = File(context.filesDir, "cookies").apply { mkdirs() }
    private fun file(context: Context, id: String) = File(dir(context), "$id.txt")
    fun mergedFile(context: Context) = File(context.filesDir, "cookies.txt")

    fun isLoggedIn(context: Context, id: String): Boolean = file(context, id).let { it.isFile && it.length() > 0 }
    fun hasImport(context: Context): Boolean = isLoggedIn(context, IMPORT_ID)

    /** Забирает cookies из WebView. Возвращает false, если вход не обнаружен (нет ключевого cookie). */
    fun capture(context: Context, site: Site): Boolean {
        val manager = CookieManager.getInstance()
        manager.flush()
        val expiry = System.currentTimeMillis() / 1000 + YEAR_SECONDS
        val lines = mutableListOf<String>()
        val names = mutableSetOf<String>()
        for (root in site.roots) {
            val cookies = linkedMapOf<String, String>()
            for (url in listOf("https://www.$root", "https://$root")) {
                manager.getCookie(url)?.split(";")?.forEach { part ->
                    val eq = part.indexOf('=')
                    if (eq > 0) cookies[part.substring(0, eq).trim()] = part.substring(eq + 1).trim()
                }
            }
            for ((name, value) in cookies) {
                names += name
                lines += listOf(".$root", "TRUE", "/", "TRUE", expiry.toString(), name, value).joinToString("\t")
            }
        }
        if (site.keyCookies.none { it in names }) return false
        file(context, site.id).writeText(lines.joinToString("\n") + "\n")
        rebuild(context)
        return true
    }

    fun logout(context: Context, id: String) {
        file(context, id).delete()
        // Сессия во встроенном браузере тоже сбрасывается, чтобы следующий вход был чистым
        CookieManager.getInstance().removeAllCookies(null)
        rebuild(context)
    }

    /** Импорт готового cookies.txt (например, экспортированного расширением браузера). Возвращает число cookies. */
    fun importFile(context: Context, uri: Uri): Int {
        val text = context.contentResolver.openInputStream(uri)?.use { it.readBytes().toString(Charsets.UTF_8) }.orEmpty()
        val lines = text.lines().map { it.trimEnd('\r') }.filter { line ->
            line.isNotBlank() && (!line.startsWith("#") || line.startsWith("#HttpOnly_")) && line.split("\t").size >= 7
        }
        if (lines.isEmpty()) return 0
        file(context, IMPORT_ID).writeText(lines.joinToString("\n") + "\n")
        rebuild(context)
        return lines.size
    }

    fun removeImport(context: Context) {
        file(context, IMPORT_ID).delete()
        rebuild(context)
    }

    /** Склеивает все сохранённые входы в один файл. Возвращает путь или пустую строку, если входов нет. */
    fun rebuild(context: Context): String {
        val parts = dir(context).listFiles { f -> f.isFile && f.extension == "txt" && f.length() > 0 }.orEmpty().sortedBy { it.name }
        val merged = mergedFile(context)
        if (parts.isEmpty()) {
            merged.delete()
            return ""
        }
        merged.writeText(HEADER + "\n" + parts.joinToString("") { it.readText() })
        return merged.absolutePath
    }
}
