package app.myvitals.ui.meals

import android.content.Context
import android.net.Uri
import androidx.core.content.FileProvider
import java.io.File

/**
 * A place for the camera app to write a photo, and a URI it may write to.
 *
 * Needed because the two photo screens offered a camera they never opened.
 * Both used `ActivityResultContracts.GetContent()`, which is a document
 * picker — the launcher in `PhotoPantry` was even named `camera` — so the
 * button labelled "Choose or take a photo" could only ever do the first
 * half of what it said.
 *
 * The capture goes to the app's cache rather than the gallery, and is
 * deleted as soon as it has been read. That matches the rule the photo
 * features already follow: the image is forwarded once and discarded,
 * with nothing stored here. A camera app cannot write into our cache
 * directly, so the file is handed over as a `content://` URI through the
 * FileProvider the APK updater already declares.
 *
 * No CAMERA permission is declared or needed: launching the system
 * capture intent requires one only if the manifest asks for it, and
 * asking would add a runtime prompt for no benefit.
 */
internal object CameraCapture {

    private const val AUTHORITY_SUFFIX = ".fileprovider"

    /** A fresh file plus the URI to hand the camera app. */
    fun newTarget(context: Context): Pair<File, Uri> {
        val dir = File(context.cacheDir, "captures").apply { mkdirs() }
        // Named by nanoTime rather than a counter so two captures in the
        // same session cannot collide, and swept below regardless.
        val file = File(dir, "capture-${System.nanoTime()}.jpg")
        val uri = FileProvider.getUriForFile(
            context, context.packageName + AUTHORITY_SUFFIX, file,
        )
        return file to uri
    }

    /**
     * Delete a capture once it has been read.
     *
     * Called on both paths — success and failure — because a photo left
     * in the cache is the one thing these screens promise not to do.
     * Failure to delete is ignored: it is a cache, the OS clears it, and
     * an error here would replace a working feature with a scary message.
     */
    fun discard(file: File?) {
        runCatching { file?.takeIf { it.exists() }?.delete() }
    }

    /** Sweep anything an earlier crash or kill left behind. */
    fun sweep(context: Context) {
        runCatching {
            File(context.cacheDir, "captures").listFiles()?.forEach { it.delete() }
        }
    }
}
