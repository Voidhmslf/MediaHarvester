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
import kotlinx.coroutines.launch

/**
 * Держит процесс живым, пока идёт очередь, переносит готовые файлы в «Загрузки» и показывает прогресс.
 * Сам Python работает в потоке внутри процесса; сервис нужен, чтобы Android не убил приложение в фоне.
 */
class DownloadService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var job: Job? = null
    private var wakeLock: PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        ensureChannel()
        startForeground(NOTIFICATION_ID, ongoing("Подготовка…", 0, 0), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        if (job == null) {
            wakeLock = (getSystemService(POWER_SERVICE) as PowerManager)
                .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "MediaHarvester:download")
                .apply { acquire(2 * 60 * 60 * 1000L) }
            job = scope.launch { watchQueue() }
        }
        return START_NOT_STICKY
    }

    private suspend fun watchQueue() {
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        var last: QueueSnapshot
        while (true) {
            last = Bridge.snapshot(this)
            Exporter.exportDone(this, last.items)
            History.record(this, last.items, Exporter.saved.value, Exporter.uris.value)
            val total = last.items.count { it.status != ItemStatus.CANCELLED }
            val finished = last.items.count { it.status == ItemStatus.DONE || it.status == ItemStatus.ERROR }
            val current = last.items.firstOrNull { it.status == ItemStatus.WORKING }
            val title = current?.let { "${it.label}: ${it.text}".trim(' ', ':') } ?: "Скачивание…"
            nm.notify(NOTIFICATION_ID, ongoing(title, finished, total))
            if (!last.running) break
            delay(700)
        }
        val done = last.items.count { it.status == ItemStatus.DONE }
        val failed = last.items.count { it.status == ItemStatus.ERROR }
        val summary = if (failed > 0) "Готово: $done, с ошибкой: $failed" else "Готово: $done. Файлы в Загрузки/${Settings.folderName(this)}"
        stopForeground(STOP_FOREGROUND_REMOVE)
        nm.notify(NOTIFICATION_ID + 1, finishedNotification(summary))
        stopSelf()
    }

    private fun contentIntent(): PendingIntent = PendingIntent.getActivity(
        this, 0, Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
    )

    private fun ongoing(text: String, done: Int, total: Int): Notification =
        NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_mediaharvester)
            .setContentTitle(if (total > 0) "MediaHarvester · $done из $total" else "MediaHarvester")
            .setContentText(text)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setProgress(total, done, total == 0)
            .setContentIntent(contentIntent())
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

        fun start(context: Context) {
            context.startForegroundService(Intent(context, DownloadService::class.java))
        }
    }
}
