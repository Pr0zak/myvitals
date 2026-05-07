package app.myvitals.data

import android.content.Context
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase
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

@Entity(tableName = "logs")
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

@Database(
    entities = [BufferedBatch::class, LogEntry::class, BufferedStrengthSet::class],
    version = 3,
    exportSchema = false,
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun buffered(): BufferedBatchDao
    abstract fun logs(): LogDao
    abstract fun bufferedStrengthSets(): BufferedStrengthSetDao

    companion object {
        @Volatile private var instance: AppDatabase? = null

        fun get(context: Context): AppDatabase = instance ?: synchronized(this) {
            instance ?: Room.databaseBuilder(
                context.applicationContext,
                AppDatabase::class.java,
                "myvitals.db",
            )
                // Pre-1.0 schema; cheaper to drop than to maintain migrations.
                .fallbackToDestructiveMigration()
                .build()
                .also { instance = it }
        }
    }
}
