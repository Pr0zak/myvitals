import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("com.google.devtools.ksp")
}

// Read signing config from android/keystore.properties (gitignored).
// CI provides values via env vars instead — see ANDROID_* secrets in releasing.md.
val keystoreProps = Properties().apply {
    val f = rootProject.file("keystore.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

fun keystoreOrEnv(key: String, env: String): String? =
    keystoreProps.getProperty(key) ?: System.getenv(env)

android {
    namespace = "app.myvitals"
    compileSdk = 35

    defaultConfig {
        applicationId = "app.myvitals"
        minSdk = 28
        targetSdk = 35
        // CI overrides via env vars so the git tag is the single source of truth.
        versionCode = (System.getenv("BUILD_VERSION_CODE") ?: "1").toInt()
        versionName = System.getenv("BUILD_VERSION_NAME") ?: "0.1.0"

        // Update checker hits this repo's GitHub Releases API.
        buildConfigField("String", "GITHUB_REPO", "\"Pr0zak/myvitals\"")
    }

    signingConfigs {
        create("release") {
            val storePath = keystoreOrEnv("storeFile", "ANDROID_KEYSTORE_PATH")
            val storePass = keystoreOrEnv("storePassword", "ANDROID_KEYSTORE_PASSWORD")
            val alias = keystoreOrEnv("keyAlias", "ANDROID_KEY_ALIAS")
            val keyPass = keystoreOrEnv("keyPassword", "ANDROID_KEY_PASSWORD")

            if (storePath != null && storePass != null && alias != null && keyPass != null) {
                storeFile = file(storePath)
                storePassword = storePass
                keyAlias = alias
                keyPassword = keyPass
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            // Only attach the signing config if it was actually populated;
            // otherwise gradle errors instead of silently producing an unsigned APK.
            signingConfigs.findByName("release")
                ?.takeIf { it.storeFile != null }
                ?.let { signingConfig = it }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    sourceSets {
        getByName("main") {
            java.srcDirs("src/main/kotlin")
        }
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.12.01")
    implementation(composeBom)
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.navigation:navigation-compose:2.8.5")
    implementation("io.coil-kt:coil-compose:2.7.0")

    implementation("androidx.health.connect:connect-client:1.1.0-alpha11")
    implementation("androidx.work:work-runtime-ktx:2.10.0")

    implementation("com.squareup.retrofit2:retrofit:2.11.0")
    implementation("com.squareup.retrofit2:converter-moshi:2.11.0")
    implementation("com.squareup.moshi:moshi-kotlin:1.15.1")
    implementation("com.squareup.moshi:moshi-adapters:1.15.1")
    implementation("com.squareup.okhttp3:logging-interceptor:4.12.0")

    implementation("androidx.room:room-runtime:2.6.1")
    implementation("androidx.room:room-ktx:2.6.1")
    ksp("androidx.room:room-compiler:2.6.1")

    implementation("androidx.security:security-crypto:1.1.0-alpha06")
    implementation("androidx.datastore:datastore-preferences:1.1.1")
    implementation("androidx.compose.runtime:runtime-livedata")

    implementation("com.jakewharton.timber:timber:5.0.1")

    debugImplementation("androidx.compose.ui:ui-tooling")
}
