package app.mediaharvester

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.Toast

/**
 * Принимает ссылку из «Поделиться» и сразу кладёт её в очередь, не открывая экран приложения:
 * пользователь остаётся в браузере или соцсети. Режим (только в очередь / ещё и скачать / открыть приложение)
 * выбирается в настройках.
 */
class ShareActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val text = intent?.takeIf { it.action == Intent.ACTION_SEND }?.getStringExtra(Intent.EXTRA_TEXT).orEmpty()
        val app = applicationContext
        if (text.isBlank()) {
            finish()
            return
        }
        val mode = Settings.shareMode(app)
        if (mode == "open") {
            startActivity(Intent(this, MainActivity::class.java).setAction(Intent.ACTION_SEND)
                .putExtra(Intent.EXTRA_TEXT, text).setType("text/plain").addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP))
        }
        // Python стартует долго: работаем в потоке, активность закрывается, когда всё готово
        Thread {
            val added = try { Bridge.addLinks(app, text) } catch (e: Exception) { -1 }
            val message = when {
                added < 0 -> "Не удалось добавить ссылку"
                added == 0 -> "Эта ссылка уже в очереди или не распознана"
                mode == "download" -> "Добавлено и скачиваю: $added"
                else -> "Добавлено в очередь: $added"
            }
            if (added > 0 && mode == "download") {
                DownloadService.start(app, app.getSharedPreferences("settings", MODE_PRIVATE).getString("quality", "").orEmpty())
            }
            Handler(Looper.getMainLooper()).post {
                if (mode != "open") Toast.makeText(app, message, Toast.LENGTH_SHORT).show()
                finish()
            }
        }.start()
    }
}
