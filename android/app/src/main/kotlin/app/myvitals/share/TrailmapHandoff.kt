package app.myvitals.share

import android.app.PendingIntent
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import app.myvitals.BuildConfig
import app.myvitals.MainActivity
import timber.log.Timber

/**
 * "Send to trailmap" — hands the saved server address and access key to the
 * trailmap app on this phone, so it can show which trails were ridden, the
 * pace on them and trail conditions from this server.
 *
 * The contract is shared with trailmap and must match it exactly: an
 * explicit Intent ([ACTION], [setPackage][Intent.setPackage] [PACKAGE],
 * never a chooser or a broadcast) carrying [EXTRA_URL], [EXTRA_TOKEN] and
 * [EXTRA_SENDER]. trailmap only pre-fills its myvitals screen; the user
 * confirms there ("Connect", or "Use this" when it is already connected).
 *
 * [EXTRA_SENDER] is how trailmap knows the offer came from this app: an
 * immutable PendingIntent this app creates for itself ([senderProof]).
 * trailmap never fires it; it reads [PendingIntent.getCreatorPackage],
 * which the system fills in and no other app can forge, then checks this
 * app's signing certificate. An offer without it is ignored.
 *
 * The key can read AND write this server, so it only leaves when the
 * installed com.trailmap is signed with trailmap's release certificate
 * ([RELEASE_CERT_SHA256], a public fingerprint). A debug build of this app
 * accepts any signature so a locally built trailmap can be tested; a
 * release build always enforces the pin.
 *
 * The key is never logged. Nothing here keeps it in a type that could be
 * toString()'d, and a failed launch is logged by exception class only —
 * the exception's message describes the Intent.
 */
object TrailmapHandoff {
    const val PACKAGE = "com.trailmap"
    const val ACTION = "com.trailmap.action.CONNECT_MYVITALS"
    const val EXTRA_URL = "com.trailmap.extra.MYVITALS_URL"
    const val EXTRA_TOKEN = "com.trailmap.extra.MYVITALS_TOKEN"
    const val EXTRA_SENDER = "com.trailmap.extra.MYVITALS_SENDER"

    /**
     * The action on [senderProof]'s own Intent. Not part of the contract:
     * it only keeps that PendingIntent a record of its own. The widgets and
     * the workout reminder also point PendingIntents at MainActivity with
     * request code 0, and a matching Intent would hand back one of theirs.
     */
    private const val SENDER_PROOF_ACTION = "app.myvitals.action.TRAILMAP_SENDER_PROOF"

    /** SHA-256 of trailmap's release signing certificate. */
    const val RELEASE_CERT_SHA256 = "0aeaa84a18d61fb2b7ae60b7b2d74e40a252c4ab7fbe775162cac21f7bb6b0d4"

    private val releaseCert: ByteArray = decodeSha256Pin(RELEASE_CERT_SHA256)

    /** What a send did, in words for the screen. Never carries the key. */
    sealed class Result(val message: String, val ok: Boolean) {
        data object Sent : Result("Sent. Check the details in trailmap and confirm there.", true)
        data object NotConfigured : Result("Set up your server first.", false)
        data object NotInstalled : Result("trailmap isn't installed on this phone.", false)
        data object Untrusted : Result(
            "The trailmap on this phone isn't the official build, so your key wasn't sent.", false,
        )
        data object CantReceive : Result(
            "This version of trailmap can't receive a connection. Update it and try again.", false,
        )
        data object Blocked : Result("Android wouldn't open trailmap, so nothing was sent.", false)
    }

    /**
     * 64 hex characters → the 32 bytes [PackageManager.hasSigningCertificate]
     * compares. Strict: a malformed pin must fail loudly, not match nothing.
     */
    fun decodeSha256Pin(hex: String): ByteArray {
        require(hex.length == 64) { "SHA-256 pin must be 64 hex characters, was ${hex.length}" }
        return ByteArray(32) { i ->
            val hi = Character.digit(hex[2 * i], 16)
            val lo = Character.digit(hex[2 * i + 1], 16)
            require(hi >= 0 && lo >= 0) { "SHA-256 pin has a non-hex character near position ${2 * i}" }
            ((hi shl 4) or lo).toByte()
        }
    }

    /**
     * The host alone, for the log line — never the whole address, which can
     * carry a user:password. "unknown host" when it won't parse.
     */
    fun hostOf(url: String): String {
        val u = url.trim()
        val withScheme = if ("://" in u) u else "https://$u"
        return runCatching { java.net.URI(withScheme).host }.getOrNull()
            ?.takeIf { it.isNotBlank() } ?: "unknown host"
    }

    /** Why the button is off, or null when it can send. */
    fun blockedReason(configured: Boolean, unsavedEdits: Boolean): String? = when {
        unsavedEdits -> "Save your server first"
        !configured -> "Set up your server first"
        else -> null
    }

    /**
     * What the card still shows after the screen comes back to the front for
     * the [resumes]th time since [result] was set. A refusal is dropped:
     * trailmap may have been updated or reinstalled meanwhile, and an old
     * "isn't the official build" under a live button would be wrong. "Sent"
     * survives the first return, which is coming back from trailmap and
     * exactly when it is read, and goes after that — days later it would
     * claim a send that isn't recent.
     */
    fun resultAfterResume(result: Result?, resumes: Int): Result? =
        result?.takeIf { it.ok && resumes <= 1 }

    fun isInstalled(pm: PackageManager): Boolean = try {
        pm.getPackageInfo(PACKAGE, 0)
        true
    } catch (e: PackageManager.NameNotFoundException) {
        false
    }

    /**
     * Signed with trailmap's release certificate. Debug builds accept any
     * signature (but trailmap must still be installed).
     */
    fun isTrusted(pm: PackageManager): Boolean =
        if (BuildConfig.DEBUG) isInstalled(pm)
        else pm.hasSigningCertificate(PACKAGE, releaseCert, PackageManager.CERT_INPUT_SHA256)

    /**
     * The proof for [EXTRA_SENDER]: an immutable PendingIntent this app
     * creates, pointing at its own MainActivity. It is never fired — if it
     * ever were, it would only open myvitals, and FLAG_IMMUTABLE stops the
     * holder filling anything into it.
     */
    fun senderProof(context: Context): PendingIntent = PendingIntent.getActivity(
        context, 0,
        Intent(context, MainActivity::class.java).setAction(SENDER_PROOF_ACTION),
        PendingIntent.FLAG_IMMUTABLE,
    )

    /** The offer itself: exactly the contract's extras, nothing else. */
    fun offerIntent(url: String, token: String, sender: PendingIntent): Intent = Intent(ACTION)
        .setPackage(PACKAGE)
        .putExtra(EXTRA_URL, url)
        .putExtra(EXTRA_TOKEN, token)
        .putExtra(EXTRA_SENDER, sender)
        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)

    /**
     * Open trailmap with [url] and [token]. Never throws.
     *
     * [Result.Sent] means trailmap was started, not that it accepted the
     * offer: trailmap drops an offer whose sender it can't verify, so a
     * locally built debug myvitals (not signed with the release key) sending
     * to a release trailmap reports Sent and trailmap shows nothing.
     */
    fun send(context: Context, url: String, token: String): Result {
        if (url.isBlank() || token.isBlank()) return Result.NotConfigured
        val pm = context.packageManager
        if (!isInstalled(pm)) return Result.NotInstalled
        if (!isTrusted(pm)) {
            Timber.w("trailmap handoff refused: not signed with trailmap's release certificate")
            return Result.Untrusted
        }
        return try {
            context.startActivity(offerIntent(url, token, senderProof(context)))
            Timber.i("sent connection to trailmap (%s)", hostOf(url))
            Result.Sent
        } catch (e: ActivityNotFoundException) {
            Timber.w("trailmap handoff failed: %s", e.javaClass.simpleName)
            Result.CantReceive
        } catch (e: SecurityException) {
            Timber.w("trailmap handoff failed: %s", e.javaClass.simpleName)
            Result.Blocked
        }
    }
}
