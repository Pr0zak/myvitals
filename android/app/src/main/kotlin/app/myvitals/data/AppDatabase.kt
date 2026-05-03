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
}

@Database(entities = [BufferedBatch::class], version = 1, exportSchema = false)
abstract class AppDatabase : RoomDatabase() {
    abstract fun buffered(): BufferedBatchDao

    companion object {
        @Volatile private var instance: AppDatabase? = null

        fun get(context: Context): AppDatabase = instance ?: synchronized(this) {
            instance ?: Room.databaseBuilder(
                context.applicationContext,
                AppDatabase::class.java,
                "myvitals.db",
            ).build().also { instance = it }
        }
    }
}
