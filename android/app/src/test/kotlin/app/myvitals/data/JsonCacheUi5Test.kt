package app.myvitals.data

import app.myvitals.snapshots.SampleDataUi5
import app.myvitals.sync.ActivityYtd
import app.myvitals.sync.TrailsResponse
import com.squareup.moshi.Moshi
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * UI-5 caches two new shapes through JsonCache, whose Moshi has no
 * reflective fallback (see JsonCacheCodegenTest): the whole /activities/ytd
 * response, and the whole /trails response so the hero's server counts
 * render offline. Both must resolve a generated adapter and round-trip.
 */
class JsonCacheUi5Test {
    private val moshi = Moshi.Builder().build()

    @Test
    fun `ActivityYtd round-trips, keeping a null percentage null`() {
        val adapter = moshi.adapter(ActivityYtd::class.java)
        val back = adapter.fromJson(adapter.toJson(SampleDataUi5.ytd))!!
        assertEquals(SampleDataUi5.ytd, back)
        // "new" when last year was zero — never coerced to a number.
        assertNull(back.metrics.first { it.key == "elevation_m" }.pctChange)
    }

    @Test
    fun `TrailsResponse round-trips with its server status counts`() {
        val adapter = moshi.adapter(TrailsResponse::class.java)
        val r = TrailsResponse(
            count = SampleDataUi5.trails.size, trails = SampleDataUi5.trails,
            statusCounts = SampleDataUi5.trailsUi.counts, syncedAt = SampleDataUi5.trailsUi.syncedAt,
        )
        assertEquals(r, adapter.fromJson(adapter.toJson(r)))
    }

    @Test
    fun `an older backend without counts still parses`() {
        val adapter = moshi.adapter(TrailsResponse::class.java)
        val r = adapter.fromJson("""{"count":0,"trails":[]}""")!!
        assertNull(r.statusCounts)
        assertNull(r.syncedAt)
    }
}
