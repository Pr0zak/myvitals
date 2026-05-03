package app.myvitals.sync

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory
import retrofit2.http.Body
import retrofit2.http.POST
import java.util.concurrent.TimeUnit

interface BackendApi {
    @POST("ingest/batch")
    suspend fun ingestBatch(@Body batch: IngestBatch): IngestResponse
}

object BackendClient {
    fun create(baseUrl: String, bearerToken: String): BackendApi {
        val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()

        val auth = Interceptor { chain ->
            val req = chain.request().newBuilder()
                .header("Authorization", "Bearer $bearerToken")
                .build()
            chain.proceed(req)
        }

        val http = OkHttpClient.Builder()
            .addInterceptor(auth)
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .build()

        return Retrofit.Builder()
            .baseUrl(if (baseUrl.endsWith("/")) baseUrl else "$baseUrl/")
            .client(http)
            .addConverterFactory(MoshiConverterFactory.create(moshi))
            .build()
            .create(BackendApi::class.java)
    }
}
