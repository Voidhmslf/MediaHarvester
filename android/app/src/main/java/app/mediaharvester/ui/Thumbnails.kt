package app.mediaharvester.ui

import android.graphics.BitmapFactory
import android.util.LruCache
import androidx.compose.runtime.Composable
import androidx.compose.runtime.produceState
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.URL

/** Маленькие обложки для очереди: без сторонних библиотек, с кэшем в памяти. */
private object ThumbCache {
    val cache = LruCache<String, ImageBitmap>(80)
}

private const val TARGET_WIDTH = 360

private fun download(url: String): ImageBitmap? = try {
    val connection = (URL(url).openConnection() as HttpURLConnection).apply {
        connectTimeout = 8000
        readTimeout = 8000
    }
    val bytes = connection.inputStream.use { it.readBytes() }
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
    var sample = 1
    while (bounds.outWidth / (sample * 2) >= TARGET_WIDTH) sample *= 2
    val options = BitmapFactory.Options().apply { inSampleSize = sample }
    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options)?.asImageBitmap()
} catch (e: Exception) {
    null
}

/** Обложка по адресу (только https); null, пока грузится или если не вышло. */
@Composable
fun rememberThumbnail(url: String): ImageBitmap? {
    if (!url.startsWith("https://")) return null
    val state = produceState(initialValue = ThumbCache.cache.get(url), url) {
        if (value == null) {
            value = withContext(Dispatchers.IO) { download(url)?.also { ThumbCache.cache.put(url, it) } }
        }
    }
    return state.value
}
