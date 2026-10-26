import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("com.chaquo.python")
}

// Версия приложения берётся из единственного источника — ../src/version.py
val appVersion: String = Regex("""__version__\s*=\s*"([^"]+)"""")
    .find(rootProject.file("../src/version.py").readText())!!.groupValues[1]

// Ядро (без интерфейса для ПК) копируется в build/pysrc, чтобы в APK не попал customtkinter-код
val syncPythonCore by tasks.registering(Sync::class) {
    from(rootProject.file("../src")) {
        include("__init__.py", "version.py", "config.py", "core/**", "utils/**")
        exclude("**/__pycache__/**")
    }
    into(layout.buildDirectory.dir("pysrc/src"))
}

android {
    namespace = "app.mediaharvester"
    compileSdk = 35

    defaultConfig {
        applicationId = "app.mediaharvester"
        minSdk = 29
        targetSdk = 35
        versionCode = 1
        versionName = appVersion
    }

    // Отдельный APK под каждую архитектуру (Chaquopy требует задавать их через flavors): телефон ставит arm64,
    // эмулятор на ПК — x64. Общий APK не собирается: он вдвое больше, так как везёт Python и ffmpeg для обеих.
    flavorDimensions += "abi"
    productFlavors {
        create("arm64") {
            dimension = "abi"
            ndk { abiFilters += "arm64-v8a" }
        }
        create("x64") {
            dimension = "abi"
            ndk { abiFilters += "x86_64" }
        }
    }

    val keystoreProps = Properties().apply {
        val f = rootProject.file("keystore.properties")
        if (f.exists()) f.inputStream().use { load(it) }
    }
    if (keystoreProps.isNotEmpty()) {
        signingConfigs.create("release") {
            storeFile = rootProject.file(keystoreProps.getProperty("storeFile"))
            storePassword = keystoreProps.getProperty("storePassword")
            keyAlias = keystoreProps.getProperty("keyAlias")
            keyPassword = keystoreProps.getProperty("keyPassword")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfigs.findByName("release")?.let { signingConfig = it }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { compose = true }
    // ffmpeg запускается как исполняемый файл из папки нативных библиотек: их нужно распаковывать на диск
    packaging {
        jniLibs {
            useLegacyPackaging = true
            // libc++ для ffmpeg берётся из пакета библиотек youtubedl-android (см. Ffmpeg.kt)
            excludes += "**/libc++_shared.so"
        }
    }

}

chaquopy {
    sourceSets {
        getByName("main") {
            srcDir(files(layout.buildDirectory.dir("pysrc")).builtBy(syncPythonCore))
        }
    }
    defaultConfig {
        version = "3.13"
        // Python для самой сборки (не для телефона); 3.14+ Chaquopy пока не поддерживает
        buildPython("py", "-3.13")
        pip {
            install("yt-dlp")
            install("gallery-dl")
            install("requests")
            install("certifi")
            install("mutagen")
            install("vk_api")
        }
    }
}

tasks.named("preBuild") { dependsOn(syncPythonCore) }

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.10.01")
    implementation(composeBom)
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material:material-icons-core")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("org.apache.commons:commons-compress:1.27.1")
    // Только бинарники ffmpeg/ffprobe для каждой архитектуры; код библиотеки не используется
    implementation("io.github.junkfood02.youtubedl-android:ffmpeg:0.18.1") { isTransitive = false }
    // Общие библиотеки (libc++, expat и др.), без которых ffmpeg не запускается; внутри также QuickJS
    implementation("io.github.junkfood02.youtubedl-android:library:0.18.1") { isTransitive = false }
    debugImplementation("androidx.compose.ui:ui-tooling")
}
