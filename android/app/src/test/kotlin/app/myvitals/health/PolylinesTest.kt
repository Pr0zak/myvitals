package app.myvitals.health

import app.myvitals.sync.WorkoutSample
import com.squareup.moshi.Moshi
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * SA-P3 — the encoder that decides whether the walk draws in Kansas City
 * or in the Atlantic.
 *
 * Nothing else in this app encodes a polyline: every other track arrives
 * already encoded from Strava, Garmin or a FIT import. So this is the one
 * place the format can be got wrong, and it fails in the worst available
 * way — a wrong precision still produces a valid polyline that still
 * renders, just somewhere else on Earth.
 *
 * The decoder used here is written out rather than imported, deliberately.
 * Round-tripping through a shared implementation proves the two halves
 * agree with each other and nothing more; both could be wrong together.
 * This one is transcribed from the phone's OWN map, the `decodePolyline`
 * function inside `ActivityDetailScreen.ActivityMap`'s WebView — so what
 * is being tested is that the encoder agrees with the thing that will
 * actually draw the line.
 */
class PolylinesTest {

    /** Google's reference example: (38.5, -120.2), (40.7, -120.95),
     *  (43.252, -126.453) encodes to this. Published in the polyline
     *  algorithm documentation and reproduced by every implementation. */
    private val REFERENCE_POINTS = listOf(
        38.5 to -120.2,
        40.7 to -120.95,
        43.252 to -126.453,
    )
    private val REFERENCE_ENCODED = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"

    // ── the phone's own WebView decoder, transcribed ──────────────────
    private fun decode(str: String): List<Pair<Double, Double>> {
        var idx = 0
        var lat = 0L
        var lon = 0L
        val out = mutableListOf<Pair<Double, Double>>()
        while (idx < str.length) {
            var shift = 0
            var result = 0L
            var b: Int
            do {
                b = str[idx++].code - 63
                result = result or ((b and 0x1f).toLong() shl shift)
                shift += 5
            } while (b >= 0x20)
            lat += if (result and 1L != 0L) (result shr 1).inv() else (result shr 1)
            shift = 0
            result = 0
            do {
                b = str[idx++].code - 63
                result = result or ((b and 0x1f).toLong() shl shift)
                shift += 5
            } while (b >= 0x20)
            lon += if (result and 1L != 0L) (result shr 1).inv() else (result shr 1)
            out += (lat * 1e-5) to (lon * 1e-5)
        }
        return out
    }

    @Test
    fun `matches Google's published reference encoding`() {
        assertEquals(REFERENCE_ENCODED, Polylines.encode(REFERENCE_POINTS))
    }

    @Test
    fun `the phone's own map decoder reads back what this encodes`() {
        val decoded = decode(Polylines.encode(REFERENCE_POINTS))
        assertEquals(REFERENCE_POINTS.size, decoded.size)
        REFERENCE_POINTS.forEachIndexed { i, (lat, lon) ->
            assertEquals(lat, decoded[i].first, 1e-5)
            assertEquals(lon, decoded[i].second, 1e-5)
        }
    }

    @Test
    fun `a track in the user's own city survives the round trip`() {
        // Coordinates in the shape the production Strava rows decode to,
        // so a precision mistake shows up as a continent-scale error here
        // rather than as a rounding nit.
        val walk = listOf(
            39.16700 to -94.50582,
            39.16698 to -94.50581,
            39.16696 to -94.50579,
            39.16690 to -94.50570,
        )
        val decoded = decode(Polylines.encode(walk))
        assertEquals(walk.size, decoded.size)
        walk.forEachIndexed { i, (lat, lon) ->
            assertEquals(lat, decoded[i].first, 1e-5)
            assertEquals(lon, decoded[i].second, 1e-5)
        }
        // The failure this guards against is a factor of ten, not a
        // rounding error: at precision 6 the first point reads as 3.9.
        assertTrue(decoded[0].first > 39.0 && decoded[0].first < 40.0)
    }

    @Test
    fun `deltas accumulate from the rounded value so a long track cannot drift`() {
        // Every step is half a unit of 1e-5. Differencing raw doubles and
        // rounding each delta independently accumulates that half-unit,
        // and a 2h17m walk is thousands of points — which is exactly
        // where the drift would show and nowhere else.
        val points = (0 until 500).map { i ->
            (39.0 + i * 0.000005) to (-94.5 + i * 0.000005)
        }
        val decoded = decode(Polylines.encode(points))
        assertEquals(points.size, decoded.size)
        val lastLat = decoded.last().first
        assertEquals(39.0 + 499 * 0.000005, lastLat, 1e-5)
    }

    @Test
    fun `rounding is symmetric across the equator and the meridian`() {
        // Math.round is half-UP, which is asymmetric about zero: -0.5
        // rounds to 0 and +0.5 to 1. Every decoder treats the hemispheres
        // symmetrically, so an asymmetric encoder disagrees with its own
        // decoder by 1e-5 on half the planet.
        val north = listOf(0.000005 to 0.000005, 0.00002 to 0.00002)
        val south = listOf(-0.000005 to -0.000005, -0.00002 to -0.00002)
        val dn = decode(Polylines.encode(north))
        val ds = decode(Polylines.encode(south))
        assertEquals(dn[0].first, -ds[0].first, 1e-9)
        assertEquals(dn[0].second, -ds[0].second, 1e-9)
    }

    @Test
    fun `a single fix is not a route`() {
        // Health Connect can hand back a Data result holding one fix — a
        // GPS lock taken at the start of a session that then lost signal.
        // It encodes to a perfectly valid polyline that draws nothing, and
        // both clients gate their Route card on the polyline being
        // present, so storing it would open a map card onto an empty world.
        assertNull(Polylines.encodeOrNull(listOf(39.167 to -94.506)))
        assertNull(Polylines.encodeOrNull(emptyList()))
        assertNotNull(Polylines.encodeOrNull(listOf(
            39.167 to -94.506, 39.168 to -94.507,
        )))
    }
}

/**
 * The three states, and the wire words they turn into. A typo in any of
 * them makes both clients fall through to "nobody asked" about a route
 * that is sitting in Health Connect withheld — which is precisely the
 * silence SA-P3 exists to end, reintroduced one string at a time.
 */
class RouteReadWireTest {

    @Test
    fun `a track needs no excuse for not having a track`() {
        val t: RouteRead = RouteRead.Track("abc", 42)
        assertNull(t.wireState)
        assertEquals("AVAILABLE", t.probeLabel)
    }

    @Test
    fun `the withheld and absent states are spelled the way the column stores them`() {
        assertEquals("consent_required", RouteRead.ConsentRequired.wireState)
        assertEquals("none", RouteRead.NoData.wireState)
    }

    @Test
    fun `the probe vocabulary is unchanged so old log queries still match`() {
        // `select ... from app_logs where tag = 'HCRouteProbe'` is how the
        // original answer was found. A regression has to be findable the
        // same way.
        assertEquals("CONSENT_REQUIRED", RouteRead.ConsentRequired.probeLabel)
        assertEquals("NO_DATA", RouteRead.NoData.probeLabel)
    }
}

/**
 * The wire field, through the real Moshi adapter — R8 is on for release
 * and the adapter is generated, so "does this serialise" is a question
 * only a test can answer before a user does.
 */
class WorkoutSampleRouteJsonTest {

    private val moshi = Moshi.Builder().build()
    private val adapter = moshi.adapter(WorkoutSample::class.java)

    @Test
    fun `a sample with no route omits nothing it should send and claims nothing it should not`() {
        val w = WorkoutSample(time = "2026-09-19T14:05:05Z", type = "walking",
                              durationS = 8217)
        assertNull(w.polyline)
        assertNull(w.routeState)
        // Not "" — an empty string is a present value, and the backend's
        // `is not None` filter would let it through and blank a stored
        // track.
        assertTrue(adapter.toJson(w).let { !it.contains("\"polyline\":\"\"") })
    }

    @Test
    fun `route_state is the snake_case name the backend reads`() {
        val w = WorkoutSample(time = "2026-09-19T14:05:05Z", type = "walking",
                              durationS = 8217, routeState = "consent_required")
        val json = adapter.toJson(w)
        assertTrue(json, json.contains("\"route_state\":\"consent_required\""))
        assertTrue(json, !json.contains("routeState"))
    }

    @Test
    fun `a track survives the round trip`() {
        val w = WorkoutSample(time = "2026-09-19T14:05:05Z", type = "walking",
                              durationS = 8217, polyline = "_p~iF~ps|U")
        assertEquals("_p~iF~ps|U", adapter.fromJson(adapter.toJson(w))!!.polyline)
    }

    @Test
    fun `absent keys deserialise to null, never to a zero-length route`() {
        // CLAUDE.md's Moshi-defaults landmine: whatever the Kotlin default
        // is, that is what a replayed buffered batch gets when the JSON
        // omits the key. Null is the only default that means "this sample
        // says nothing about a route".
        val w = adapter.fromJson(
            """{"time":"2026-09-19T14:05:05Z","type":"walking","duration_s":8217}"""
        )!!
        assertNull(w.polyline)
        assertNull(w.routeState)
    }
}
