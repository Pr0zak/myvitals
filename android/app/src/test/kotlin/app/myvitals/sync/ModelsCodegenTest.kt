package app.myvitals.sync

import com.squareup.moshi.Moshi
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * Every data class in Models.kt must carry `@JsonClass(generateAdapter = true)`.
 *
 * `BackendClient` builds a plain `Moshi.Builder().build()` with no Kotlin
 * reflection factory, so a class without a generated adapter falls back to
 * Java-field reflection — and the release build runs R8, which renames those
 * fields. Nothing fails: the request goes out with obfuscated keys, the
 * server ignores keys it does not know, and answers 200. v0.45.0 shipped
 * `ActivityEditBody` that way; the activity-type correction returned
 * success and changed nothing. Debug builds are not minified, so this is
 * invisible everywhere except on the phone.
 */
class ModelsCodegenTest {

    @Test
    fun `every data class in Models kt has a generated adapter`() {
        val src = File("src/main/kotlin/app/myvitals/sync/Models.kt").readLines()
        val missing = mutableListOf<String>()
        for ((i, line) in src.withIndex()) {
            val m = Regex("""^data class (\w+)""").find(line) ?: continue
            // Walk back over KDoc / blank lines to the nearest real line.
            var j = i - 1
            while (j >= 0) {
                val t = src[j].trim()
                if (t.isEmpty() || t.startsWith("*") || t.startsWith("/**") || t.startsWith("//")) { j--; continue }
                break
            }
            if (j < 0 || !src[j].contains("@JsonClass(generateAdapter = true)")) {
                missing += "${m.groupValues[1]} (line ${i + 1})"
            }
        }
        assertTrue("data classes without @JsonClass: $missing", missing.isEmpty())
    }

    @Test
    fun `the activity edit body serialises with its real keys`() {
        // Resolves through the generated adapter (the class exists only if
        // codegen ran), and the keys are the ones the server reads.
        Class.forName("app.myvitals.sync.ActivityEditBodyJsonAdapter")
        val json = Moshi.Builder().build().adapter(ActivityEditBody::class.java)
            .toJson(ActivityEditBody(type = "yard_work"))
        assertEquals("""{"type":"yard_work"}""", json)
    }
}
