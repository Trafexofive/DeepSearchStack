package com.substrate.ytlab.data

import androidx.room.*

@Entity(tableName = "jobs")
data class JobEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    @ColumnInfo(name = "url") val url: String,
    @ColumnInfo(name = "type") val type: String,  // "video" or "channel"
    @ColumnInfo(name = "title") val title: String = "",
    @ColumnInfo(name = "channel") val channel: String = "",
    @ColumnInfo(name = "result") val result: String = "",
    @ColumnInfo(name = "status") val status: String = "pending",  // pending, done, error
    @ColumnInfo(name = "created_at") val createdAt: Long = System.currentTimeMillis(),
)

@Dao
interface JobDao {
    @Query("SELECT * FROM jobs ORDER BY created_at DESC")
    suspend fun getAll(): List<JobEntity>

    @Query("SELECT * FROM jobs WHERE id = :id")
    suspend fun getById(id: Long): JobEntity?

    @Insert
    suspend fun insert(job: JobEntity): Long

    @Update
    suspend fun update(job: JobEntity)

    @Query("DELETE FROM jobs WHERE id = :id")
    suspend fun delete(id: Long)

    @Query("SELECT COUNT(*) FROM jobs")
    suspend fun count(): Int
}

@Database(entities = [JobEntity::class], version = 1, exportSchema = false)
abstract class AppDatabase : RoomDatabase() {
    abstract fun jobDao(): JobDao

    companion object {
        @Volatile
        private var INSTANCE: AppDatabase? = null

        fun getInstance(context: android.content.Context): AppDatabase {
            return INSTANCE ?: synchronized(this) {
                INSTANCE ?: Room.databaseBuilder(
                    context.applicationContext,
                    AppDatabase::class.java,
                    "ytlab.db"
                ).build().also { INSTANCE = it }
            }
        }
    }
}
