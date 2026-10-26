package app.mediaharvester

import android.app.Application
import android.content.Context
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

enum class Tab { LINKS, TRACKS, HISTORY }

data class UiState(
    val ready: Boolean = false,
    val version: String = "",
    val qualities: List<String> = emptyList(),
    val quality: String = "",
    val items: List<QueueEntry> = emptyList(),
    val running: Boolean = false,
    val cancelling: Boolean = false,
    val saved: Map<Int, Int> = emptyMap(),
    val uris: Map<Int, List<String>> = emptyMap(),
    val theme: String = "system",
    val notice: String? = null,
    val input: String = "",
    val tracksInput: String = "",
    val tab: Tab = Tab.LINKS,
    val settingsOpen: Boolean = false,
    val history: List<HistoryEntry> = emptyList(),
    val wifiOnly: Boolean = false,
    val autoUpdate: Boolean = true,
    val folderName: String = Settings.DEFAULT_FOLDER,
    val engines: EngineInfo? = null,
    val updateStatus: String = "",
    val updating: Boolean = false,
    val stagingBytes: Long = 0,
    val vkAuthUrl: String = "",
    val vkLoggedIn: Boolean = false,
    val vkName: String = "",
    val vkAwaiting: Boolean = false,
    val accounts: Set<String> = emptySet(),
    val cookiesImported: Boolean = false,
)

class MainViewModel(app: Application) : AndroidViewModel(app) {
    private val prefs = app.getSharedPreferences("settings", Context.MODE_PRIVATE)
    private val _state = MutableStateFlow(UiState(
        theme = prefs.getString("theme", "system") ?: "system",
        wifiOnly = Settings.wifiOnly(app), autoUpdate = Settings.autoUpdate(app), folderName = Settings.folderName(app),
    ))
    val state: StateFlow<UiState> = _state.asStateFlow()

    private val ctx get() = getApplication<Application>()

    init {
        viewModelScope.launch(Dispatchers.Default) {
            val qualities = Bridge.qualities(ctx)
            val saved = prefs.getString("quality", null)
            History.load(ctx)
            applyAccounts()
            val savedToken = prefs.getString("vk_token", "") ?: ""
            if (savedToken.isNotEmpty()) Bridge.vkLogin(ctx, savedToken, validate = false)
            _state.update {
                it.copy(
                    vkAuthUrl = Bridge.vkAuthUrl(ctx),
                    vkLoggedIn = savedToken.isNotEmpty(),
                    vkName = prefs.getString("vk_name", "") ?: "",
                    ready = true, version = Bridge.version(ctx), qualities = qualities,
                    quality = saved?.takeIf { q -> q in qualities } ?: qualities.first(),
                )
            }
            while (isActive) {
                val snap = Bridge.snapshot(ctx)
                _state.update {
                    it.copy(items = snap.items, running = snap.running, cancelling = snap.cancelling,
                        saved = Exporter.saved.value, uris = Exporter.uris.value, history = History.entries.value)
                }
                delay(500)
            }
        }
    }

    private fun io(block: suspend () -> Unit) = viewModelScope.launch(Dispatchers.Default) { block() }

    /** Добавляет ссылки из текста (вставка, «Поделиться»). */
    fun addLinks(text: String) = io {
        val added = Bridge.addLinks(ctx, text)
        notice(if (added > 0) "Добавлено ссылок: $added" else "Новых ссылок не найдено")
    }

    fun remove(id: Int) = io { Bridge.remove(ctx, id) }

    fun setItemQuality(id: Int, quality: String) = io { Bridge.setItemQuality(ctx, id, quality) }

    fun clearFinished() = io {
        Bridge.clearFinished(ctx)
        if (Bridge.snapshot(ctx).items.isEmpty()) Exporter.reset()
    }

    fun setQuality(q: String) {
        prefs.edit().putString("quality", q).apply()
        _state.update { it.copy(quality = q) }
    }

    fun setTheme(mode: String) {
        prefs.edit().putString("theme", mode).apply()
        _state.update { it.copy(theme = mode) }
    }

    // ───── Настройки ─────
    fun openSettings(open: Boolean) {
        _state.update { it.copy(settingsOpen = open) }
        if (open) io {
            val engines = runCatching { Bridge.engineInfo(ctx) }.getOrNull()
            val bytes = Bridge.stagingDir(ctx).walkTopDown().filter { it.isFile }.sumOf { it.length() }
            _state.update { it.copy(engines = engines, stagingBytes = bytes) }
        }
    }

    fun setWifiOnly(on: Boolean) {
        Settings.setWifiOnly(ctx, on)
        _state.update { it.copy(wifiOnly = on) }
    }

    fun setAutoUpdate(on: Boolean) {
        Settings.setAutoUpdate(ctx, on)
        _state.update { it.copy(autoUpdate = on) }
    }

    fun setFolderName(value: String) {
        Settings.setFolderName(ctx, value)
        _state.update { it.copy(folderName = Settings.folderName(ctx)) }
    }

    fun checkYtdlpUpdate() = io {
        _state.update { it.copy(updating = true, updateStatus = "Проверяю…") }
        val r = runCatching { Bridge.updateYtdlp(ctx) }.getOrNull()
        val text = when (r?.status) {
            "current" -> "Установлена последняя версия (${r.current})"
            "updated" -> "Скачана версия ${r.latest}: она заработает после перезапуска приложения"
            "error" -> "Не удалось проверить: ${r.message.ifBlank { "нет связи с GitHub" }}"
            null -> "Не удалось проверить обновление"
            else -> "Проверка пропущена"
        }
        val engines = runCatching { Bridge.engineInfo(ctx) }.getOrNull()
        _state.update { it.copy(updating = false, updateStatus = text, engines = engines ?: it.engines) }
    }

    /** Текст для «Поделиться»: версии и хвост журнала без секретов. */
    fun diagnostics(): String {
        val s = _state.value
        val e = s.engines ?: runCatching { Bridge.engineInfo(ctx) }.getOrNull()
        val head = "MediaHarvester ${s.version} · yt-dlp ${e?.ytdlp.orEmpty()} · gallery-dl ${e?.gallery.orEmpty()} · Android ${android.os.Build.VERSION.RELEASE}"
        return head + "\n\n" + runCatching { Bridge.logTail(ctx) }.getOrDefault("")
    }

    fun clearStaging() = io {
        if (!_state.value.running) Bridge.stagingDir(ctx).listFiles()?.forEach { it.deleteRecursively() }
        val bytes = Bridge.stagingDir(ctx).walkTopDown().filter { it.isFile }.sumOf { it.length() }
        _state.update { it.copy(stagingBytes = bytes) }
        notice("Временные файлы удалены")
    }

    // ───── История ─────
    fun historyRequeue(entry: HistoryEntry) = io {
        val added = Bridge.addLinks(ctx, entry.url)
        notice(if (added > 0) "Ссылка снова в очереди" else "Эта ссылка уже в очереди")
        if (added > 0) _state.update { it.copy(tab = Tab.LINKS) }
    }

    fun historyRemove(entry: HistoryEntry) = io { History.remove(ctx, entry) }
    fun historyClear() = io { History.clear(ctx) }

    /** Пересобирает общий cookies.txt, отдаёт его движкам и обновляет статусы блока «Аккаунты». */
    private fun applyAccounts() {
        val path = Cookies.rebuild(ctx)
        Bridge.setCookies(ctx, path)
        _state.update {
            it.copy(accounts = SITES.filter { s -> Cookies.isLoggedIn(ctx, s.id) }.map { s -> s.id }.toSet(),
                cookiesImported = Cookies.hasImport(ctx))
        }
    }

    fun accountsChanged(message: String?) = io {
        applyAccounts()
        message?.let { notice(it) }
    }

    fun accountLogout(id: String) = io {
        Cookies.logout(ctx, id)
        applyAccounts()
    }

    fun importCookies(uri: android.net.Uri) = io {
        val count = Cookies.importFile(ctx, uri)
        applyAccounts()
        notice(if (count > 0) "Импортировано cookies: $count" else "Файл не похож на cookies.txt (формат Netscape)")
    }

    fun removeImportedCookies() = io {
        Cookies.removeImport(ctx)
        applyAccounts()
    }

    fun setVkAwaiting(on: Boolean) = _state.update { it.copy(vkAwaiting = on) }

    /** Текст с адресом после входа (или токеном) -> проверка и сохранение токена VK. */
    fun vkLogin(text: String) = io {
        val r = Bridge.vkLogin(ctx, text)
        if (r.ok) {
            prefs.edit().putString("vk_token", r.token).putString("vk_name", r.name).apply()
            _state.update { it.copy(vkLoggedIn = true, vkName = r.name, vkAwaiting = false) }
            notice(if (r.name.isNotEmpty()) "Вход выполнен: ${r.name}" else "Вход выполнен")
        } else {
            notice(r.error)
        }
    }

    fun vkLogout() = io {
        Bridge.vkLogout(ctx)
        prefs.edit().remove("vk_token").remove("vk_name").apply()
        _state.update { it.copy(vkLoggedIn = false, vkName = "", vkAwaiting = false) }
    }

    fun setTab(tab: Tab) = _state.update { it.copy(tab = tab) }

    fun setTracksInput(text: String) = _state.update { it.copy(tracksInput = text) }

    fun pasteTracks(clip: String) = _state.update {
        it.copy(tracksInput = listOf(it.tracksInput.trimEnd(), clip.trim()).filter { part -> part.isNotEmpty() }.joinToString("\n"))
    }

    fun clearTracks() = _state.update { it.copy(tracksInput = "") }

    /** Кнопка «В очередь» в режиме треков: весь список уходит в очередь одним элементом. */
    fun queueTracks() = io { flushTracks() }

    private fun flushTracks() {
        val text = _state.value.tracksInput
        if (text.isBlank()) return
        val count = Bridge.addTracks(ctx, text)
        if (count > 0) _state.update { it.copy(tracksInput = "") }
        notice(if (count > 0) "Список добавлен: треков $count" else "Не нашёл в списке треков или он уже в очереди")
    }

    fun setInput(text: String) = _state.update { it.copy(input = text) }

    /** Кнопка «Вставить»: текст из буфера попадает в поле, чтобы его было видно и можно было поправить. */
    fun pasteInto(clip: String) = _state.update {
        it.copy(input = listOf(it.input.trimEnd(), clip.trim()).filter { part -> part.isNotEmpty() }.joinToString("\n"))
    }

    /** Кнопка «В очередь»: ссылки из поля уходят в очередь. */
    fun queueInput() = io { flushInput() }

    private fun flushInput() {
        val text = _state.value.input
        if (text.isBlank()) return
        _state.update { it.copy(input = "") }
        val added = Bridge.addLinks(ctx, text)
        notice(if (added > 0) "Добавлено ссылок: $added" else "Новых ссылок не найдено")
    }

    /** Старт или остановка. Ссылки, оставшиеся в поле, сначала добавляются в очередь. */
    fun toggleDownload() = io {
        val s = _state.value
        if (!s.running) {
            flushInput()
            flushTracks()
        }
        if (s.running) {
            Bridge.cancel(ctx)
        } else if (s.wifiOnly && !Settings.onUnmeteredNetwork(ctx)) {
            notice("Включён режим «Только по Wi-Fi»: подключитесь к Wi-Fi или выключите его в настройках")
        } else if (Bridge.start(ctx, s.quality)) {
            withContext(Dispatchers.Main) { DownloadService.start(ctx) }
        } else {
            notice("Добавьте ссылки в очередь")
        }
    }

    fun dismissNotice() = _state.update { it.copy(notice = null) }

    private fun notice(text: String) = _state.update { it.copy(notice = text) }
}
