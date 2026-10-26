package app.mediaharvester

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** Запись истории: чем закончилась загрузка одного элемента очереди. */
data class HistoryEntry(
    val time: Long,
    val url: String,
    val label: String,
    val ok: Boolean,
    val text: String,
    val files: Int,
    val isTracks: Boolean,
    val folder: String = Settings.DEFAULT_FOLDER,
    val title: String = "",
)

/** Журнал завершённых загрузок (последние 200) в файле history.json; ссылки можно вернуть в очередь. */
object History {
    private const val LIMIT = 200
    private val recorded = mutableSetOf<Int>()
    private val _entries = MutableStateFlow<List<HistoryEntry>>(emptyList())
    val entries: StateFlow<List<HistoryEntry>> = _entries

    private fun file(context: Context) = File(context.applicationContext.filesDir, "history.json")

    @Synchronized
    fun load(context: Context) {
        val f = file(context)
        if (!f.isFile) return
        _entries.value = try {
            val arr = JSONArray(f.readText())
            List(arr.length()) { i ->
                val o = arr.getJSONObject(i)
                HistoryEntry(
                    o.getLong("time"), o.getString("url"), o.getString("label"), o.getBoolean("ok"),
                    o.optString("text"), o.optInt("files"), o.optBoolean("tracks"),
                    o.optString("folder").ifEmpty { Settings.DEFAULT_FOLDER },
                    o.optString("title"),
                )
            }
        } catch (e: Exception) {
            emptyList()
        }
    }

    /** Добавляет в историю завершённые элементы очереди (каждый только один раз). saved — сколько файлов сохранено. */
    @Synchronized
    fun record(context: Context, items: List<QueueEntry>, saved: Map<Int, Int>) {
        val fresh = items.filter { it.id !in recorded && (it.status == ItemStatus.ERROR || (it.status == ItemStatus.DONE && it.id in saved)) }
        if (fresh.isEmpty()) return
        val now = System.currentTimeMillis()
        val added = fresh.map {
            recorded += it.id
            HistoryEntry(
                time = now, url = it.url, label = it.label, ok = it.status == ItemStatus.DONE,
                text = if (it.status == ItemStatus.DONE) "" else it.message.ifBlank { "Ошибка" },
                files = saved[it.id] ?: 0, isTracks = it.isTracks, folder = Settings.folderName(context), title = it.title,
            )
        }
        save(context, (added.reversed() + _entries.value).take(LIMIT))
    }

    @Synchronized
    fun remove(context: Context, entry: HistoryEntry) = save(context, _entries.value.filterNot { it === entry || (it.time == entry.time && it.url == entry.url) })

    @Synchronized
    fun clear(context: Context) = save(context, emptyList())

    private fun save(context: Context, list: List<HistoryEntry>) {
        _entries.value = list
        val arr = JSONArray()
        list.forEach {
            arr.put(JSONObject().put("time", it.time).put("url", it.url).put("label", it.label).put("ok", it.ok)
                .put("text", it.text).put("files", it.files).put("tracks", it.isTracks).put("folder", it.folder).put("title", it.title))
        }
        file(context).writeText(arr.toString())
    }
}
