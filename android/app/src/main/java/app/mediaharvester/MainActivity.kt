package app.mediaharvester

import android.Manifest
import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.SystemBarStyle
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import app.mediaharvester.ui.MainScreen
import app.mediaharvester.ui.MediaHarvesterTheme

class MainActivity : ComponentActivity() {
    private val viewModel: MainViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        if (savedInstanceState == null) handleShare(intent)
        setContent {
            val state by viewModel.state.collectAsState()
            val askNotifications = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {}
            // Уведомление с прогрессом нужно, чтобы видеть загрузку в фоне
            LaunchedEffect(Unit) { askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS) }
            // Иконки статус-бара должны читаться на фоне выбранной в приложении темы, а не системной
            val dark = when (state.theme) { "light" -> false; "dark" -> true; else -> isSystemInDarkTheme() }
            LaunchedEffect(dark) {
                val style = if (dark) SystemBarStyle.dark(android.graphics.Color.TRANSPARENT)
                else SystemBarStyle.light(android.graphics.Color.TRANSPARENT, android.graphics.Color.TRANSPARENT)
                enableEdgeToEdge(statusBarStyle = style, navigationBarStyle = style)
            }
            MediaHarvesterTheme(state.theme) {
                MainScreen(state, viewModel)
            }
        }
    }

    /** После входа в браузере пользователь копирует адрес страницы: токен подхватывается из буфера при возврате. */
    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (!hasFocus) return
        // Читать буфер обмена Android разрешает только приложению, которое сейчас на экране
        val clipboard = getSystemService(CLIPBOARD_SERVICE) as android.content.ClipboardManager
        val text = clipboard.primaryClip?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.text?.toString().orEmpty()
        if (viewModel.state.value.vkAwaiting) {
            if ("access_token=" in text) {
                viewModel.vkLogin(text)
                clipboard.clearPrimaryClip() // токен не должен оставаться в буфере обмена
            }
        } else if (text.isNotEmpty() && "access_token=" !in text) {
            viewModel.offerClipboard(text)
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleShare(intent)
    }

    private fun handleShare(intent: Intent?) {
        if (intent?.action == Intent.ACTION_SEND && intent.type == "text/plain") {
            intent.getStringExtra(Intent.EXTRA_TEXT)?.let { viewModel.addLinks(it) }
        }
    }
}
