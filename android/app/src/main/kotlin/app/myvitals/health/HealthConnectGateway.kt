package app.myvitals.health

import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.PermissionController
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.DistanceRecord
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.HeartRateVariabilityRmssdRecord
import androidx.health.connect.client.records.OxygenSaturationRecord
import androidx.health.connect.client.records.Record
import androidx.health.connect.client.records.SkinTemperatureRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import kotlinx.coroutines.runBlocking
import timber.log.Timber
import java.time.Instant
import kotlin.reflect.KClass

class HealthConnectGateway(private val context: Context) {

    val requiredPermissions: Set<String> = setOf(
        HealthPermission.getReadPermission(HeartRateRecord::class),
        HealthPermission.getReadPermission(HeartRateVariabilityRmssdRecord::class),
        HealthPermission.getReadPermission(OxygenSaturationRecord::class),
        HealthPermission.getReadPermission(SkinTemperatureRecord::class),
        HealthPermission.getReadPermission(StepsRecord::class),
        // HC seems to require READ_DISTANCE when reading some Steps-related sources
        // ("record type 11" SecurityException). Asking for it preempts the rejection.
        HealthPermission.getReadPermission(DistanceRecord::class),
        HealthPermission.getReadPermission(SleepSessionRecord::class),
        HealthPermission.getReadPermission(ExerciseSessionRecord::class),
    )

    fun isAvailable(): Boolean =
        HealthConnectClient.getSdkStatus(context) == HealthConnectClient.SDK_AVAILABLE

    private fun client(): HealthConnectClient = HealthConnectClient.getOrCreate(context)

    fun permissionContract() =
        PermissionController.createRequestPermissionResultContract()

    fun hasAllPermissions(): Boolean {
        if (!isAvailable()) return false
        val granted = runBlocking { client().permissionController.getGrantedPermissions() }
        return granted.containsAll(requiredPermissions)
    }

    /**
     * Reads ALL records of [type] in the time range, walking HC's pageToken.
     * pageSize=5000 (HC max) keeps round-trips down. Hard cap at 100 pages
     * (≤ 500k records) to avoid runaway loops on bad data.
     */
    suspend fun <T : Record> read(
        type: KClass<T>,
        since: Instant,
        until: Instant = Instant.now(),
    ): List<T> {
        val all = mutableListOf<T>()
        var pageToken: String? = null
        var page = 0
        do {
            val request = ReadRecordsRequest(
                recordType = type,
                timeRangeFilter = TimeRangeFilter.between(since, until),
                pageSize = 5000,
                pageToken = pageToken,
            )
            val response = client().readRecords(request)
            all.addAll(response.records)
            pageToken = response.pageToken
            page++
            if (page >= 100) {
                Timber.w("HC %s: 100-page safety cap hit (records=%d)", type.simpleName, all.size)
                break
            }
        } while (pageToken != null)
        return all
    }
}
