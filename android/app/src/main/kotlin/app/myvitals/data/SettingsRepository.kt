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

    fun lastSyncInstant(): Instant? =
        lastSyncEpochSeconds.takeIf { it > 0 }?.let(Instant::ofEpochSecond)

    fun lastSuccessInstant(): Instant? =
        lastSuccessEpochSeconds.takeIf { it > 0 }?.let(Instant::ofEpochSecond)

    fun isConfigured(): Boolean = backendUrl.isNotBlank() && bearerToken.isNotBlank()

    companion object {
        private const val PLAIN_FILE = "myvitals_prefs"
        private const val SECURE_FILE = "myvitals_secure"
        private const val KEY_BACKEND_URL = "backend_url"
        private const val KEY_TOKEN = "bearer_token"
        private const val KEY_LAST_SYNC = "last_sync_epoch_s"
        private const val KEY_LAST_DEEP_SWEEP = "last_deep_sweep_epoch_s"
        private const val KEY_LAST_SUCCESS = "last_success_epoch_s"
        private const val KEY_PERMS_LOST = "perms_lost"
    }
}
