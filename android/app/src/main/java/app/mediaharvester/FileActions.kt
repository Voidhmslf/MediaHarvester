package app.mediaharvester

import android.app.DownloadManager
import android.content.ClipData
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.widget.Toast

/** Открыть и отправить уже сохранённые файлы (адреса content:// из MediaStore). */
object FileActions {
    fun open(context: Context, uriString: String) {
        val uri = Uri.parse(uriString)
        val mime = context.contentResolver.getType(uri) ?: "*/*"
        val intent = Intent(Intent.ACTION_VIEW)
            .setDataAndType(uri, mime)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        start(context, intent, "Нет приложения, которое откроет этот файл")
    }

    fun share(context: Context, uriStrings: List<String>) {
        val uris = uriStrings.map(Uri::parse)
        if (uris.isEmpty()) return
        val send = if (uris.size == 1) {
            Intent(Intent.ACTION_SEND).putExtra(Intent.EXTRA_STREAM, uris[0])
                .setType(context.contentResolver.getType(uris[0]) ?: "*/*")
        } else {
            Intent(Intent.ACTION_SEND_MULTIPLE).putParcelableArrayListExtra(Intent.EXTRA_STREAM, ArrayList(uris)).setType("*/*")
        }
        val clip = ClipData.newRawUri(null, uris[0]).also { c -> uris.drop(1).forEach { c.addItem(ClipData.Item(it)) } }
        send.clipData = clip
        send.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        start(context, Intent.createChooser(send, "Отправить").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), "Не удалось отправить файл")
    }

    /** Системное приложение «Загрузки» (конкретную папку Android открыть не позволяет). */
    fun openDownloads(context: Context) {
        start(context, Intent(DownloadManager.ACTION_VIEW_DOWNLOADS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), "Не удалось открыть «Загрузки»")
    }

    private fun start(context: Context, intent: Intent, failure: String) {
        try {
            context.startActivity(intent)
        } catch (e: Exception) {
            Toast.makeText(context, failure, Toast.LENGTH_SHORT).show()
        }
    }
}
