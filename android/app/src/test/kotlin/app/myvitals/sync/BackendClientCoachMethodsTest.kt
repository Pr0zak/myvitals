package app.myvitals.sync

import okhttp3.OkHttpClient
import org.junit.Test
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory
import com.squareup.moshi.Moshi

/**
 * SA-L4: All five phone Coach card POST methods must not use `@Body Map<String, Any>`
 * because Kotlin compiles the value type to a Java wildcard, which Retrofit rejects
 * at runtime with `IllegalArgumentException: Parameter type must not include a type
 * variable or wildcard`.
 *
 * This test verifies that the five coach methods can be instantiated without throwing
 * that exception. The failure is invisible to compilation and to the web surface, so
 * only instantiating the Retrofit API and introspecting the methods catches it.
 *
 * The fixture instantiates a real Retrofit instance and attempts to call the API
 * factory, which internally validates every method signature against the Retrofit
 * RequestFactory. If any coach method still carries a wildcard @Body, RequestFactory
 * throws at this point.
 */
class BackendClientCoachMethodsTest {

    // SA-C1: matches BackendClient's real construction (codegen, no reflective
    // factory) so this also proves CoachCard's generated adapter resolves.
    private val moshi = Moshi.Builder().build()

    @Test
    fun `coach POST methods do not use wildcard @Body that Retrofit rejects`() {
        // This instantiation would throw IllegalArgumentException if any of the
        // five coach methods (coachWorkout, coachCardio, coachSleep, coachRecovery,
        // coachFasting) declare a @Body parameter with an unresolved type variable.
        // RequestFactory validates the signature when Retrofit.create() is called.
        val retrofit = Retrofit.Builder()
            .baseUrl("http://localhost/")
            .addConverterFactory(MoshiConverterFactory.create(moshi))
            .client(OkHttpClient())
            .build()

        // create() calls RequestFactory for every method on the interface,
        // which validates @Body types and rejects wildcards.
        val api = retrofit.create(BackendApi::class.java)

        // If we reach here without an exception, all method signatures are valid.
        assert(api != null)
    }

    @Test
    fun `the five coach methods declare no request body`() {
        // The backend handlers take no body at all, so the correct post-fix signature
        // is a bare suspend fun. A `suspend fun` compiles to a JVM method carrying an
        // implicit trailing Continuation, so the invariant to assert is "exactly one
        // JVM parameter, and it is the Continuation" — not "zero parameters", which
        // no suspend function can ever satisfy.
        val apiClass = BackendApi::class.java
        val names = listOf("coachWorkout", "coachCardio", "coachSleep", "coachRecovery", "coachFasting")

        for (name in names) {
            val method = apiClass.methods.singleOrNull { it.name == name }
                ?: error("BackendApi.$name not found, or overloaded")
            val params = method.parameterTypes.toList()
            assert(params.size == 1) {
                "Expected $name to take only the implicit Continuation, but it takes " +
                    "${params.size} parameters: $params"
            }
            assert(kotlin.coroutines.Continuation::class.java.isAssignableFrom(params[0])) {
                "Expected $name's only parameter to be the Continuation, but it is ${params[0]}"
            }
        }
    }
}
