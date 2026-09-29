import com.android.build.api.artifact.SingleArtifact

plugins {
    id("com.android.application")
}

// ---------------------------------------------------------------------------
// .env — build-time local configuration (ADR 0013)
//
// Two values cannot be anything but build-time: the PC's LAN address, which the
// APK must be allowed to reach in cleartext, and the key the APK is signed with.
// Both live in a gitignored .env at the repository root, with .env.example
// committed beside it. Everything the owner might want to change at will —
// tickers, city, intervals — is runtime config in server/config.json instead,
// because a change to what the panel shows must never need a rebuild.
//
// NEVER add an API token here. A value Gradle reads is a value compiled into the
// APK, and an APK is a zip file.
//
// Parsed here rather than sourced by a shell wrapper on purpose: exporting this
// file would put the signing passwords into the environment of every process the
// build spawns.
// ---------------------------------------------------------------------------
val dotenvFile = rootProject.file("../.env")
val dotenv: Map<String, String> = buildMap {
    if (dotenvFile.exists()) {
        dotenvFile.readLines().forEach { raw ->
            val line = raw.trim()
            // Only a whole-line comment. There are no inline comments, so a
            // password may legitimately contain '#'.
            if (line.isEmpty() || line.startsWith("#")) return@forEach
            val eq = line.indexOf('=')
            if (eq <= 0) return@forEach
            val key = line.substring(0, eq).trim()
            var value = line.substring(eq + 1).trim()
            // One matching pair of surrounding quotes, since .env is
            // shell-shaped by convention and people quote out of habit.
            if (value.length >= 2 &&
                (value.first() == '"' || value.first() == '\'') &&
                value.last() == value.first()
            ) {
                value = value.substring(1, value.length - 1)
            }
            put(key, value)
        }
    }
}

fun dotenvValue(key: String): String? = dotenv[key]?.takeIf { it.isNotBlank() }

// ---------------------------------------------------------------------------
// Cleartext pinning
//
// res/xml/network_security_config.xml keeps the placeholder in git — T7.3's
// pre-public sweep requires that no real LAN address appears in committed
// non-doc source, and making that structurally true beats an operator
// remembering not to commit an edit. The substitution therefore happens on a
// generated copy of res/, which is what the APK packages; the tracked file is
// never rewritten.
// ---------------------------------------------------------------------------
val cleartextPlaceholder = "192.168.1.100"
// A comma-separated list since ADR 0016: one panel can follow more than one PC,
// and each listed address gets its own <domain> in the cleartext pin -- never
// a wider rule. One address is the old behaviour exactly.
val pcIps = dotenvValue("PC_IP")
    ?.split(",")
    ?.map { it.trim() }
    ?.filter { it.isNotEmpty() }
    ?.distinct()
    ?.takeIf { it.isNotEmpty() }
// Octets are range-checked, not just counted: \d{1,3} accepts 192.168.1.256,
// and the build would then bake an unreachable address into both the pin and
// pc_host while printing the reassuring line below. A panel that cannot reach
// its PC looks exactly like a panel whose PC is off, which is the ambiguity
// this whole mechanism exists to remove.
val ipv4Octet = "(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])"
pcIps?.forEach { ip ->
    if (!Regex("^" + ipv4Octet + "(\\." + ipv4Octet + "){3}$").matches(ip)) {
        throw GradleException("PC_IP in .env is not a list of IPv4 addresses: '$ip'")
    }
}
// Three at most, the same number as PcHosts.MAX_HOSTS: an offline cycle asks
// every host at up to 3 s each, inside a 10 s wake lock (PanelService).
if (pcIps != null && pcIps.size > 3) {
    throw GradleException("PC_IP in .env lists ${pcIps.size} addresses; at most 3 fit the dormant probe's wake lock")
}
val pcIp = pcIps?.joinToString(",")
val cleartextHosts = pcIps ?: listOf(cleartextPlaceholder)
val cleartextHost = cleartextHosts.joinToString(",")

// Printed at configuration time, so it appears on every build including one
// where every task is up to date. An APK silently built against the placeholder
// is indistinguishable from a network fault, and that ambiguity is the reason
// .env exists at all.
logger.lifecycle(
    if (pcIp != null) {
        "desk-panel: cleartext pinned to $cleartextHost (from .env)"
    } else {
        "desk-panel: cleartext pinned to $cleartextHost " +
            "(placeholder — no .env, the panel will not reach any PC)"
    }
)

val generatedResDir = layout.buildDirectory.dir("generated/netsec/res").get().asFile

// The generated tree replaces src/main/res as the module's only res source dir,
// rather than sitting alongside it: two source dirs carrying the same resource
// name is a duplicate-resource error, and there is no ordering that makes one
// win inside a single source set.
// Sync, not Copy: Copy never removes a destination file whose source went away,
// and this tree is the module's *only* res source dir. Renaming a resource under
// src/main/res would otherwise leave the old copy behind and ship both, which
// surfaces as a duplicate-resource error or a stale resource that only
// ./gradlew clean explains.
val generateNetsecRes = tasks.register<Sync>("generateNetsecRes") {
    description = "Copies res/, substituting the PC's LAN address from .env into the cleartext pin."
    from("src/main/res")
    into(generatedResDir)
    // Scoped to XML because filter() round-trips a file through a line-by-line
    // String transform. res/ is all text today; the first launcher icon, WebP
    // or font to land here would be packaged corrupted, with no build error and
    // nothing to see until it fails to decode on the device.
    filesMatching("**/*.xml") {
        // A <domain> line carrying the placeholder becomes one line per host,
        // so each PC is pinned by name and nothing else is (ADR 0016). Any
        // other line -- pc_host, a comment -- gets the comma-separated list.
        filter { line ->
            if (line.contains(cleartextPlaceholder) && line.trimStart().startsWith("<domain ")) {
                cleartextHosts.joinToString("\n") { line.replace(cleartextPlaceholder, it) }
            } else {
                line.replace(cleartextPlaceholder, cleartextHost)
            }
        }
    }
    inputs.property("cleartextHost", cleartextHost)
}

// ---------------------------------------------------------------------------
// Panel orientation
//
// Which way up the panel sits is a property of the stand, not of the software:
// it is decided once, when the phone is put on the desk, by which side the cable
// leaves from. That is the same class of value as PC_IP — local, physical,
// decided once — so it lives in .env for the same reason (ADR 0013).
//
// It became build-time config because it had to become *something*. The manifest
// said sensorLandscape, which accepts both landscape directions and picks by
// accelerometer, and that was harmless only while nothing ever relaunched the
// Activity. Real screen sleep (T4.4) relaunches it on every wake, and the phone
// is then lying nearly flat in a stand, where the sensor reading is ambiguous —
// so the panel came back upside down. Observed on the device, 2026-09-19.
//
// sensorLandscape stays the default, because a fresh clone with no .env should
// still behave the way it always did rather than guess at somebody's desk.
// ---------------------------------------------------------------------------
val orientationDefault = "sensorLandscape"
val allowedOrientations = setOf("sensorLandscape", "landscape", "reverseLandscape")
val panelOrientation = dotenvValue("PANEL_ORIENTATION") ?: orientationDefault
// Range-checked, not just non-empty, and for the same reason as PC_IP's octets: a
// typo here is not a build error by itself. android:screenOrientation would take
// the unknown string, aapt2 would reject it with a message about a manifest
// attribute rather than about .env, and the person reading it has no reason to
// suspect a file Gradle parsed.
if (panelOrientation !in allowedOrientations) {
    throw GradleException(
        "PANEL_ORIENTATION in .env is '$panelOrientation'; expected one of " +
            allowedOrientations.joinToString(", ") + "."
    )
}

logger.lifecycle(
    if (dotenvValue("PANEL_ORIENTATION") != null) {
        "desk-panel: panel orientation $panelOrientation (from .env)"
    } else {
        "desk-panel: panel orientation $panelOrientation (default — the sensor picks, " +
            "and may pick differently after a wake)"
    }
)

// ---------------------------------------------------------------------------
// Release signing
//
// Absorbed from keystore.properties into .env (ADR 0013): two build-time local
// files was one too many. Behaviour is T7.1's, unchanged — all four values
// present means release signing, any of them missing means fall back to debug
// so a fresh clone and CI still build.
// ---------------------------------------------------------------------------
val keystoreFilePath = dotenvValue("KEYSTORE_FILE")
val keystorePassword = dotenvValue("KEYSTORE_PASSWORD")
val keystoreAlias = dotenvValue("KEY_ALIAS")
val keystoreKeyPassword = dotenvValue("KEY_PASSWORD")

// storeFile is resolved against the Gradle root (android/), so the keystore
// sitting next to .env at the repository root is `../desk-panel.keystore`. A
// path that only resolves from this module is accepted too, so either spelling
// works.
// A path that is set but resolves to nothing is a typo, and a typo must not
// fall back to the debug key: the APK builds, installs on a clean device, and
// then refuses to install over the real one — INSTALL_FAILED_UPDATE_INCOMPATIBLE,
// whose only cure is an uninstall that discards the MIUI grants T2.4 spent a
// session collecting. Same argument as PC_IP above: absent is a documented
// fallback, wrong is not.
val resolvedKeystore = keystoreFilePath?.let { path ->
    (rootProject.file(path).takeIf { it.exists() } ?: file(path).takeIf { it.exists() })
        ?: throw GradleException(
            "KEYSTORE_FILE in .env points at no file: '$path'. Tried " +
                "${rootProject.file(path)} and ${file(path)}. Leave it empty to fall back " +
                "to the debug key deliberately."
        )
}
val hasReleaseSigning = resolvedKeystore != null &&
    keystorePassword != null && keystoreAlias != null && keystoreKeyPassword != null

// Same argument as the cleartext line: a release APK that silently fell back to
// the debug key installs fine and then refuses to install over the real one.
logger.lifecycle(
    if (hasReleaseSigning) {
        "desk-panel: release signing (from .env)"
    } else {
        "desk-panel: debug signing (no usable release key in .env — not installable " +
            "over a release build)"
    }
)

android {
    namespace = "dev.bosco.deskpanel"
    compileSdk = 36

    defaultConfig {
        applicationId = "dev.bosco.deskpanel"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "1.0"

        // Substituted into android:screenOrientation in the manifest. A
        // placeholder rather than the res/ substitution PC_IP rides, because
        // screenOrientation is a manifest attribute and takes an enum, not a
        // string resource.
        manifestPlaceholders["panelOrientation"] = panelOrientation
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    // Points straight at web/, the single copy of the panel UI — never
    // duplicate it into assets/. See android/CLAUDE.md.
    sourceSets["main"].assets.srcDirs("../../web")

    // res/ is read from the generated copy above, never from src/main/res
    // directly, so the address baked into the APK can differ from the one in git.
    sourceSets["main"].res.setSrcDirs(listOf(generatedResDir))

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
    if (hasReleaseSigning) {
        signingConfigs.create("release") {
            storeFile = resolvedKeystore
            storePassword = keystorePassword
            keyAlias = keystoreAlias
            keyPassword = keystoreKeyPassword
        }
    }

    buildTypes {
        getByName("release") {
            // No signing values in .env means a fresh clone or CI. Fall back to
            // the debug key so `assembleRelease` still produces an APK there
            // instead of failing the build; only the machine holding the
            // keystore can produce an installable-over-the-top release.
            signingConfig = signingConfigs.findByName("release")
                ?: signingConfigs.getByName("debug")
        }
    }
}

// Resource merging has to see the substituted copy, and preBuild is the one
// task every variant's pipeline runs first.
tasks.named("preBuild") {
    dependsOn(generateNetsecRes)
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

    // org.json is part of Android and is NOT packaged into the APK; what
    // android.jar hands a JVM unit test is a stub whose every method throws.
    // DataPayload builds the panel's payload through it — which is what keeps
    // a ticker name from being able to break out of an evaluateJavascript call
    // — so without this the one class worth testing here could only be tested
    // on a device. Test classpath only: `implementation` would ship a second
    // copy of a library the platform already has.
    testImplementation("org.json:json:20240303")
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
