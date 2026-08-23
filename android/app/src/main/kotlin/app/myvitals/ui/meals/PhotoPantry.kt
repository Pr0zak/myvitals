package app.myvitals.ui.meals

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PhotoCamera
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import android.util.Base64
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.IdentifiedFood
import app.myvitals.sync.IdentifyIn
import app.myvitals.sync.QuickAddIn
import app.myvitals.ui.neon.NeonMV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream

/**
 * Add to the pantry from a photograph — the phone mirror of the web's
 * PhotoPantry.
 *
 * Three rules, each easy to lose to a convenience tweak:
 *
 * 1. NOTHING IS ADDED AUTOMATICALLY. Vision misidentifies confidently,
 *    and a pantry that grows items the user did not put there stops
 *    being trustworthy — which makes the shopping list built on it worse
 *    than useless. Everything arrives unticked except high-confidence
 *    matches, and even "select likely" leaves guesses alone.
 * 2. The photo is downscaled HERE. A 12 MP phone photo identifies no
 *    better than a 1400 px one, costs more to send, and would trip the
 *    server's size limit. Re-encoding through a Bitmap also drops EXIF,
 *    including GPS, which is the right default for an image leaving the
 *    device.
 * 3. The user is told the photo goes to their AI provider BEFORE they
 *    open the camera. This is the only place in the app that sends an
 *    image anywhere.
 */

/** Longest edge after downscaling. Enough to read a label. */
private const val MAX_EDGE = 1400
private const val JPEG_QUALITY = 82

@Composable
fun PhotoPantry(settings: SettingsRepository, onAdded: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    var busy by remember { mutableStateOf(false) }
    var adding by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var items by remember { mutableStateOf<List<IdentifiedFood>>(emptyList()) }
    var notes by remember { mutableStateOf<List<String>>(emptyList()) }
    var picked by remember { mutableStateOf<Set<Int>>(emptySet()) }

    fun identify(uri: Uri?) {
        if (uri == null) return
        scope.launch {
            busy = true
            error = null
            items = emptyList()
            notes = emptyList()
            picked = emptySet()
            try {
                val b64 = withContext(Dispatchers.IO) { downscaleUriToBase64(context, uri) }
                if (b64 == null) {
                    error = "Could not read that image."
                    return@launch
                }
                val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                val res = withContext(Dispatchers.IO) {
                    api.mealsIdentify(IdentifyIn(imageBase64 = b64))
                }
                items = res.items
                notes = res.notes
                // Pre-tick only confident, matched items. A bulk accept
                // must not sweep in guesses.
                picked = res.items.withIndex()
                    .filter { (_, it) -> it.confidence == "high" && !it.unmatched }
                    .map { it.index }
                    .toSet()
            } catch (e: Exception) {
                error = e.message ?: "could not read that photo"
            } finally {
                busy = false
            }
        }
    }

    val camera = rememberLauncherForActivityResult(
        ActivityResultContracts.GetContent(),
    ) { identify(it) }

    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
            .background(NeonMV.Card).padding(12.dp),
    ) {
        Text(
            "Add from a photo", color = NeonMV.Ink, fontSize = 13.sp,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            "Photograph a shelf, a fridge or a receipt. The photo is sent to " +
                "your AI provider to be read, then discarded — it is never " +
                "stored here. Nothing is added until you confirm it.",
            color = NeonMV.Muted, fontSize = 10.sp, lineHeight = 14.sp,
            modifier = Modifier.padding(top = 4.dp, bottom = 8.dp),
        )

        Button(
            enabled = !busy,
            onClick = { camera.launch("image/*") },
            modifier = Modifier.fillMaxWidth(),
        ) {
            Icon(Icons.Filled.PhotoCamera, contentDescription = null)
            Text(if (busy) "  Reading…" else "  Choose or take a photo")
        }

        error?.let {
            Text(
                it, color = NeonMV.Bad, fontSize = 11.sp,
                modifier = Modifier.padding(top = 6.dp),
            )
        }

        if (items.isNotEmpty()) {
            Row(
                Modifier.fillMaxWidth().padding(top = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    "${items.size} found", color = NeonMV.Muted, fontSize = 11.sp,
                    modifier = Modifier.weight(1f),
                )
                Text(
                    "select likely", color = NeonMV.Cyan, fontSize = 11.sp,
                    modifier = Modifier.clickable {
                        // Even "select likely" leaves low-confidence items
                        // alone — that is the point of reporting confidence.
                        picked = items.withIndex()
                            .filter { (_, it) -> it.confidence != "low" && !it.unmatched }
                            .map { it.index }.toSet()
                    },
                )
                Text(
                    "  none", color = NeonMV.Muted, fontSize = 11.sp,
                    modifier = Modifier.clickable { picked = emptySet() },
                )
            }

            items.forEachIndexed { i, it ->
                Row(
                    Modifier.fillMaxWidth().padding(vertical = 2.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Checkbox(
                        checked = i in picked,
                        enabled = !it.unmatched,
                        onCheckedChange = { on ->
                            picked = if (on) picked + i else picked - i
                        },
                    )
                    Column(Modifier.weight(1f)) {
                        Text(
                            it.concept ?: it.name,
                            color = if (it.unmatched) NeonMV.Muted else NeonMV.Ink,
                            fontSize = 12.sp,
                        )
                        val sub = it.detail
                            ?: if (it.unmatched) "not in the catalog" else null
                        sub?.let { s ->
                            Text(s, color = NeonMV.Muted, fontSize = 9.sp)
                        }
                    }
                    Text(
                        it.confidence,
                        color = when (it.confidence) {
                            "high" -> NeonMV.Lime
                            "medium" -> NeonMV.Amber
                            else -> NeonMV.Muted
                        },
                        fontSize = 9.sp,
                    )
                }
            }

            notes.forEach {
                Text(
                    it, color = NeonMV.Amber, fontSize = 10.sp, lineHeight = 14.sp,
                    modifier = Modifier.padding(top = 4.dp),
                )
            }

            val ids = items.filterIndexed { i, _ -> i in picked }
                .mapNotNull { it.foodId }
            Button(
                enabled = !adding && ids.isNotEmpty(),
                onClick = {
                    scope.launch {
                        adding = true
                        try {
                            val api = BackendClient.create(
                                settings.backendUrl, settings.bearerToken,
                            )
                            withContext(Dispatchers.IO) {
                                api.mealsQuickAddPantry(QuickAddIn(ids))
                            }
                            items = emptyList()
                            notes = emptyList()
                            picked = emptySet()
                            onAdded()
                        } catch (e: Exception) {
                            error = e.message ?: "could not add"
                        } finally {
                            adding = false
                        }
                    }
                },
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            ) {
                Text(if (adding) "Adding…" else "Add ${ids.size} to pantry")
            }
        } else if (notes.isNotEmpty()) {
            Text(
                notes.joinToString(" "), color = NeonMV.Amber, fontSize = 10.sp,
                lineHeight = 14.sp, modifier = Modifier.padding(top = 6.dp),
            )
        }
    }
}

/**
 * Read, downscale and JPEG-encode an image to base64.
 *
 * Two-pass decode: `inJustDecodeBounds` reads the dimensions without
 * allocating the pixels, so a 50 MP image never lands in memory whole —
 * decoding one first and scaling after is a reliable OOM on a phone.
 */
internal fun downscaleUriToBase64(context: Context, uri: Uri): String? = runCatching {
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    context.contentResolver.openInputStream(uri)?.use {
        BitmapFactory.decodeStream(it, null, bounds)
    }
    val longest = maxOf(bounds.outWidth, bounds.outHeight)
    if (longest <= 0) return@runCatching null

    var sample = 1
    while (longest / sample > MAX_EDGE * 2) sample *= 2

    val opts = BitmapFactory.Options().apply { inSampleSize = sample }
    val decoded = context.contentResolver.openInputStream(uri)?.use {
        BitmapFactory.decodeStream(it, null, opts)
    } ?: return@runCatching null

    val scale = MAX_EDGE.toFloat() / maxOf(decoded.width, decoded.height)
    val bmp = if (scale < 1f) {
        Bitmap.createBitmap(
            decoded, 0, 0, decoded.width, decoded.height,
            Matrix().apply { postScale(scale, scale) }, true,
        )
    } else {
        decoded
    }

    val out = ByteArrayOutputStream()
    bmp.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, out)
    if (bmp !== decoded) bmp.recycle()
    decoded.recycle()
    Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
}.getOrNull()
