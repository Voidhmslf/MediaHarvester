package app.mediaharvester

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

/**
 * Держит процесс живым, пока идёт очередь, переносит готовые файлы в «Загрузки» и показывает прогресс.
 * Сам Python работает в потоках внутри процесса; сервис нужен, чтобы Android не убил приложение в фоне.
 * В режиме «Только по Wi-Fi» ждёт сеть без лимита, а если она пропала посреди загрузки — приостанавливает очередь
 * и продолжает, когда Wi-Fi вернётся (yt-dlp докачивает начатые файлы).
 */
class DownloadService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var job: Job? = null
    private var wakeLock: PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            requestStop(this)
            return START_NOT_STICKY
        }
        ensureChannel()
        startForeground(NOTIFICATION_ID, ongoing("Подготовка…", 0, 0, withStop = true), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        if (job == null) {
            stopRequested = false
            val quality = intent?.getStringExtra(EXTRA_QUALITY).orEmpty()
            wakeLock = (getSystemService(POWER_SERVICE) as PowerManager)
                .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "MediaHarvester:download")
                .apply { acquire(2 * 60 * 60 * 1000L) }
            job = scope.launch { run(quality) }
        }
        return START_NOT_STICKY
    }

    private suspend fun run(quality: String) {
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        var last = QueueSnapshot(false, false, emptyList())
        try {
            do {
                var pausedForNetwork = false
                waitForWifi(nm)
                if (stopRequested) break
                if (!Bridge.snapshot(this).running && !Bridge.start(this, quality, Settings.parallel(this))) break
                while (true) {
                    last = Bridge.snapshot(this)
                    Exporter.exportDone(this, last.items)
                    History.record(this, last.items, Exporter.saved.value, Exporter.uris.value)
                    val total = last.items.count { it.status != ItemStatus.CANCELLED }
                    val finished = last.items.count { it.status == ItemStatus.DONE || it.status == ItemStatus.ERROR }
                    val working = last.items.filter { it.status == ItemStatus.WORKING }
                    val title = when {
                        working.size > 1 -> "Качаю одновременно: ${working.size}"
                        working.size == 1 -> "${working[0].title.ifBlank { working[0].label }}: ${working[0].text}".trim(' ', ':')
                        else -> "Скачивание…"
                    }
                    nm.notify(NOTIFICATION_ID, ongoing(title, finished, total, withStop = true))
                    if (!stopRequested && last.running && Settings.wifiOnly(this) && !Settings.onUnmeteredNetwork(this)) {
                        pausedForNetwork = true
                        Bridge.cancel(this) // очередь остановится, начатое докачается после возвращения Wi-Fi
                    }
                    if (!last.running) break
                    delay(700)
                }
            } while (pausedForNetwork && !stopRequested)
        } finally {
            waiting.value = false
        }
        val done = last.items.count { it.status == ItemStatus.DONE }
        val failed = last.items.count { it.status == ItemStatus.ERROR }
        val summary = when {
            stopRequested -> "Остановлено. Готово: $done"
            failed > 0 -> "Готово: $done, с ошибкой: $failed"
            else -> "Готово: $done. Файлы в Загрузки/${Settings.folderName(this)}"
        }
        stopForeground(STOP_FOREGROUND_REMOVE)
        nm.notify(NOTIFICATION_ID + 1, finishedNotification(summary))
        job = null
        stopSelf()
    }

    /** Пока включён «Только по Wi-Fi» и сети без лимита нет — ждём; «Остановить» прерывает ожидание. */
    private suspend fun waitForWifi(nm: NotificationManager) {
        while (!stopRequested && Settings.wifiOnly(this) && !Settings.onUnmeteredNetwork(this)) {
            waiting.value = true
            nm.notify(NOTIFICATION_ID, ongoing("Жду Wi-Fi…", 0, 0, withStop = true))
            delay(3000)
        }
        waiting.value = false
    }

    private fun contentIntent(): PendingIntent = PendingIntent.getActivity(
        this, 0, Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
    )

    private fun stopIntent(): PendingIntent = PendingIntent.getService(
        this, 1, Intent(this, DownloadService::class.java).setAction(ACTION_STOP),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
    )

    private fun ongoing(text: String, done: Int, total: Int, withStop: Boolean): Notification =
        NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_mediaharvester)
            .setContentTitle(if (total > 0) "MediaHarvester · $done из $total" else "MediaHarvester")
            .setContentText(text)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setProgress(total, done, total == 0)
            .setContentIntent(contentIntent())
            .apply { if (withStop) addAction(0, "Остановить", stopIntent()) }
            .build()

    private fun finishedNotification(text: String): Notification =
        NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_mediaharvester)
            .setContentTitle("MediaHarvester")
            .setContentText(text)
            .setAutoCancel(true)
            .setContentIntent(contentIntent())
            .build()

    private fun ensureChannel() {
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        if (nm.getNotificationChannel(CHANNEL) == null) {
            nm.createNotificationChannel(NotificationChannel(CHANNEL, "Загрузки", NotificationManager.IMPORTANCE_LOW))
        }
    }

    override fun onDestroy() {
        wakeLock?.takeIf { it.isHeld }?.release()
        scope.cancel()
        super.onDestroy()
    }

    companion object {
        private const val CHANNEL = "downloads"
        private const val NOTIFICATION_ID = 1
        private const val ACTION_STOP = "app.mediaharvester.STOP"
        private const val EXTRA_QUALITY = "quality"

        @Volatile
        private var stopRequested = false

        private val waiting = MutableStateFlow(false)

        /** Служба ждёт Wi-Fi: очередь ещё не запущена, но пользователь уже нажал «Скачать». */
        val waitingForWifi: StateFlow<Boolean> = waiting

        fun start(context: Context, quality: String) {
            context.startForegroundService(
                Intent(context, DownloadService::class.java).putExtra(EXTRA_QUALITY, quality),
            )
        }

        /** Остановка из приложения или из уведомления: прерывает ожидание Wi-Fi и текущие загрузки. */
        fun requestStop(context: Context) {
            stopRequested = true
            waiting.value = false
            Thread { Bridge.cancel(context) }.start()
        }
    }
}
