package app.myvitals.data

import kotlin.math.roundToInt

/**
 * DISP-1 — unit conversion and formatting for the phone.
 *
 * The phone had no unit preference at all. Twelve call sites across eight
 * files divided by a hardcoded metres-per-mile constant, and they did not
 * even agree on the constant: some used 1609.34, others 1609.344. The web
 * has had a preference since early on, so a user who set metric there
 * still saw miles on their phone.
 *
 * Mirrors `frontend/src/units.ts` deliberately — same conversion factors,
 * same rounding, same unit labels — so the two surfaces cannot print
 * different numbers for the same measurement.
 *
 * The backend always stores SI (metres, kg, °C); conversion happens here,
 * at the edge, and never in a repository or on the server.
 */
object Units {

    // Exact definitions, not the truncated forms that were in use.
    private const val M_PER_MILE = 1609.344
    private const val M_PER_FT = 0.3048
    private const val KG_PER_LB = 0.45359237

    /** Set from SettingsRepository at app start and whenever it changes. */
    @Volatile
    var imperial: Boolean = true

    // ── Distance ──────────────────────────────────────────────────────

    val distanceUnit: String get() = if (imperial) "mi" else "km"

    /** Numeric distance in the user's unit, or null. */
    fun distance(meters: Double?): Double? {
        if (meters == null) return null
        return if (imperial) meters / M_PER_MILE else meters / 1000.0
    }

    /** "7.7 mi" / "12.4 km". Null renders as an em dash, never as 0. */
    fun fmtDistance(meters: Double?, digits: Int = 1): String {
        val v = distance(meters) ?: return "—"
        return "%.${digits}f %s".format(v, distanceUnit)
    }

    // ── Elevation ─────────────────────────────────────────────────────

    val elevationUnit: String get() = if (imperial) "ft" else "m"

    fun elevation(meters: Double?): Double? {
        if (meters == null) return null
        return if (imperial) meters / M_PER_FT else meters
    }

    fun fmtElevation(meters: Double?): String {
        val v = elevation(meters) ?: return "—"
        return "${v.roundToInt()} $elevationUnit"
    }

    // ── Weight ────────────────────────────────────────────────────────

    val weightUnit: String get() = if (imperial) "lb" else "kg"

    fun weight(kg: Double?): Double? {
        if (kg == null) return null
        return if (imperial) kg / KG_PER_LB else kg
    }

    fun fmtWeight(kg: Double?, digits: Int = 1): String {
        val v = weight(kg) ?: return "—"
        return "%.${digits}f %s".format(v, weightUnit)
    }

    /** A user-entered weight back to kg for storage. */
    fun weightToKg(value: Double): Double =
        if (imperial) value * KG_PER_LB else value

    // ── Temperature ───────────────────────────────────────────────────

    val tempDeltaUnit: String get() = if (imperial) "ΔF" else "ΔC"

    /**
     * Skin-temperature values are DELTAS from baseline, so only the
     * magnitude converts (ΔF = ΔC × 9/5). Applying the +32 offset here
     * would turn a 0.2 °C deviation into 32.4 °F.
     */
    fun tempDelta(celsius: Double?): Double? {
        if (celsius == null) return null
        return if (imperial) celsius * 1.8 else celsius
    }

    fun fmtTempDelta(celsius: Double?, digits: Int = 2): String {
        val v = tempDelta(celsius) ?: return "—"
        return "%.${digits}f %s".format(v, tempDeltaUnit)
    }

    // ── Pace ──────────────────────────────────────────────────────────

    /** Minutes per mile or per km, as "8:42 /mi". */
    fun fmtPace(metersPerSecond: Double?): String {
        if (metersPerSecond == null || metersPerSecond <= 0) return "—"
        val secPerUnit =
            if (imperial) M_PER_MILE / metersPerSecond else 1000.0 / metersPerSecond
        val m = (secPerUnit / 60).toInt()
        val s = (secPerUnit % 60).roundToInt()
        return "%d:%02d /%s".format(m, s, distanceUnit)
    }
}
