import com.android.build.api.artifact.SingleArtifact

plugins {
    id("com.android.application")
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
}

dependencies {
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
        }
        project.afterEvaluate {
            tasks.named("assemble$variantName") {
                finalizedBy(copyApk)
            }
        }
    }
}
