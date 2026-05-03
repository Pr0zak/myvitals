# myvitals — Android companion app

Reads Health Connect on the phone and POSTs batches to the backend.

## Open in Android Studio

This directory is a placeholder. Bootstrap with:

1. Android Studio → New Project → "Empty Activity"
2. Package: `app.myvitals` (or your own namespace)
3. Minimum SDK: 28 (Android 9)
4. Language: Kotlin, Build: Kotlin DSL

Then add to `app/build.gradle.kts`:

```kotlin
dependencies {
    implementation("androidx.health.connect:connect-client:1.1.0-alpha11")
    implementation("androidx.work:work-runtime-ktx:2.10.0")
    implementation("com.squareup.retrofit2:retrofit:2.11.0")
    implementation("com.squareup.retrofit2:converter-moshi:2.11.0")
    implementation("androidx.room:room-runtime:2.6.1")
    implementation("androidx.room:room-ktx:2.6.1")
    ksp("androidx.room:room-compiler:2.6.1")
    implementation("androidx.security:security-crypto:1.1.0-alpha06")
}
```

## Sketch

```
app.myvitals/
├── MainActivity.kt              // settings: backend URL, bearer token, "sync now"
├── health/
│   ├── HealthConnectClient.kt   // permission request + readers
│   └── DataMapper.kt            // Health Connect records → backend Batch JSON
├── sync/
│   ├── SyncWorker.kt            // WorkManager periodic job (15 min)
│   ├── BackendClient.kt         // Retrofit interface for POST /ingest/batch
│   └── OfflineBuffer.kt         // Room: queue failed posts, retry next sync
└── ui/
    └── SettingsScreen.kt
```

## Health Connect record types to read (v0)

- `HeartRateRecord`
- `HeartRateVariabilityRmssdRecord`
- `OxygenSaturationRecord`
- `SkinTemperatureRecord`
- `StepsRecord`
- `SleepSessionRecord` (and stages)
- `ExerciseSessionRecord`

## Auth

Single bearer token, stored in `EncryptedSharedPreferences`. Set via the settings screen on first launch.
