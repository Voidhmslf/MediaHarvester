package app.mediaharvester

import android.content.Context
import android.util.Log
import org.apache.commons.compress.archivers.zip.ZipArchiveEntry
import org.apache.commons.compress.archivers.zip.ZipFile
import java.io.File
import java.nio.file.Files

/** Папки установленного ffmpeg: binDir содержит ffmpeg и ffprobe, libDir — его библиотеки. */
class FfmpegPaths(val binDir: String, val libDir: String)

/**
 * ffmpeg поставляется внутри APK: исполняемый файл лежит среди нативных библиотек, а его зависимости — в
 * архиве libffmpeg.zip.so (с символическими ссылками), который распаковывается один раз для каждой версии.
 */
object Ffmpeg {
    private const val TAG = "Ffmpeg"
    private const val S_IFMT = 0xF000
    private const val S_IFLNK = 0xA000

    @Synchronized
    fun prepare(context: Context): FfmpegPaths? = try {
        val nativeDir = File(context.applicationInfo.nativeLibraryDir)
        val archive = File(nativeDir, "libffmpeg.zip.so")
        val shared = File(nativeDir, "libpython.zip.so")
        val binary = File(nativeDir, "libffmpeg.so")
        if (!archive.isFile || !binary.isFile || !shared.isFile) {
            null
        } else {
            val root = File(context.noBackupFilesDir, "ffmpeg")
            val marker = File(root, ".version")
            val version = "${archive.length()}-${shared.length()}"
            if (marker.takeIf { it.isFile }?.readText() != version) {
                root.deleteRecursively()
                root.mkdirs()
                unzip(archive, root)
                unzip(shared, File(root, "shared"))
                marker.writeText(version)
            }
            val bin = File(root, "bin").apply { mkdirs() }
            link(File(bin, "ffmpeg"), binary)
            link(File(bin, "ffprobe"), File(nativeDir, "libffprobe.so"))
            val libs = listOf(File(root, "usr/lib"), File(root, "shared/usr/lib"), nativeDir)
            FfmpegPaths(bin.absolutePath, libs.joinToString(File.pathSeparator) { it.absolutePath })
        }
    } catch (e: Exception) {
        Log.e(TAG, "ffmpeg недоступен", e)
        null
    }

    private fun link(link: File, target: File) {
        if (!target.exists()) return
        if (Files.isSymbolicLink(link.toPath())) {
            if (Files.readSymbolicLink(link.toPath()).toFile() == target) return
            link.delete()
        }
        Files.createSymbolicLink(link.toPath(), target.toPath())
    }

    private fun unzip(archive: File, dest: File) {
        ZipFile.builder().setFile(archive).get().use { zip ->
            for (entry in zip.entries) {
                val out = File(dest, entry.name)
                require(out.canonicalPath.startsWith(dest.canonicalPath)) { "Недопустимый путь в архиве: ${entry.name}" }
                when {
                    entry.isDirectory -> out.mkdirs()
                    entry.isSymlink() -> {
                        out.parentFile?.mkdirs()
                        val target = zip.getInputStream(entry).use { it.readBytes() }.toString(Charsets.UTF_8)
                        Files.createSymbolicLink(out.toPath(), File(target).toPath())
                    }
                    else -> {
                        out.parentFile?.mkdirs()
                        zip.getInputStream(entry).use { input -> out.outputStream().use { input.copyTo(it) } }
                        out.setExecutable(true)
                    }
                }
            }
        }
    }

    private fun ZipArchiveEntry.isSymlink() = (unixMode and S_IFMT) == S_IFLNK
}
