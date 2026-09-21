package app.myvitals.health

/**
 * Google encoded polyline, precision 5 — the exact format
 * `activities.polyline` already holds for every other provider, so a track
 * read from Health Connect renders through the renderers that are already
 * there rather than needing a second path.
 *
 * Precision 5 is not a guess. A Strava row pulled from the production
 * database decodes cleanly at precision 5 to 2,920 points in the user's
 * own city and round-trips back to the identical string; at precision 6
 * the same bytes decode to coordinates a factor of ten off, in the Gulf of
 * Guinea. The backend's `analytics/geo.py` and `api/imports.py` both use
 * the Python `polyline` library's default (5), the web decodes with
 * `@mapbox/polyline` (default 5) and the phone's own map WebView decodes
 * with a hand-written `lat * 1e-5`. Five it is, in five places; changing
 * it here alone would silently draw every phone-sourced walk in the
 * Atlantic.
 *
 * The algorithm is the published one: take the signed offset from the
 * previous point, round to 1e-5 degrees, zig-zag it into an unsigned
 * integer, then emit it five bits at a time, low bits first, with the
 * continuation bit set on every chunk but the last, each chunk offset by
 * 63 into printable ASCII.
 *
 * Two details that are easy to get wrong and are what the tests pin:
 *
 *  - **Deltas are accumulated from the ROUNDED previous value, not the
 *    raw one.** Rounding each coordinate independently and differencing
 *    the raw doubles lets a half-unit of error accumulate across a long
 *    track; a 2h17m walk is thousands of points, which is exactly where
 *    a drifting encoder would show up and nowhere else.
 *  - **Rounding is half-away-from-zero, not Kotlin's `Math.round`**, which
 *    is half-UP and therefore asymmetric across the equator and the prime
 *    meridian. Every decoder treats the two hemispheres symmetrically, so
 *    an asymmetric encoder disagrees with its own decoder by 1e-5 on half
 *    the planet.
 */
internal object Polylines {

    private const val FACTOR = 1e5

    /**
     * Encode [points] — `(latitude, longitude)` in degrees, in order — as
     * one Google polyline string. An empty list encodes to `""`, which is
     * deliberately NOT the same value as "no route": the caller must not
     * post an empty string as a polyline, because `activity.polyline`
     * being a non-null empty string would make both clients render a Route
     * card around an invisible zero-length line. See [encodeOrNull].
     */
    fun encode(points: List<Pair<Double, Double>>): String {
        val sb = StringBuilder(points.size * 6)
        var prevLat = 0L
        var prevLon = 0L
        for ((lat, lon) in points) {
            val e5Lat = round5(lat)
            val e5Lon = round5(lon)
            appendValue(sb, e5Lat - prevLat)
            appendValue(sb, e5Lon - prevLon)
            prevLat = e5Lat
            prevLon = e5Lon
        }
        return sb.toString()
    }

    /**
     * [encode], but null for anything that cannot draw a line.
     *
     * A single-point "track" is a real thing Health Connect can hand back
     * — a GPS fix taken at the start of a session that then lost signal —
     * and it encodes to a perfectly valid polyline that renders as
     * nothing. Both clients gate their Route card on the polyline being
     * present, so storing one would open a map card onto an empty world.
     * Fewer than two points is no route.
     */
    fun encodeOrNull(points: List<Pair<Double, Double>>): String? {
        if (points.size < 2) return null
        return encode(points).ifEmpty { null }
    }

    /** Half-away-from-zero, in units of 1e-5 degrees. */
    private fun round5(deg: Double): Long {
        val scaled = deg * FACTOR
        return if (scaled < 0) -Math.round(-scaled) else Math.round(scaled)
    }

    private fun appendValue(sb: StringBuilder, delta: Long) {
        var v = if (delta < 0) (delta shl 1).inv() else (delta shl 1)
        while (v >= 0x20) {
            sb.append((((0x20 or (v and 0x1f).toInt()) + 63)).toChar())
            v = v shr 5
        }
        sb.append((v.toInt() + 63).toChar())
    }
}
