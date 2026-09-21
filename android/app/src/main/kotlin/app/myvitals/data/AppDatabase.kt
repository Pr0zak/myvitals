package app.myvitals.data

import android.content.Context
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Index
import androidx.room.Insert
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import kotlinx.coroutines.flow.Flow

@Entity(tableName = "buffered_batches")
data class BufferedBatch(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val json: String,
    val createdAtEpochS: Long,
    val attempts: Int = 0,
)

@Dao
interface BufferedBatchDao {
    @Insert
    suspend fun insert(batch: BufferedBatch)

    @Query("SELECT * FROM buffered_batches ORDER BY createdAtEpochS ASC LIMIT 50")
    suspend fun oldest(): List<BufferedBatch>

    @Query("DELETE FROM buffered_batches WHERE id = :id")
    suspend fun delete(id: Long)

    @Query("UPDATE buffered_batches SET attempts = attempts + 1 WHERE id = :id")
    suspend fun incrementAttempts(id: Long)

    @Query("SELECT COUNT(*) FROM buffered_batches")
    suspend fun count(): Int

    @Query("DELETE FROM buffered_batches")
    suspend fun clear()

    @Query("SELECT id, length(json) AS json_len, attempts, createdAtEpochS FROM buffered_batches ORDER BY createdAtEpochS ASC")
    suspend fun summaries(): List<BufferedSummary>
}

data class BufferedSummary(
    val id: Long,
    val json_len: Int,
    val attempts: Int,
    val createdAtEpochS: Long,
)

@Entity(
    tableName = "logs",
    indices = [
        Index(value = ["uploadedAt", "tsEpochMs"]),  // unsent() query filter + sort
    ]
)
data class LogEntry(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val tsEpochMs: Long,
    val level: Int,                 // android.util.Log priority (2..7)
    val tag: String?,
    val message: String,
    val stack: String? = null,
    val uploadedAt: Long? = null,
)

@Dao
interface LogDao {
    @Insert
    suspend fun insert(entry: LogEntry): Long

    @Query("SELECT * FROM logs ORDER BY tsEpochMs DESC LIMIT :limit")
    fun recentFlow(limit: Int = 500): Flow<List<LogEntry>>

    @Query("SELECT * FROM logs WHERE uploadedAt IS NULL ORDER BY tsEpochMs ASC LIMIT :limit")
    suspend fun unsent(limit: Int = 200): List<LogEntry>

    @Query("UPDATE logs SET uploadedAt = :now WHERE id IN (:ids)")
    suspend fun markSent(ids: List<Long>, now: Long)

    @Query("DELETE FROM logs WHERE tsEpochMs < :before")
    suspend fun deleteOlderThan(before: Long)

    @Query("DELETE FROM logs")
    suspend fun clear()
}

/**
 * One row per logged strength set that couldn't be POSTed (offline or
 * backend down). Pushed best-effort by SyncWorker / a manual flush.
 * Idempotent on (workout_exercise_id, set_number) at the backend.
 */
@Entity(tableName = "buffered_strength_sets")
data class BufferedStrengthSet(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val jsonBody: String,
    val createdAtEpochS: Long,
    val attempts: Int = 0,
)

@Dao
interface BufferedStrengthSetDao {
    @Insert
    suspend fun insert(row: BufferedStrengthSet)

    @Query("SELECT * FROM buffered_strength_sets ORDER BY createdAtEpochS ASC LIMIT 100")
    suspend fun oldest(): List<BufferedStrengthSet>

    @Query("DELETE FROM buffered_strength_sets WHERE id = :id")
    suspend fun delete(id: Long)

    @Query("UPDATE buffered_strength_sets SET attempts = attempts + 1 WHERE id = :id")
    suspend fun bumpAttempts(id: Long)

    @Query("SELECT COUNT(*) FROM buffered_strength_sets")
    suspend fun count(): Int
}

/**
 * One row per workout-mutation write (complete / skip / discard / pref)
 * that couldn't be sent. Replayed in oldest-first order. The `kind`
 * field tags the call so the dispatcher knows which Retrofit method
 * to invoke; `path` is the resource id (workout id, exercise id) the
 * call targets; `jsonBody` is the serialized body if any.
 */
@Entity(tableName = "buffered_workout_writes")
data class BufferedWorkoutWrite(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val kind: String,            // patch_workout | set_pref
    val path: String,            // e.g. "42" or "Goblet_Squat"
    val jsonBody: String,
    val createdAtEpochS: Long,
    val attempts: Int = 0,
)

@Dao
interface BufferedWorkoutWriteDao {
    @Insert
    suspend fun insert(row: BufferedWorkoutWrite)

    @Query("SELECT * FROM buffered_workout_writes ORDER BY createdAtEpochS ASC LIMIT 100")
    suspend fun oldest(): List<BufferedWorkoutWrite>

    @Query("DELETE FROM buffered_workout_writes WHERE id = :id")
    suspend fun delete(id: Long)

    @Query("UPDATE buffered_workout_writes SET attempts = attempts + 1 WHERE id = :id")
    suspend fun bumpAttempts(id: Long)

    @Query("SELECT COUNT(*) FROM buffered_workout_writes")
    suspend fun count(): Int
}


/**
 * v4 -> v5: add the index SA-C3 declared on `logs`.
 *
 * SA-C3 added `Index(value = ["uploadedAt", "tsEpochMs"])` to [LogEntry] and
 * left `version = 4`. Room hashes the schema and compares it on open, so the
 * mismatch threw `IllegalStateException: Room cannot verify the data
 * integrity` — and `fallbackToDestructiveMigration` did NOT rescue it, because
 * that only applies when the version number moves. With the database
 * unopenable, `SyncWorker`'s strength flush threw on every tick and took the
 * whole sync down with it: no telemetry reached the server for nine hours,
 * across v0.40.1 and v0.41.0.
 *
 * A destructive fallback would have been one character cheaper and would have
 * silently discarded `buffered_strength_sets` and `buffered_workout_writes` —
 * offline set logs and status patches that exist because they have not been
 * delivered yet. This creates the index instead, matching the name Room
 * derives for that entity, and leaves every row in place.
 */
val MIGRATION_4_5 = object : Migration(4, 5) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL(
            "CREATE INDEX IF NOT EXISTS index_logs_uploadedAt_tsEpochMs " +
                "ON logs (uploadedAt, tsEpochMs)"
        )
    }
}

@Database(
    entities = [
        BufferedBatch::class, LogEntry::class,
        BufferedStrengthSet::class, BufferedWorkoutWrite::class,
    ],
    version = 5,
    exportSchema = false,
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun buffered(): BufferedBatchDao
    abstract fun logs(): LogDao
    abstract fun bufferedStrengthSets(): BufferedStrengthSetDao
    abstract fun bufferedWorkoutWrites(): BufferedWorkoutWriteDao

    companion object {
        @Volatile private var instance: AppDatabase? = null

        fun get(context: Context): AppDatabase = instance ?: synchronized(this) {
            instance ?: Room.databaseBuilder(
                context.applicationContext,
                AppDatabase::class.java,
                "myvitals.db",
            )
                .addMigrations(MIGRATION_4_5)
                // Pre-1.0 schema; cheaper to drop than to maintain migrations.
                // That still holds for a table shape change, but NOT for the
                // buffered-write tables: dropping those loses sets and status
                // patches logged while offline, which exist precisely because
                // they could not be sent yet. Anything touching them gets a
                // real migration.
                .fallbackToDestructiveMigration()
                .build()
                .also { instance = it }
        }
    }
}
