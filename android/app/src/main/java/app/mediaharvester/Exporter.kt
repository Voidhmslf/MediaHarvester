package app.mediaharvester

import android.content.ContentValues
import android.content.Context
import android.provider.MediaStore
import android.util.Log
import android.webkit.MimeTypeMap
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.io.File

/** Переносит готовые файлы из временной папки в общую «Загрузки/MediaHarvester» (MediaStore, без разрешений). */
object Exporter {
    private const val TAG = "Exporter"
    private val _saved = MutableStateFlow<Map<Int, Int>>(emptyMap())

    /** id элемента очереди -> сколько файлов сохранено. */
    val saved: StateFlow<Map<Int, Int>> = _saved

    @Synchronized
    fun exportDone(context: Context, items: List<QueueEntry>) {
        for (item in items) {
            if (item.status != ItemStatus.DONE || item.id in _saved.value) continue
            var count = 0
            for (path in item.files) {
                val file = File(path)
                if (file.isFile && copyToDownloads(context, file, item)) {
                    file.delete()
                    count++
                }
            }
            _saved.value = _saved.value + (item.id to count)
        }
    }

    /** Забыть учёт сохранённого, когда очередь очищена. */
    @Synchronized
    fun reset() {
        _saved.value = emptyMap()
    }

    private fun alreadySaved(context: Context, name: String, relativePath: String): Boolean =
        context.contentResolver.query(
            MediaStore.Downloads.EXTERNAL_CONTENT_URI, arrayOf(MediaStore.Downloads._ID),
            "${MediaStore.Downloads.DISPLAY_NAME} = ? AND ${MediaStore.Downloads.RELATIVE_PATH} = ?",
            arrayOf(name, "$relativePath/"), null,
        )?.use { it.moveToFirst() } ?: false

    private fun copyToDownloads(context: Context, file: File, item: QueueEntry): Boolean = try {
        val resolver = context.contentResolver
        val staging = Bridge.stagingDir(context)
        // Подпапка сохраняется: staging/Instagram_Downloads/x.jpg -> Download/MediaHarvester/Instagram_Downloads/
        val sub = file.parentFile?.relativeToOrNull(staging)?.path?.replace('\\', '/').orEmpty()
        val relative = listOf("Download/MediaHarvester", sub).filter { it.isNotEmpty() }.joinToString("/")
        val mime = MimeTypeMap.getSingleton().getMimeTypeFromExtension(file.extension.lowercase())
        val values = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, file.name)
            put(MediaStore.Downloads.MIME_TYPE, mime ?: "application/octet-stream")
            put(MediaStore.Downloads.RELATIVE_PATH, relative)
            put(MediaStore.Downloads.IS_PENDING, 1)
        }
        if (item.isTracks && file.extension == "mp3" && alreadySaved(context, file.name, relative)) {
            true // трек уже лежит в «Загрузках»: повторный запуск списка не плодит копии
        } else {
        val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
        if (uri == null) {
            false
        } else {
            resolver.openOutputStream(uri)?.use { out -> file.inputStream().use { it.copyTo(out) } }
            values.clear()
            values.put(MediaStore.Downloads.IS_PENDING, 0)
            resolver.update(uri, values, null, null)
            true
        }
        }
    } catch (e: Exception) {
        Log.e(TAG, "Не удалось сохранить ${file.name} (${item.url})", e)
        false
    }
}
