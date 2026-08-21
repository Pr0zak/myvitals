package app.myvitals.data

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import java.time.Instant

/**
 * Backend URL + last-sync time live in plain prefs (not secret).
 * Bearer token lives in EncryptedSharedPreferences (Android keystore-backed).
 */
class SettingsRepository(context: Context) {

    private val plain: SharedPreferences =
        context.getSharedPreferences(PLAIN_FILE, Context.MODE_PRIVATE)

    private val secure: SharedPreferences = run {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            context,
            SECURE_FILE,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    var backendUrl: String
        get() = plain.getString(KEY_BACKEND_URL, "") ?: ""
        set(value) = plain.edit().putString(KEY_BACKEND_URL, value.trimEnd('/')).apply()

    var bearerToken: String
        get() = secure.getString(KEY_TOKEN, "") ?: ""
        set(value) = secure.edit().putString(KEY_TOKEN, value).apply()

    var lastSyncEpochSeconds: Long
        get() = plain.getLong(KEY_LAST_SYNC, 0L)
        set(value) = plain.edit().putLong(KEY_LAST_SYNC, value).apply()

    /** Last time we did the once-a-day 7-day deep sweep. */
    var lastDeepSweepEpochSeconds: Long
        get() = plain.getLong(KEY_LAST_DEEP_SWEEP, 0L)
        set(value) = plain.edit().putLong(KEY_LAST_DEEP_SWEEP, value).apply()

    /** Last time the SyncWorker actually finished a successful upload (or no-op). */
    var lastSuccessEpochSeconds: Long
        get() = plain.getLong(KEY_LAST_SUCCESS, 0L)
        set(value) = plain.edit().putLong(KEY_LAST_SUCCESS, value).apply()

    /** Most recent doWork() saw a HC SecurityException — UI surfaces this. */
    var permissionsLost: Boolean
        get() = plain.getBoolean(KEY_PERMS_LOST, false)
        set(value) = plain.edit().putBoolean(KEY_PERMS_LOST, value).apply()

    /**
     * RETIRED in v0.7.393 — the Classic / Vitality Neon choice is gone and
     * the neon shell is the only shell.
     *
     * Kept as a constant rather than deleted because ~15 screens read it as
     * a styling flag (`val neon = settings.neonShellEnabled`). Returning
     * true makes every one of them take the neon branch without a
     * fifteen-file edit, and the reads can be unwound at leisure. It no
     * longer touches storage, so a stale stored value can't resurrect a
     * shell that no longer exists.
     */
    @Suppress("unused")
    /**
     * Condensed trail rows. Persisted so the choice survives a relaunch —
     * a density preference the user has to re-set every time is worse than
     * not offering one.
     */
    var trailsDense: Boolean
        get() = plain.getBoolean(KEY_TRAILS_DENSE, false)
        set(value) = plain.edit().putBoolean(KEY_TRAILS_DENSE, value).apply()

    val neonShellEnabled: Boolean get() = true

    /**
     * DISP-1 — unit preference. The phone had none: twelve call sites
     * divided by a hardcoded metres-per-mile constant, so a user who
     * chose metric on the web still saw miles here.
     *
     * Cached locally so the first frame renders in the right unit rather
     * than flipping after a round-trip; the server copy in
     * `user_profile.extra.display` is the source of truth and reconciles
     * on the next sync.
     */
    var unitsImperial: Boolean
        get() = plain.getBoolean(KEY_UNITS_IMPERIAL, true)
        set(value) {
            plain.edit().putBoolean(KEY_UNITS_IMPERIAL, value).apply()
            // Units is read from composables that have no repository
            // handle, so the flag is mirrored there on every write.
            Units.imperial = value
        }

    /** "auto" | "12h" | "24h". */
    var timeFormat: String
        get() = plain.getString(KEY_TIME_FORMAT, "auto") ?: "auto"
        set(value) = plain.edit().putString(KEY_TIME_FORMAT, value).apply()


    /**
     * RETIRED in v0.7.366. "Neon Refined" was a third information
     * architecture rather than a skin: on it Sleep, Steps and Measurements had
     * no reachable entry point, weekly volume cost 4 taps instead of 1, and
     * the blood-pressure card lost its "Optimal" band — so an *appearance*
     * toggle changed a health verdict.
     *
     * The setter is kept only to clear the stored key, so anyone who had it
     * enabled lands on Vitality Neon instead of a shell that no longer exists.
     */
    fun clearRetiredRefinedHomeFlag() {
        if (plain.contains(KEY_REFINED_HOME)) {
            plain.edit().remove(KEY_REFINED_HOME).apply()
        }
    }

    fun lastSyncInstant(): Instant? =
        lastSyncEpochSeconds.takeIf { it > 0 }?.let(Instant::ofEpochSecond)

    fun lastSuccessInstant(): Instant? =
        lastSuccessEpochSeconds.takeIf { it > 0 }?.let(Instant::ofEpochSecond)

    fun isConfigured(): Boolean = backendUrl.isNotBlank() && bearerToken.isNotBlank()

    companion object {
        private const val KEY_TRAILS_DENSE = "trails_dense"
        private const val KEY_UNITS_IMPERIAL = "units_imperial"
        private const val KEY_TIME_FORMAT = "time_format"
        private const val PLAIN_FILE = "myvitals_prefs"
        private const val SECURE_FILE = "myvitals_secure"
        private const val KEY_BACKEND_URL = "backend_url"
        private const val KEY_TOKEN = "bearer_token"
        private const val KEY_LAST_SYNC = "last_sync_epoch_s"
        private const val KEY_LAST_DEEP_SWEEP = "last_deep_sweep_epoch_s"
        private const val KEY_LAST_SUCCESS = "last_success_epoch_s"
        private const val KEY_PERMS_LOST = "perms_lost"
        private const val KEY_NEON_SHELL = "neon_shell_enabled"
        private const val KEY_REFINED_HOME = "refined_home_enabled"
    }
}
