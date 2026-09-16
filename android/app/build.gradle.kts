import com.android.build.api.artifact.SingleArtifact
import java.util.Properties

plugins {
    id("com.android.application")
}

// Signing material for release builds. The file sits at the repository root and
// is gitignored along with the keystore itself, so it is absent on a fresh clone
// and in CI — see the fallback in buildTypes below.
val keystorePropertiesFile = rootProject.file("../keystore.properties")
val keystoreProperties = Properties().apply {
    if (keystorePropertiesFile.exists()) {
        keystorePropertiesFile.inputStream().use { load(it) }
    }
}

android {
    namespace = "dev.bosco.deskpanel"
    compileSdk = 36

    defaultConfig {
        applicationId = "dev.bosco.deskpanel"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "1.0"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    // Points straight at web/, the single copy of the panel UI — never
    // duplicate it into assets/. See android/CLAUDE.md.
    sourceSets["main"].assets.srcDirs("../../web")

    // web/ is the whole layer, tests included, and packaging everything under
    // it shipped web/test/format.test.js into the APK: node:test code, inert
    // on the device but real bytes in a production artefact, and exactly what
    // T7.3's pre-public review exists to catch. The panel loads only
    // index.html, css/ and js/, so nothing else belongs in there.
    androidResources.ignoreAssetsPatterns += listOf("test", "*.test.js", ".gitkeep")

    // A stable release key from the very first install: Android refuses to
    // install an APK signed with a different key over an existing one, and the
    // only way out is an uninstall, which throws away the MIUI permissions and
    // device state T2.4 grants by hand. See docs/BUILD.md.
    if (keystorePropertiesFile.exists()) {
        signingConfigs.create("release") {
            // storeFile is resolved against the Gradle root (android/), so the
            // keystore sitting next to keystore.properties at the repository
            // root is `../desk-panel.keystore`. A path that only resolves from
            // this module is accepted too, so either spelling works.
            val storeFilePath = keystoreProperties.getProperty("storeFile")
            storeFile = rootProject.file(storeFilePath).takeIf { it.exists() }
                ?: file(storeFilePath)
            storePassword = keystoreProperties.getProperty("storePassword")
            keyAlias = keystoreProperties.getProperty("keyAlias")
            keyPassword = keystoreProperties.getProperty("keyPassword")
        }
    }

    buildTypes {
        getByName("release") {
            // No keystore.properties means a fresh clone or CI. Fall back to the
            // debug key so `assembleRelease` still produces an APK there instead
            // of failing the build; only the machine holding the keystore can
            // produce an installable-over-the-top release.
            signingConfig = signingConfigs.findByName("release")
                ?: signingConfigs.getByName("debug")
        }
    }
}

dependencies {
    // WebViewAssetLoader + WebViewClientCompat: they serve web/ over the
    // https://appassets.androidplatform.net/ origin, which is what makes the
    // panel a secure context. Without it the only option is file://, which
    // is not (T2.2).
    implementation("androidx.webkit:webkit:1.12.1")

    // WindowCompat / WindowInsetsControllerCompat: the supported way to hide the
    // system bars on every API level the panel runs on (T2.3). It arrives
    // transitively through webkit, but the immersive code is ours and so is the
    // dependency on it.
    implementation("androidx.core:core:1.13.1")

    // JVM unit tests only — PcState and friends are plain Java with no Android
    // imports precisely so `./gradlew test` covers them without a device.
    testImplementation("junit:junit:4.13.2")
}

// Every other task (`make apk`, T3.6, CI) expects the APK at the repository
// root's out/, not buried in app/build/outputs/apk/. The assemble<Variant>
// umbrella task is not registered yet when onVariants fires, so the hookup
// is deferred to afterEvaluate.
androidComponents {
    onVariants { variant ->
        val variantName = variant.name.replaceFirstChar { it.uppercaseChar() }
        val copyApk = tasks.register<Copy>("copy${variantName}ApkToOut") {
            from(variant.artifacts.get(SingleArtifact.APK))
            into(rootProject.file("../out"))
            // The release APK is the one a human installs and the server offers,
            // so it gets a product-shaped name. Debug keeps app-debug.apk, which
            // T3.6 and the server already look for. The regex is anchored so the
            // output-metadata.json sitting beside it is left alone.
            if (variant.name == "release") {
                rename("""^app-release\.apk$""", "desk-panel-release.apk")
            }
        }
        project.afterEvaluate {
            tasks.named("assemble$variantName") {
                finalizedBy(copyApk)
            }
        }
    }
}
