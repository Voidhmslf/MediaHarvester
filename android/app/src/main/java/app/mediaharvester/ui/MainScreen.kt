package app.mediaharvester.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.mediaharvester.ItemStatus
import app.mediaharvester.MainViewModel
import app.mediaharvester.QueueEntry
import app.mediaharvester.R
import app.mediaharvester.UiState

private val palette @Composable get() = LocalPalette.current

@Composable
fun MainScreen(state: UiState, vm: MainViewModel) {
    val p = palette
    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(state.notice) {
        state.notice?.let {
            snackbar.showSnackbar(it)
            vm.dismissNotice()
        }
    }
    Scaffold(
        containerColor = p.bg,
        snackbarHost = { SnackbarHost(snackbar) },
        bottomBar = { BottomAction(state, vm) },
    ) { inner ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(inner).statusBarsPadding(),
            contentPadding = PaddingValues(Dim.gutter),
            verticalArrangement = Arrangement.spacedBy(Dim.gap),
        ) {
            item { Header(state, vm) }
            item { ModeTabs(state, vm) }
            if (state.tracksMode) {
                item { TracksCard(state, vm) }
            } else {
                item { LinksCard(state, vm) }
                item { QualityCard(state, vm) }
                item { VkCard(state, vm) }
            }
            item { QueueHeader(state, vm) }
            if (state.items.isEmpty()) {
                item { EmptyQueue(state.ready) }
            } else {
                items(state.items, key = { it.id }) { QueueRow(it, state, vm) }
            }
        }
    }
}

@Composable
private fun Header(state: UiState, vm: MainViewModel) {
    val p = palette
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp)) {
        Box(Modifier.size(40.dp).clip(RoundedCornerShape(10.dp)).background(p.accent), contentAlignment = Alignment.Center) {
            Icon(painterResource(R.drawable.ic_launcher_foreground), null, tint = Color.Unspecified, modifier = Modifier.size(56.dp))
        }
        Column(Modifier.weight(1f).padding(start = 12.dp)) {
            Text("MediaHarvester", style = MaterialTheme.typography.headlineSmall, color = p.text)
            if (state.version.isNotEmpty()) Text("v${state.version}", style = MaterialTheme.typography.bodySmall, color = p.textMuted)
        }
        val label = when (state.theme) { "light" -> "Светлая"; "dark" -> "Тёмная"; else -> "Авто" }
        Pill(label, onClick = vm::cycleTheme)
    }
}

@Composable
private fun Card(modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    val p = palette
    Column(
        modifier.fillMaxWidth()
            .clip(RoundedCornerShape(Dim.radiusCard))
            .background(p.card)
            .border(BorderStroke(1.dp, p.cardBorder), RoundedCornerShape(Dim.radiusCard))
            .padding(Dim.cardPadding),
    ) { content() }
}

@Composable
private fun Pill(text: String, selected: Boolean = false, onClick: () -> Unit) {
    val p = palette
    Box(
        Modifier.heightIn(min = 40.dp)
            .clip(RoundedCornerShape(20.dp))
            .background(if (selected) p.accentTint else p.secondary)
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(text, style = MaterialTheme.typography.labelMedium, color = if (selected) p.accentTintText else p.textSecondary)
    }
}

@Composable
private fun Button(text: String, modifier: Modifier = Modifier, primary: Boolean, color: Color? = null, onClick: () -> Unit) {
    val p = palette
    val bg = color ?: if (primary) p.accent else p.secondary
    Box(
        modifier.heightIn(min = Dim.touch)
            .clip(RoundedCornerShape(Dim.radiusControl))
            .background(bg)
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(text, style = MaterialTheme.typography.labelLarge, color = if (primary || color != null) Color.White else p.text)
    }
}

@Composable
private fun LinksCard(state: UiState, vm: MainViewModel) {
    val p = palette
    val text = state.input
    val clipboard = LocalClipboardManager.current
    Card {
        Text("Ссылки", style = MaterialTheme.typography.titleMedium, color = p.text)
        Spacer(Modifier.height(4.dp))
        Text("По одной в строке или списком: YouTube, Instagram, TikTok, X, Pinterest, Reddit, SoundCloud",
            style = MaterialTheme.typography.bodySmall, color = p.textMuted)
        Spacer(Modifier.height(10.dp))
        Box(
            Modifier.fillMaxWidth().heightIn(min = 96.dp, max = 180.dp)
                .clip(RoundedCornerShape(Dim.radiusControl)).background(p.inner)
                .border(BorderStroke(1.dp, p.innerBorder), RoundedCornerShape(Dim.radiusControl))
                .padding(12.dp),
        ) {
            if (text.isEmpty()) Text("https://…", style = MaterialTheme.typography.bodyLarge, color = p.textMuted)
            BasicTextField(
                value = text, onValueChange = vm::setInput,
                textStyle = MaterialTheme.typography.bodyLarge.copy(color = p.text),
                cursorBrush = SolidColor(p.accent),
                modifier = Modifier.fillMaxWidth().heightIn(min = 72.dp),
            )
        }
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Button("Вставить", Modifier.weight(1f), primary = false) {
                clipboard.getText()?.text?.takeIf { it.isNotBlank() }?.let { vm.pasteInto(it) }
            }
            Button("В очередь", Modifier.weight(1f), primary = true) {
                vm.queueInput()
            }
        }
    }
}

@Composable
private fun ModeTabs(state: UiState, vm: MainViewModel) {
    val p = palette
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(Dim.radiusControl)).background(p.secondary).padding(4.dp),
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        listOf("Ссылки" to false, "Треки по списку" to true).forEach { (title, tracks) ->
            val selected = state.tracksMode == tracks
            Box(
                Modifier.weight(1f).heightIn(min = 44.dp)
                    .clip(RoundedCornerShape(Dim.radiusControl - 2.dp))
                    .background(if (selected) p.card else Color.Transparent)
                    .clickable { vm.setTracksMode(tracks) },
                contentAlignment = Alignment.Center,
            ) {
                Text(title, style = MaterialTheme.typography.labelLarge, color = if (selected) p.accent else p.textSecondary)
            }
        }
    }
}

/** Сколько треков в списке: непустые строки без комментариев (#), без повторов — как в ядре. */
private fun countTracks(text: String): Int = text.lines()
    .map { it.trim().trimStart('-', '*', '•', ' ').replace(Regex("""^\d+\s*[.)]\s*"""), "").trim() }
    .filter { it.isNotEmpty() && !it.startsWith("#") }
    .map { it.lowercase() }.toSet().size

@Composable
private fun TracksCard(state: UiState, vm: MainViewModel) {
    val p = palette
    val clipboard = LocalClipboardManager.current
    val text = state.tracksInput
    val count = countTracks(text)
    Card {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Список треков", style = MaterialTheme.typography.titleMedium, color = p.text, modifier = Modifier.weight(1f))
            Pill("Треков: $count", selected = count > 0, onClick = {})
        }
        Spacer(Modifier.height(4.dp))
        Text("По одному в строке: «Исполнитель — Название». Каждый трек ищется на YouTube и сохраняется в MP3 с тегами. Не найденные попадут в _not_found.txt",
            style = MaterialTheme.typography.bodySmall, color = p.textMuted)
        Spacer(Modifier.height(10.dp))
        Box(
            Modifier.fillMaxWidth().heightIn(min = 160.dp, max = 280.dp)
                .clip(RoundedCornerShape(Dim.radiusControl)).background(p.inner)
                .border(BorderStroke(1.dp, p.innerBorder), RoundedCornerShape(Dim.radiusControl))
                .padding(12.dp),
        ) {
            if (text.isEmpty()) Text("Queen — Bohemian Rhapsody", style = MaterialTheme.typography.bodyLarge, color = p.textMuted)
            BasicTextField(
                value = text, onValueChange = vm::setTracksInput,
                textStyle = MaterialTheme.typography.bodyLarge.copy(color = p.text),
                cursorBrush = SolidColor(p.accent),
                modifier = Modifier.fillMaxWidth().heightIn(min = 136.dp),
            )
        }
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Button("Вставить", Modifier.weight(1f), primary = false) {
                clipboard.getText()?.text?.takeIf { it.isNotBlank() }?.let { vm.pasteTracks(it) }
            }
            Button("Очистить", Modifier.weight(1f), primary = false) { vm.clearTracks() }
        }
        Spacer(Modifier.height(10.dp))
        Button("В очередь", Modifier.fillMaxWidth(), primary = true) { vm.queueTracks() }
    }
}

@Composable
private fun QualityCard(state: UiState, vm: MainViewModel) {
    val p = palette
    Card {
        Text("Качество", style = MaterialTheme.typography.titleMedium, color = p.text)
        Spacer(Modifier.height(10.dp))
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            state.qualities.forEach { q ->
                Pill(q, selected = q == state.quality) { if (!state.running) vm.setQuality(q) }
            }
        }
    }
}

@Composable
private fun VkCard(state: UiState, vm: MainViewModel) {
    val p = palette
    val context = androidx.compose.ui.platform.LocalContext.current
    val clipboard = LocalClipboardManager.current
    Card {
        Text("ВКонтакте · фото", style = MaterialTheme.typography.titleMedium, color = p.text)
        Spacer(Modifier.height(4.dp))
        if (state.vkLoggedIn) {
            Text(
                if (state.vkName.isNotEmpty()) "Вы вошли как ${state.vkName}. Ссылки на альбомы vk.com/album… скачиваются в максимальном размере."
                else "Вход выполнен. Ссылки на альбомы vk.com/album… скачиваются в максимальном размере.",
                style = MaterialTheme.typography.bodySmall, color = p.green,
            )
            Spacer(Modifier.height(10.dp))
            Button("Выйти", Modifier.fillMaxWidth(), primary = false) { vm.vkLogout() }
        } else {
            Text(
                if (state.vkAwaiting) "Войдите в VK в браузере, затем скопируйте адрес страницы (blank.html#access_token=…) и вернитесь сюда: токен подхватится сам."
                else "Для альбомов VK нужен вход. Пароль приложению не передаётся: VK выдаёт временный токен только для фото.",
                style = MaterialTheme.typography.bodySmall, color = p.textMuted,
            )
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Button("Войти", Modifier.weight(1f), primary = true) {
                    vm.setVkAwaiting(true)
                    if (state.vkAuthUrl.isNotEmpty()) {
                        context.startActivity(
                            android.content.Intent(android.content.Intent.ACTION_VIEW, android.net.Uri.parse(state.vkAuthUrl))
                                .addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK),
                        )
                    }
                }
                Button("Вставить адрес", Modifier.weight(1f), primary = false) {
                    clipboard.getText()?.text?.takeIf { it.isNotBlank() }?.let { vm.vkLogin(it) }
                }
            }
        }
    }
}

@Composable
private fun QueueHeader(state: UiState, vm: MainViewModel) {
    val p = palette
    Row(Modifier.fillMaxWidth().padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Text("Очередь · ${state.items.size}", style = MaterialTheme.typography.titleMedium,
            color = p.text, modifier = Modifier.weight(1f))
        if (state.items.any { it.status == ItemStatus.DONE } && !state.running) {
            Pill("Очистить готовые", onClick = vm::clearFinished)
        }
    }
}

@Composable
private fun EmptyQueue(ready: Boolean) {
    val p = palette
    Box(Modifier.fillMaxWidth().padding(vertical = 32.dp), contentAlignment = Alignment.Center) {
        Text(
            if (ready) "Очередь пуста. Вставьте ссылки выше или нажмите «Поделиться» в другом приложении и выберите MediaHarvester."
            else "Запуск движка…",
            style = MaterialTheme.typography.bodyMedium, color = p.textMuted,
        )
    }
}

@Composable
private fun QueueRow(item: QueueEntry, state: UiState, vm: MainViewModel) {
    val p = palette
    Card {
        Row(verticalAlignment = Alignment.Top) {
            Column(Modifier.weight(1f)) {
                Text(item.label, style = MaterialTheme.typography.labelLarge, color = p.text, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(item.url, style = MaterialTheme.typography.bodySmall, color = p.textMuted, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            if (!state.running) {
                IconButton(onClick = { vm.remove(item.id) }, modifier = Modifier.size(Dim.touch).padding(0.dp)) {
                    Icon(Icons.Default.Close, contentDescription = "Убрать", tint = p.textMuted)
                }
            }
        }
        Spacer(Modifier.height(8.dp))
        val saved = state.saved[item.id]
        val (line, color) = when (item.status) {
            ItemStatus.PENDING -> "В очереди" to p.textMuted
            ItemStatus.WORKING -> item.text.ifBlank { "Подготовка…" } to p.accentTintText
            ItemStatus.DONE -> (if (saved != null) "Готово · сохранено файлов: $saved (Загрузки/MediaHarvester)" else "Готово · сохраняю…") to p.green
            ItemStatus.ERROR -> item.message.ifBlank { "Ошибка" } to p.danger
            ItemStatus.CANCELLED -> "Отменено" to p.amber
        }
        Text(line, style = MaterialTheme.typography.bodyMedium, color = color)
        if (item.status == ItemStatus.ERROR && item.hint.isNotBlank()) {
            Text(item.hint, style = MaterialTheme.typography.bodySmall, color = p.textSecondary, modifier = Modifier.padding(top = 4.dp))
        }
        if (item.status == ItemStatus.WORKING) {
            Spacer(Modifier.height(8.dp))
            val progress = item.progress
            if (progress != null) {
                LinearProgressIndicator(progress = { progress.coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth().height(6.dp).clip(RoundedCornerShape(3.dp)), color = p.accent, trackColor = p.secondary)
            } else {
                LinearProgressIndicator(modifier = Modifier.fillMaxWidth().height(6.dp).clip(RoundedCornerShape(3.dp)), color = p.accent, trackColor = p.secondary)
            }
        }
    }
}

@Composable
private fun BottomAction(state: UiState, vm: MainViewModel) {
    val p = palette
    val pending = state.items.count { it.status == ItemStatus.PENDING || it.status == ItemStatus.ERROR || it.status == ItemStatus.CANCELLED }
    Column(
        Modifier.fillMaxWidth().background(p.card).border(BorderStroke(1.dp, p.cardBorder)).navigationBarsPadding().imePadding()
            .padding(horizontal = Dim.gutter, vertical = 10.dp),
    ) {
        val label = when {
            state.cancelling -> "Останавливаю…"
            state.running -> "Остановить"
            pending > 0 -> "Скачать ($pending)"
            else -> "Скачать"
        }
        Button(label, Modifier.fillMaxWidth().height(52.dp), primary = true, color = if (state.running) p.danger else null) {
            if (!state.cancelling) vm.toggleDownload()
        }
    }
}
