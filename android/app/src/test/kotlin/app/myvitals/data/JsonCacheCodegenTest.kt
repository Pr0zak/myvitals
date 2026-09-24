package app.myvitals.data

import app.myvitals.ui.vitals.BpReading
import app.myvitals.ui.vitals.VitalsSeries
import app.myvitals.sync.RangeStats
import app.myvitals.sync.StepsRangeStats
import app.myvitals.sync.WeightSeriesOut
import app.myvitals.sync.WeightStats
import app.myvitals.sync.WeightPointOut
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * SA-C1: the exact regression this codebase is one annotation away from
 * reintroducing. `JsonCache`'s Moshi has no reflective fallback, so a screen
 * caching a new local type only fails at runtime (`Moshi.Builder().build()`
 * cannot find a generated adapter) — never at compile time. `WPoint` (now
 * replaced by `WeightSeriesOut`, UI-4) and
 * `BpReading` were `private data class` (moshi-kotlin-codegen's generated
 * adapter lives in a separate file and can't see a file-private one) and
 * `VitalsSeries` had no `@JsonClass` at all; all three are exercised through
 * `JsonCache.read`/`write` from their screens. This pins that every type
 * JsonCache actually caches resolves through the same construction
 * `JsonCache` uses, and round-trips correctly.
 */
class JsonCacheCodegenTest {

    private val moshi = Moshi.Builder().build()

    @Test
    fun `WeightSeriesOut (weight detail cache, UI-4) round-trips through the real JsonCache adapter`() {
        val adapter = moshi.adapter(WeightSeriesOut::class.java)
        val v = WeightSeriesOut(
            points = listOf(WeightPointOut(time = "2026-09-01T12:00:00Z", weightKg = 82.3)),
            stats = WeightStats(count = 1, latestKg = 82.3, tone = "neutral"),
        )
        assertEquals(v, adapter.fromJson(adapter.toJson(v)))
    }

    @Test
    fun `RangeStats (steps, HR and sleep detail cache, UI-4) round-trips`() {
        val adapter = moshi.adapter(RangeStats::class.java)
        val v = RangeStats(since = "2026-09-01", until = "2026-09-30",
            steps = StepsRangeStats(avg = 8000, daysWithData = 3, goalDays = 1))
        assertEquals(v, adapter.fromJson(adapter.toJson(v)))
    }

    @Test
    fun `hourly steps cache (List of Int) round-trips`() {
        val type = Types.newParameterizedType(List::class.java, Integer::class.java)
        val adapter = moshi.adapter<List<Int>>(type)
        val v = List(24) { it * 10 }
        assertEquals(v, adapter.fromJson(adapter.toJson(v)))
    }

    @Test
    fun `BpReading (blood pressure detail cache) round-trips through the real JsonCache adapter`() {
        val listType = Types.newParameterizedType(List::class.java, BpReading::class.java)
        val adapter = moshi.adapter<List<BpReading>>(listType)
        val pts = listOf(BpReading(ms = 1_726_000_000_000L, sys = 118, dia = 76))

        val json = adapter.toJson(pts)
        val back = adapter.fromJson(json)!!

        assertEquals(pts, back)
    }

    @Test
    fun `VitalsSeries (vitals detail cache) round-trips through the real JsonCache adapter`() {
        val adapter = moshi.adapter(VitalsSeries::class.java)
        val series = VitalsSeries(xs = listOf(0.0, 1.0, 2.0), ys = listOf(70.5, 71.0, 69.8))

        val json = adapter.toJson(series)
        val back = adapter.fromJson(json)!!

        assertEquals(series, back)
    }
}
