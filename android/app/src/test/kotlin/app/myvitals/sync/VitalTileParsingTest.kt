package app.myvitals.sync

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The tiles payload parses, against a real capture from the live backend.
 *
 * `VitalTile.value` is `Any?` because blood pressure is the string "139/92"
 * while every other metric is a number. That is the riskiest thing in the
 * wire model: if Moshi mishandles it the grid renders empty, and the Kotlin
 * still compiles perfectly — nothing short of running the app would show it.
 *
 * The fixture in `src/test/resources/tiles_live.json` is an actual response,
 * not a hand-written sample, so field names and shapes are the server's.
 *
 * Note this project has no Moshi codegen processor: `@JsonClass` is inert
 * and everything resolves through `KotlinJsonAdapterFactory` reflection —
 * the same construction `BackendClient` uses, mirrored here deliberately.
 */
class VitalTileParsingTest {

    private val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()

    private fun parse(): VitalTilesResponse {
        val json = javaClass.classLoader!!
            .getResourceAsStream("tiles_live.json")!!
            .bufferedReader().readText()
        return moshi.adapter(VitalTilesResponse::class.java).fromJson(json)!!
    }

    @Test
    fun `the live payload parses into every tile`() {
        val r = parse()
        assertEquals("2026-08-09", r.date)
        assertEquals(7, r.tiles.size)
        assertEquals(
            listOf("hrv", "resting_hr", "steps", "sleep_duration",
                   "blood_pressure", "recovery", "weight"),
            r.tiles.map { it.key },
        )
    }

    @Test
    fun `blood pressure survives as a string and renders unchanged`() {
        val bp = parse().tiles.first { it.key == "blood_pressure" }
        assertTrue("expected a String, got ${bp.value?.javaClass}", bp.value is String)
        assertEquals("139/92", bp.displayValue())
    }

    @Test
    fun `numeric metrics don't render a stray decimal`() {
        // Moshi parses every JSON number as Double, so an integer metric
        // would read "5.0 steps" without the formatting in displayValue().
        val tiles = parse().tiles
        assertEquals("5", tiles.first { it.key == "steps" }.displayValue())
        assertEquals("83", tiles.first { it.key == "recovery" }.displayValue())
        // ...while a genuinely fractional metric keeps its decimal.
        assertEquals("27.3", tiles.first { it.key == "hrv" }.displayValue())
    }

    @Test
    fun `snake_case fields land on their camelCase properties`() {
        // A silently-missed @Json name is invisible: the field just stays
        // null and the tile renders without its reason or staleness.
        val weight = parse().tiles.first { it.key == "weight" }
        assertEquals(90, weight.staleDays)
        assertEquals("2026-05-11", weight.asOf)

        val hrv = parse().tiles.first { it.key == "hrv" }
        assertEquals(true, hrv.higherIsBetter)
        assertTrue(hrv.statusReason!!.contains("baseline"))
    }

    @Test
    fun `series gaps stay null rather than collapsing to zero`() {
        // A null rendered as 0.0 would draw the sparkline to the floor and
        // imply a crash that never happened.
        val hrv = parse().tiles.first { it.key == "hrv" }
        assertEquals(14, hrv.series.size)
        assertTrue("fixture should contain at least one gap",
                   hrv.series.any { it.value == null })
        assertTrue(hrv.series.none { it.value == 0.0 })
    }

    @Test
    fun `a withheld verdict parses as an absent status, not an empty string`() {
        val bp = parse().tiles.first { it.key == "blood_pressure" }
        assertNull(bp.status)
        assertTrue(bp.statusReason!!.contains("days ago"))
    }

    @Test
    fun `an unknown future field does not break the parse`() {
        // The backend adds tile fields freely; a strict model would start
        // failing on deploy order alone.
        val json = """
            {"date":"2026-08-09","tiles":[
              {"key":"hrv","label":"HRV","unit":"ms","value":27.3,
               "series":[],"brand_new_field":123}]}
        """.trimIndent()
        val r = moshi.adapter(VitalTilesResponse::class.java).fromJson(json)!!
        assertEquals(1, r.tiles.size)
        assertEquals("27.3", r.tiles[0].displayValue())
    }
}
