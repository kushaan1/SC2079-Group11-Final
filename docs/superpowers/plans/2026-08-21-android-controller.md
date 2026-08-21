# Android Remote Controller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Android tablet app that controls the SC2079 robot over Bluetooth SPP and satisfies checklist items C.1–C.10.

**Architecture:** Single Gradle module, Jetpack Compose UI. Boundaries are packages, not modules. `protocol/` and `arena/` are pure Kotlin with zero `android.*` imports so they are JVM-unit-testable; `connection/` owns an Application-scoped repository holding the socket behind a `Transport` interface, with a `FakeTransport` twin that makes the reconnect logic testable without hardware.

**Tech Stack:** Kotlin 2.x · Jetpack Compose (BOM 2026.08.00) · Material 3 stable · Coroutines/Flow · DataStore · JUnit4 + kotlinx-coroutines-test

**Spec:** `docs/superpowers/specs/2026-08-21-android-controller-design.md`

## Global Constraints

- Package: `com.mdp.grp11`. Project root: `android/` (new directory; never edit `SC2079_Example/`).
- `minSdk 31`, `targetSdk 36`, `compileSdk 36`. AGP **9.1.1** floor, Compose BOM **2026.08.00**, Material 3 **stable only** — never the `1.5.0-alpha` Expressive line.
- Target device: Samsung Galaxy A7 Lite, 8.7", 1340×800, landscape only.
- Arena is **20×20 cells**, origin `(0,0)` bottom-left, **y increases upward**. Max **8** obstacles. Start zone is cells `x<4 && y<4`.
- Every physical constant lives in `config/Config.kt`. Never inline one (AGENTS.md §9.2 rule 1).
- `decode()` must be **total** — it may never throw.
- Target IDs are **never range-rejected**. The checklist's own example uses ID 4, outside the 11–40 pool.
- Outbound obstacle messages fire on **finger-lift only**, and only when the position actually changed.
- Library versions below are current-stable at time of writing; resolve to latest stable compatible with the AGP/BOM floors during Task 1, and pin whatever you resolve in the version catalog.

---

## File Structure

| File | Responsibility |
|---|---|
| `android/gradle/libs.versions.toml` | Version catalog — single source of dependency versions |
| `android/app/src/main/AndroidManifest.xml` | Permissions, landscape lock, single activity |
| `.../config/Config.kt` | All physical + protocol constants |
| `.../protocol/Face.kt` | `Face` enum + parsing |
| `.../protocol/Messages.kt` | `Inbound` / `Outbound` sealed hierarchies |
| `.../protocol/Decoder.kt` | `decode(line): Inbound` — total |
| `.../protocol/Encoder.kt` | `encode(msg): String` |
| `.../arena/Grid.kt` | Cell↔pixel maths, y-flip, radius hit-testing |
| `.../arena/Arena.kt` | `Cell`, `Target`, `Obstacle`, `RobotPose`, `Arena` + operations |
| `.../transport/Transport.kt` | `Transport` interface, `Target` sealed type |
| `.../transport/LineFramer.kt` | Byte-stream → complete lines |
| `.../transport/FakeTransport.kt` | In-memory twin for tests and offline dev |
| `.../transport/BluetoothSppTransport.kt` | Real RFCOMM, client + server |
| `.../connection/ConnectionState.kt` | Connection state hierarchy |
| `.../connection/ConnectionRepository.kt` | Owns transport, reconnect loop, message flows |
| `.../session/RunTimer.kt` | Run stopwatch |
| `.../session/SessionLog.kt` | Timestamped TX/RX log + export |
| `.../arena/ArenaStore.kt` | DataStore persistence of arena state |
| `.../ui/theme/*.kt` | Colour, type, shape tokens |
| `.../ui/ArenaViewModel.kt` | Screen state, wires repository ⇄ arena ⇄ UI |
| `.../ui/ArenaCanvas.kt` | Grid, axis labels, obstacles, robot, gestures |
| `.../ui/ControlPad.kt` | Six-way movement + STOP |
| `.../ui/FaceCompass.kt` | Face annotation control |
| `.../ui/StatusPanel.kt` | Filtered status (C.4) |
| `.../ui/BtLogPanel.kt` | Raw TX/RX log (C.1) |
| `.../ui/DevicePickerSheet.kt` | Scan/select/connect (C.2) |
| `.../ui/MainScreen.kt` | Layout composition |
| `AMDTOOL/scripts/mdp_grp11.cs` | AMD send script emitting our protocol |
| `docs/checklist-demos.md` | One demo script per C.1–C.10 |

---

## Task 1: Project scaffold

**Files:**
- Create: `android/settings.gradle.kts`, `android/build.gradle.kts`, `android/gradle.properties`
- Create: `android/gradle/libs.versions.toml`
- Create: `android/app/build.gradle.kts`
- Create: `android/app/src/main/AndroidManifest.xml`
- Create: `android/app/src/main/java/com/mdp/grp11/MainActivity.kt`

**Interfaces:**
- Consumes: nothing
- Produces: a buildable Compose app; the `com.mdp.grp11` package root; `libs.*` catalog accessors

- [ ] **Step 1: Create the version catalog**

`android/gradle/libs.versions.toml`:

```toml
[versions]
agp = "9.1.1"
kotlin = "2.1.0"
composeBom = "2026.08.00"
coreKtx = "1.15.0"
lifecycle = "2.8.7"
activityCompose = "1.9.3"
coroutines = "1.9.0"
datastore = "1.1.1"
junit = "4.13.2"

[libraries]
androidx-core-ktx = { group = "androidx.core", name = "core-ktx", version.ref = "coreKtx" }
androidx-lifecycle-runtime-ktx = { group = "androidx.lifecycle", name = "lifecycle-runtime-ktx", version.ref = "lifecycle" }
androidx-lifecycle-viewmodel-compose = { group = "androidx.lifecycle", name = "lifecycle-viewmodel-compose", version.ref = "lifecycle" }
androidx-activity-compose = { group = "androidx.activity", name = "activity-compose", version.ref = "activityCompose" }
androidx-compose-bom = { group = "androidx.compose", name = "compose-bom", version.ref = "composeBom" }
androidx-compose-ui = { group = "androidx.compose.ui", name = "ui" }
androidx-compose-ui-graphics = { group = "androidx.compose.ui", name = "ui-graphics" }
androidx-compose-ui-tooling-preview = { group = "androidx.compose.ui", name = "ui-tooling-preview" }
androidx-compose-ui-tooling = { group = "androidx.compose.ui", name = "ui-tooling" }
androidx-compose-material3 = { group = "androidx.compose.material3", name = "material3" }
androidx-datastore-preferences = { group = "androidx.datastore", name = "datastore-preferences", version.ref = "datastore" }
kotlinx-coroutines-core = { group = "org.jetbrains.kotlinx", name = "kotlinx-coroutines-core", version.ref = "coroutines" }
kotlinx-coroutines-test = { group = "org.jetbrains.kotlinx", name = "kotlinx-coroutines-test", version.ref = "coroutines" }
junit = { group = "junit", name = "junit", version.ref = "junit" }

[plugins]
android-application = { id = "com.android.application", version.ref = "agp" }
kotlin-android = { id = "org.jetbrains.kotlin.android", version.ref = "kotlin" }
kotlin-compose = { id = "org.jetbrains.kotlin.plugin.compose", version.ref = "kotlin" }
```

- [ ] **Step 2: Create the Gradle build files**

`android/settings.gradle.kts`:

```kotlin
pluginManagement {
    repositories { google(); mavenCentral(); gradlePluginPortal() }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories { google(); mavenCentral() }
}
rootProject.name = "mdp-grp11"
include(":app")
```

`android/build.gradle.kts`:

```kotlin
plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.android) apply false
    alias(libs.plugins.kotlin.compose) apply false
}
```

`android/gradle.properties`:

```properties
org.gradle.jvmargs=-Xmx2048m
android.useAndroidX=true
kotlin.code.style=official
```

`android/app/build.gradle.kts`:

```kotlin
plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

android {
    namespace = "com.mdp.grp11"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.mdp.grp11"
        minSdk = 31
        targetSdk = 36
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlin { jvmToolchain(17) }
    buildFeatures { compose = true }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.datastore.preferences)
    implementation(libs.kotlinx.coroutines.core)
    debugImplementation(libs.androidx.compose.ui.tooling)
    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)
}
```

- [ ] **Step 3: Create the manifest with all Bluetooth permissions**

`android/app/src/main/AndroidManifest.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">

    <uses-permission android:name="android.permission.BLUETOOTH_CONNECT" />
    <uses-permission android:name="android.permission.BLUETOOTH_SCAN"
        android:usesPermissionFlags="neverForLocation" />
    <uses-permission android:name="android.permission.BLUETOOTH_ADVERTISE" />

    <uses-feature android:name="android.hardware.bluetooth" android:required="true" />

    <application
        android:allowBackup="true"
        android:label="MDP Grp 11"
        android:supportsRtl="true"
        android:theme="@android:style/Theme.Material.Light.NoActionBar">
        <activity
            android:name=".MainActivity"
            android:exported="true"
            android:screenOrientation="landscape"
            android:configChanges="orientation|screenSize|keyboardHidden">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
```

`android/app/src/main/java/com/mdp/grp11/MainActivity.kt`:

```kotlin
package com.mdp.grp11

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material3.Text

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { Text("MDP Grp 11") }
    }
}
```

- [ ] **Step 4: Verify it builds**

Run: `cd android && ./gradlew :app:assembleDebug`
Expected: `BUILD SUCCESSFUL`. If a dependency version fails to resolve, bump it to current stable in `libs.versions.toml` and re-run — do not lower the AGP or BOM floors.

- [ ] **Step 5: Commit**

```bash
git add android/
git commit -m "feat(android): scaffold Compose project with Bluetooth permissions"
```

---

## Task 2: Config constants

**Files:**
- Create: `android/app/src/main/java/com/mdp/grp11/config/Config.kt`

**Interfaces:**
- Consumes: nothing
- Produces: `Config.CELLS: Int`, `Config.MAX_OBSTACLES: Int`, `Config.START_ZONE_CELLS: Int`, `Config.SPP_UUID: UUID`, `Config.BACKOFF_MS: List<Long>`, `Config.MoveTokens` (data class with `forward`, `reverse`, `rotateLeft`, `rotateRight`, `strafeLeft`, `strafeRight`, `stop`), `Config.moveTokens: MoveTokens`

- [ ] **Step 1: Write the file**

```kotlin
package com.mdp.grp11.config

import java.util.UUID

object Config {
    const val CELLS = 20
    const val MAX_OBSTACLES = 8
    const val START_ZONE_CELLS = 4

    /** Bluetooth Serial Port Profile. */
    val SPP_UUID: UUID = UUID.fromString("00001101-0000-1000-8000-00805F9B34FB")

    /** Client reconnect backoff. Repeats the last value indefinitely. */
    val BACKOFF_MS = listOf(1_000L, 2_000L, 4_000L, 5_000L)

    /**
     * Movement tokens. These must match the AMD tool's Settings -> Received
     * Commands, and later whatever the STM firmware expects.
     */
    data class MoveTokens(
        val forward: String = "f",
        val reverse: String = "r",
        val rotateLeft: String = "tl",
        val rotateRight: String = "tr",
        val strafeLeft: String = "sl",
        val strafeRight: String = "sr",
        val stop: String = "s",
    )

    val moveTokens = MoveTokens()
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd android && ./gradlew :app:compileDebugKotlin`
Expected: `BUILD SUCCESSFUL`

- [ ] **Step 3: Commit**

```bash
git add android/app/src/main/java/com/mdp/grp11/config/Config.kt
git commit -m "feat(android): add config constants"
```

---

## Task 3: Face and Grid maths

**Files:**
- Create: `android/app/src/main/java/com/mdp/grp11/protocol/Face.kt`
- Create: `android/app/src/main/java/com/mdp/grp11/arena/Grid.kt`
- Test: `android/app/src/test/java/com/mdp/grp11/arena/GridTest.kt`

**Interfaces:**
- Consumes: `Config.CELLS`
- Produces: `enum class Face { N, E, S, W }` with `Face.parse(s: String): Face?`; `Grid.toCanvasRow(cellY: Int): Int`; `Grid.cellAt(px: Float, py: Float, gridPx: Float): Pair<Int, Int>`; `Grid.centreOf(cellX: Int, cellY: Int, gridPx: Float): Pair<Float, Float>`

- [ ] **Step 1: Write the failing tests**

`android/app/src/test/java/com/mdp/grp11/arena/GridTest.kt`:

```kotlin
package com.mdp.grp11.arena

import com.mdp.grp11.protocol.Face
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class GridTest {

    @Test fun `face parses case insensitively`() {
        assertEquals(Face.N, Face.parse("N"))
        assertEquals(Face.E, Face.parse("e"))
        assertEquals(Face.W, Face.parse(" W "))
        assertNull(Face.parse("NONE"))
        assertNull(Face.parse("Q"))
    }

    @Test fun `y flip maps bottom row to last canvas row`() {
        assertEquals(19, Grid.toCanvasRow(0))
        assertEquals(0, Grid.toCanvasRow(19))
        assertEquals(12, Grid.toCanvasRow(7))
    }

    @Test fun `y flip is its own inverse`() {
        for (y in 0 until 20) assertEquals(y, Grid.toCanvasRow(Grid.toCanvasRow(y)))
    }

    @Test fun `cellAt resolves corners`() {
        val g = 660f
        assertEquals(0 to 19, Grid.cellAt(1f, 1f, g))        // top-left pixel
        assertEquals(19 to 0, Grid.cellAt(659f, 659f, g))    // bottom-right pixel
        assertEquals(0 to 0, Grid.cellAt(1f, 659f, g))       // bottom-left pixel
    }

    @Test fun `cellAt clamps out of range input`() {
        val g = 660f
        assertEquals(0 to 19, Grid.cellAt(-50f, -50f, g))
        assertEquals(19 to 0, Grid.cellAt(9999f, 9999f, g))
    }

    @Test fun `centreOf returns the middle of the cell in canvas pixels`() {
        val g = 660f  // 33px cells
        assertEquals(16.5f to 643.5f, Grid.centreOf(0, 0, g))
        assertEquals(643.5f to 16.5f, Grid.centreOf(19, 19, g))
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests "*GridTest*"`
Expected: FAIL — `Unresolved reference: Face` / `Unresolved reference: Grid`

- [ ] **Step 3: Write the implementation**

`android/app/src/main/java/com/mdp/grp11/protocol/Face.kt`:

```kotlin
package com.mdp.grp11.protocol

enum class Face {
    N, E, S, W;

    companion object {
        /** Returns null for anything that is not one of the four faces. */
        fun parse(s: String): Face? = when (s.trim().uppercase()) {
            "N" -> N
            "E" -> E
            "S" -> S
            "W" -> W
            else -> null
        }
    }
}
```

`android/app/src/main/java/com/mdp/grp11/arena/Grid.kt`:

```kotlin
package com.mdp.grp11.arena

import com.mdp.grp11.config.Config

/**
 * The single place cell coordinates meet pixels.
 *
 * Arena y counts UPWARD from (0,0) at bottom-left. Android canvas y counts
 * DOWNWARD from the top. Every conversion between the two lives here; scatter
 * it and the grid ends up mirrored.
 */
object Grid {

    /** Arena row -> canvas row (and back; the mapping is its own inverse). */
    fun toCanvasRow(cellY: Int): Int = Config.CELLS - 1 - cellY

    /** Canvas pixel -> arena cell, clamped to the grid. */
    fun cellAt(px: Float, py: Float, gridPx: Float): Pair<Int, Int> {
        val cell = gridPx / Config.CELLS
        val x = (px / cell).toInt().coerceIn(0, Config.CELLS - 1)
        val row = (py / cell).toInt().coerceIn(0, Config.CELLS - 1)
        return x to toCanvasRow(row)
    }

    /** Arena cell -> centre of that cell in canvas pixels. */
    fun centreOf(cellX: Int, cellY: Int, gridPx: Float): Pair<Float, Float> {
        val cell = gridPx / Config.CELLS
        val cx = cellX * cell + cell / 2f
        val cy = toCanvasRow(cellY) * cell + cell / 2f
        return cx to cy
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests "*GridTest*"`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add android/app/src/main/java/com/mdp/grp11/protocol/Face.kt \
        android/app/src/main/java/com/mdp/grp11/arena/Grid.kt \
        android/app/src/test/java/com/mdp/grp11/arena/GridTest.kt
git commit -m "feat(android): add Face and Grid coordinate maths with tests"
```

---

## Task 4: Arena model

**Files:**
- Create: `android/app/src/main/java/com/mdp/grp11/arena/Arena.kt`
- Test: `android/app/src/test/java/com/mdp/grp11/arena/ArenaTest.kt`

**Interfaces:**
- Consumes: `Face`, `Config.CELLS`, `Config.MAX_OBSTACLES`, `Config.START_ZONE_CELLS`
- Produces: `data class Cell(val x: Int, val y: Int)`; `data class Target(val id: Int, val face: Face?)`; `data class Obstacle(val id: Int, val cell: Cell, val imageFace: Face?, val target: Target?)`; `data class RobotPose(val cell: Cell, val heading: Face)`; `data class Arena(val obstacles: List<Obstacle>, val robot: RobotPose?)` with methods `place(cell): Pair<Arena, Obstacle?>`, `move(id, cell): Arena`, `remove(id): Arena`, `setFace(id, face): Arena`, `applyTarget(id, targetId, face): Arena`, `applyPose(x, y, heading): Arena`, `canOccupy(cell, ignoreId): Boolean`, `nextFreeId(): Int?`, `obstacle(id): Obstacle?`

- [ ] **Step 1: Write the failing tests**

`android/app/src/test/java/com/mdp/grp11/arena/ArenaTest.kt`:

```kotlin
package com.mdp.grp11.arena

import com.mdp.grp11.protocol.Face
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ArenaTest {

    private val empty = Arena()

    @Test fun `place assigns ids from one upward`() {
        val (a1, o1) = empty.place(Cell(10, 10))
        val (a2, o2) = a1.place(Cell(11, 11))
        assertEquals(1, o1!!.id)
        assertEquals(2, o2!!.id)
        assertEquals(2, a2.obstacles.size)
    }

    @Test fun `removed id returns to the pool and is reused`() {
        var a = empty
        repeat(3) { i -> a = a.place(Cell(10 + i, 10)).first }
        a = a.remove(2)
        val (a2, o) = a.place(Cell(15, 15))
        assertEquals(2, o!!.id)
        assertEquals(3, a2.obstacles.size)
    }

    @Test fun `place is refused when the pool is exhausted`() {
        var a = empty
        repeat(8) { i -> a = a.place(Cell(10, i + 5)).first }
        val (after, o) = a.place(Cell(19, 19))
        assertNull(o)
        assertEquals(8, after.obstacles.size)
    }

    @Test fun `place is refused inside the start zone`() {
        val (after, o) = empty.place(Cell(3, 3))
        assertNull(o)
        assertTrue(after.obstacles.isEmpty())
    }

    @Test fun `place is allowed just outside the start zone`() {
        assertNotNull(empty.place(Cell(4, 0)).second)
        assertNotNull(empty.place(Cell(0, 4)).second)
    }

    @Test fun `place is refused on an occupied cell`() {
        val a = empty.place(Cell(10, 10)).first
        assertNull(a.place(Cell(10, 10)).second)
    }

    @Test fun `move refuses an occupied cell but allows a no-op onto itself`() {
        var a = empty.place(Cell(10, 10)).first
        a = a.place(Cell(11, 11)).first
        assertEquals(Cell(10, 10), a.move(1, Cell(11, 11)).obstacle(1)!!.cell)
        assertEquals(Cell(10, 10), a.move(1, Cell(10, 10)).obstacle(1)!!.cell)
        assertEquals(Cell(12, 12), a.move(1, Cell(12, 12)).obstacle(1)!!.cell)
    }

    @Test fun `move refuses the start zone`() {
        val a = empty.place(Cell(10, 10)).first
        assertEquals(Cell(10, 10), a.move(1, Cell(0, 0)).obstacle(1)!!.cell)
    }

    @Test fun `annotated face and reported target face are independent`() {
        var a = empty.place(Cell(10, 10)).first
        a = a.setFace(1, Face.N)
        a = a.applyTarget(1, 11, Face.E)
        val o = a.obstacle(1)!!
        assertEquals(Face.N, o.imageFace)
        assertEquals(Face.E, o.target!!.face)
        assertEquals(11, o.target!!.id)
    }

    @Test fun `applyTarget accepts an id outside the image pool`() {
        val a = empty.place(Cell(10, 10)).first.applyTarget(1, 4, null)
        assertEquals(4, a.obstacle(1)!!.target!!.id)
    }

    @Test fun `applyTarget for an unknown obstacle is ignored`() {
        val a = empty.place(Cell(10, 10)).first
        assertEquals(a, a.applyTarget(7, 11, null))
    }

    @Test fun `applyPose rejects out of range coordinates`() {
        val a = empty.applyPose(3, 4, Face.E)
        assertEquals(RobotPose(Cell(3, 4), Face.E), a.robot)
        assertEquals(a, a.applyPose(20, 4, Face.N))
        assertEquals(a, a.applyPose(-1, 4, Face.N))
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests "*ArenaTest*"`
Expected: FAIL — `Unresolved reference: Arena`

- [ ] **Step 3: Write the implementation**

`android/app/src/main/java/com/mdp/grp11/arena/Arena.kt`:

```kotlin
package com.mdp.grp11.arena

import com.mdp.grp11.config.Config
import com.mdp.grp11.protocol.Face

data class Cell(val x: Int, val y: Int)

/** What the ROBOT reported (C.9). Distinct from Obstacle.imageFace. */
data class Target(val id: Int, val face: Face?)

data class Obstacle(
    val id: Int,
    val cell: Cell,
    /** What WE annotated (C.7), outbound. */
    val imageFace: Face? = null,
    /** What the ROBOT reported (C.9), inbound. */
    val target: Target? = null,
)

data class RobotPose(val cell: Cell, val heading: Face)

data class Arena(
    val obstacles: List<Obstacle> = emptyList(),
    val robot: RobotPose? = null,
) {

    fun obstacle(id: Int): Obstacle? = obstacles.firstOrNull { it.id == id }

    /** Lowest unused id in 1..MAX, or null when the pool is exhausted. */
    fun nextFreeId(): Int? =
        (1..Config.MAX_OBSTACLES).firstOrNull { id -> obstacles.none { it.id == id } }

    fun canOccupy(cell: Cell, ignoreId: Int?): Boolean {
        if (!inBounds(cell)) return false
        if (cell.x < Config.START_ZONE_CELLS && cell.y < Config.START_ZONE_CELLS) return false
        return obstacles.none { it.id != ignoreId && it.cell == cell }
    }

    /** Returns the new arena and the placed obstacle, or (this, null) if refused. */
    fun place(cell: Cell): Pair<Arena, Obstacle?> {
        if (!canOccupy(cell, null)) return this to null
        val id = nextFreeId() ?: return this to null
        val o = Obstacle(id = id, cell = cell)
        return copy(obstacles = obstacles + o) to o
    }

    fun move(id: Int, cell: Cell): Arena {
        val existing = obstacle(id) ?: return this
        if (existing.cell == cell) return this
        if (!canOccupy(cell, id)) return this
        return copy(obstacles = obstacles.map { if (it.id == id) it.copy(cell = cell) else it })
    }

    fun remove(id: Int): Arena = copy(obstacles = obstacles.filterNot { it.id == id })

    fun setFace(id: Int, face: Face?): Arena {
        obstacle(id) ?: return this
        return copy(obstacles = obstacles.map { if (it.id == id) it.copy(imageFace = face) else it })
    }

    /** Inbound TARGET. Unknown obstacle is ignored, never auto-created. */
    fun applyTarget(id: Int, targetId: Int, face: Face?): Arena {
        obstacle(id) ?: return this
        return copy(
            obstacles = obstacles.map {
                if (it.id == id) it.copy(target = Target(targetId, face)) else it
            }
        )
    }

    /** Inbound ROBOT. Out-of-range coordinates are ignored, never clamped. */
    fun applyPose(x: Int, y: Int, heading: Face): Arena {
        val cell = Cell(x, y)
        if (!inBounds(cell)) return this
        return copy(robot = RobotPose(cell, heading))
    }

    private fun inBounds(cell: Cell) =
        cell.x in 0 until Config.CELLS && cell.y in 0 until Config.CELLS
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests "*ArenaTest*"`
Expected: PASS, 12 tests

- [ ] **Step 5: Commit**

```bash
git add android/app/src/main/java/com/mdp/grp11/arena/Arena.kt \
        android/app/src/test/java/com/mdp/grp11/arena/ArenaTest.kt
git commit -m "feat(android): add arena model with fixed-pool ids and invariants"
```

---

## Task 5: Protocol message types and decoder

**Files:**
- Create: `android/app/src/main/java/com/mdp/grp11/protocol/Messages.kt`
- Create: `android/app/src/main/java/com/mdp/grp11/protocol/Decoder.kt`
- Test: `android/app/src/test/java/com/mdp/grp11/protocol/DecoderTest.kt`

**Interfaces:**
- Consumes: `Face`
- Produces: `sealed interface Inbound` with `Inbound.Status(text)`, `Inbound.TargetFound(obstacle, targetId, face)`, `Inbound.Pose(x, y, heading)`, `Inbound.Unknown(raw)`; `sealed interface Outbound` with `Outbound.AddObstacle(id, x, y)`, `Outbound.RemoveObstacle(id)`, `Outbound.SetFace(id, x, y, face)`, `Outbound.Move(token)`; `fun decode(line: String): Inbound`

- [ ] **Step 1: Write the failing tests**

`android/app/src/test/java/com/mdp/grp11/protocol/DecoderTest.kt`:

```kotlin
package com.mdp.grp11.protocol

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class DecoderTest {

    @Test fun `MSG extracts the bracketed payload`() {
        assertEquals(Inbound.Status("Moving"), decode("MSG,[Moving]"))
        assertEquals(Inbound.Status("Scanning obstacle 2"), decode("MSG,[Scanning obstacle 2]"))
    }

    @Test fun `MSG without brackets falls back to the remainder`() {
        assertEquals(Inbound.Status("Ready"), decode("MSG,Ready"))
    }

    @Test fun `TARGET three arg form`() {
        assertEquals(Inbound.TargetFound(2, 11, null), decode("TARGET,B2,11"))
    }

    @Test fun `TARGET four arg form carries the face`() {
        assertEquals(Inbound.TargetFound(2, 11, Face.N), decode("TARGET,B2,11,N"))
    }

    @Test fun `TARGET accepts a bare obstacle number and spaces after commas`() {
        assertEquals(Inbound.TargetFound(2, 11, null), decode("TARGET, 2, 11"))
    }

    @Test fun `TARGET accepts an id outside the image pool`() {
        assertEquals(Inbound.TargetFound(2, 4, null), decode("TARGET,B2,4"))
    }

    @Test fun `ROBOT parses coordinates and heading`() {
        assertEquals(Inbound.Pose(1, 1, Face.N), decode("ROBOT,1,1,N"))
        assertEquals(Inbound.Pose(7, 2, Face.W), decode("ROBOT, 7, 2, w"))
    }

    @Test fun `verbs are case insensitive`() {
        assertEquals(Inbound.TargetFound(2, 11, null), decode("target,B2,11"))
    }

    @Test fun `unknown verb becomes Unknown and keeps the raw line`() {
        val r = decode("WAT,1,2")
        assertTrue(r is Inbound.Unknown)
        assertEquals("WAT,1,2", (r as Inbound.Unknown).raw)
    }

    @Test fun `malformed lines never throw`() {
        val junk = listOf(
            "", "   ", ",", "TARGET", "TARGET,", "TARGET,B2", "TARGET,B2,xx",
            "ROBOT,1", "ROBOT,1,1", "ROBOT,1,1,Q", "ROBOT,a,b,N", "MSG",
            "TARGET,B2,11,Q", " ",
        )
        junk.forEach { line ->
            val r = decode(line)          // must not throw
            assertTrue("expected Unknown for '$line' but got $r", r is Inbound.Unknown)
        }
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests "*DecoderTest*"`
Expected: FAIL — `Unresolved reference: decode`

- [ ] **Step 3: Write the implementation**

`android/app/src/main/java/com/mdp/grp11/protocol/Messages.kt`:

```kotlin
package com.mdp.grp11.protocol

sealed interface Inbound {
    data class Status(val text: String) : Inbound
    data class TargetFound(val obstacle: Int, val targetId: Int, val face: Face?) : Inbound
    data class Pose(val x: Int, val y: Int, val heading: Face) : Inbound
    data class Unknown(val raw: String) : Inbound
}

sealed interface Outbound {
    data class AddObstacle(val id: Int, val x: Int, val y: Int) : Outbound
    data class RemoveObstacle(val id: Int) : Outbound
    data class SetFace(val id: Int, val x: Int, val y: Int, val face: Face?) : Outbound
    data class Move(val token: String) : Outbound
}
```

`android/app/src/main/java/com/mdp/grp11/protocol/Decoder.kt`:

```kotlin
package com.mdp.grp11.protocol

/**
 * Total function: every input produces an Inbound, and it never throws.
 *
 * A parser exception on the I/O coroutine would kill the read loop, which from
 * the UI is indistinguishable from a disconnect. Worst case is Unknown.
 *
 * Tolerances exist because the two source documents disagree:
 *  - the checklist writes "TARGET, <n>, <id>" with spaces
 *  - the slides write obstacle ids as "B2", the checklist as a bare number
 *  - the 4-argument TARGET form appears only in the slides
 *  - the checklist's own example uses target id 4, outside the 11-40 pool,
 *    so target ids are NEVER range-checked
 */
fun decode(line: String): Inbound {
    val raw = line.trim()
    if (raw.isEmpty()) return Inbound.Unknown(line)

    val parts = raw.split(',').map { it.trim() }
    val verb = parts[0].uppercase()

    return when (verb) {
        "MSG" -> decodeStatus(raw, line)
        "TARGET" -> decodeTarget(parts, line)
        "ROBOT" -> decodePose(parts, line)
        else -> Inbound.Unknown(line)
    }
}

private fun decodeStatus(raw: String, original: String): Inbound {
    val body = raw.substringAfter(',', missingDelimiterValue = "").trim()
    if (body.isEmpty()) return Inbound.Unknown(original)
    val inner = body.substringAfter('[', "").substringBeforeLast(']', "")
    return Inbound.Status(if (inner.isNotEmpty()) inner else body)
}

private fun decodeTarget(parts: List<String>, original: String): Inbound {
    if (parts.size !in 3..4) return Inbound.Unknown(original)
    val obstacle = obstacleId(parts[1]) ?: return Inbound.Unknown(original)
    val targetId = parts[2].toIntOrNull() ?: return Inbound.Unknown(original)
    val face = if (parts.size == 4) {
        Face.parse(parts[3]) ?: return Inbound.Unknown(original)
    } else null
    return Inbound.TargetFound(obstacle, targetId, face)
}

private fun decodePose(parts: List<String>, original: String): Inbound {
    if (parts.size != 4) return Inbound.Unknown(original)
    val x = parts[1].toIntOrNull() ?: return Inbound.Unknown(original)
    val y = parts[2].toIntOrNull() ?: return Inbound.Unknown(original)
    val heading = Face.parse(parts[3]) ?: return Inbound.Unknown(original)
    return Inbound.Pose(x, y, heading)
}

/** Accepts "B2" or "2". */
private fun obstacleId(token: String): Int? =
    token.trim().removePrefix("B").removePrefix("b").toIntOrNull()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests "*DecoderTest*"`
Expected: PASS, 10 tests

- [ ] **Step 5: Commit**

```bash
git add android/app/src/main/java/com/mdp/grp11/protocol/ \
        android/app/src/test/java/com/mdp/grp11/protocol/DecoderTest.kt
git commit -m "feat(android): add total protocol decoder with document tolerances"
```

---

## Task 6: Protocol encoder

**Files:**
- Create: `android/app/src/main/java/com/mdp/grp11/protocol/Encoder.kt`
- Test: `android/app/src/test/java/com/mdp/grp11/protocol/EncoderTest.kt`

**Interfaces:**
- Consumes: `Outbound`, `Face`
- Produces: `fun encode(msg: Outbound): String`

- [ ] **Step 1: Write the failing tests**

`android/app/src/test/java/com/mdp/grp11/protocol/EncoderTest.kt`:

```kotlin
package com.mdp.grp11.protocol

import org.junit.Assert.assertEquals
import org.junit.Test

class EncoderTest {

    @Test fun `add obstacle matches the briefing example`() {
        assertEquals("ADD,B1,(10,6)", encode(Outbound.AddObstacle(1, 10, 6)))
    }

    @Test fun `remove obstacle matches the briefing example`() {
        assertEquals("SUB,B1", encode(Outbound.RemoveObstacle(1)))
    }

    @Test fun `set face carries the coordinate as C7 requires`() {
        assertEquals("FACE,B3,(14,15),E", encode(Outbound.SetFace(3, 14, 15, Face.E)))
    }

    @Test fun `clearing a face sends NONE`() {
        assertEquals("FACE,B3,(14,15),NONE", encode(Outbound.SetFace(3, 14, 15, null)))
    }

    @Test fun `move sends the bare configured token`() {
        assertEquals("f", encode(Outbound.Move("f")))
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests "*EncoderTest*"`
Expected: FAIL — `Unresolved reference: encode`

- [ ] **Step 3: Write the implementation**

`android/app/src/main/java/com/mdp/grp11/protocol/Encoder.kt`:

```kotlin
package com.mdp.grp11.protocol

/**
 * Formats follow the worked examples in MDP ARCM Briefing Slides.pdf.
 *
 * FACE additionally carries the coordinate: the checklist text requires "the
 * target face and obstacle coordinate", while the slide format omits it. We
 * send the superset. This must be agreed with the RPi parser owner.
 */
fun encode(msg: Outbound): String = when (msg) {
    is Outbound.AddObstacle -> "ADD,B${msg.id},(${msg.x},${msg.y})"
    is Outbound.RemoveObstacle -> "SUB,B${msg.id}"
    is Outbound.SetFace -> "FACE,B${msg.id},(${msg.x},${msg.y}),${msg.face?.name ?: "NONE"}"
    is Outbound.Move -> msg.token
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests "*EncoderTest*"`
Expected: PASS, 5 tests

- [ ] **Step 5: Commit**

```bash
git add android/app/src/main/java/com/mdp/grp11/protocol/Encoder.kt \
        android/app/src/test/java/com/mdp/grp11/protocol/EncoderTest.kt
git commit -m "feat(android): add protocol encoder"
```

---

## Task 7: Line framing

**Files:**
- Create: `android/app/src/main/java/com/mdp/grp11/transport/LineFramer.kt`
- Test: `android/app/src/test/java/com/mdp/grp11/transport/LineFramerTest.kt`

**Interfaces:**
- Consumes: nothing
- Produces: `class LineFramer` with `fun feed(bytes: ByteArray, length: Int): List<String>` and `fun reset()`

- [ ] **Step 1: Write the failing tests**

`android/app/src/test/java/com/mdp/grp11/transport/LineFramerTest.kt`:

```kotlin
package com.mdp.grp11.transport

import org.junit.Assert.assertEquals
import org.junit.Test

class LineFramerTest {

    private fun LineFramer.feed(s: String): List<String> {
        val b = s.toByteArray()
        return feed(b, b.size)
    }

    @Test fun `emits nothing until a newline arrives`() {
        val f = LineFramer()
        assertEquals(emptyList<String>(), f.feed("ROBOT,1,1"))
        assertEquals(listOf("ROBOT,1,1,N"), f.feed(",N\n"))
    }

    @Test fun `splits a chunk containing several messages`() {
        val f = LineFramer()
        assertEquals(listOf("A", "B", "C"), f.feed("A\nB\nC\n"))
    }

    @Test fun `reassembles a message delivered one character at a time`() {
        val f = LineFramer()
        val out = mutableListOf<String>()
        "TARGET,B2,11\n".forEach { ch -> out += f.feed(ch.toString()) }
        assertEquals(listOf("TARGET,B2,11"), out)
    }

    @Test fun `tolerates CRLF`() {
        val f = LineFramer()
        assertEquals(listOf("MSG,[Moving]"), f.feed("MSG,[Moving]\r\n"))
    }

    @Test fun `reset drops a half received line`() {
        val f = LineFramer()
        f.feed("ROBO")
        f.reset()
        assertEquals(listOf("T,1,1,N"), f.feed("T,1,1,N\n"))
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests "*LineFramerTest*"`
Expected: FAIL — `Unresolved reference: LineFramer`

- [ ] **Step 3: Write the implementation**

`android/app/src/main/java/com/mdp/grp11/transport/LineFramer.kt`:

```kotlin
package com.mdp.grp11.transport

/**
 * RFCOMM is a byte stream, not a message stream: a read may return half a
 * message or several glued together. This accumulates until a newline.
 *
 * reset() MUST be called on disconnect. A half-line left in the buffer would
 * otherwise prepend to the first message after reconnect and corrupt it - a
 * bug that only manifests after a reconnect.
 */
class LineFramer {

    private val buffer = StringBuilder()

    fun feed(bytes: ByteArray, length: Int): List<String> {
        buffer.append(String(bytes, 0, length, Charsets.UTF_8))
        if (buffer.indexOf("\n") < 0) return emptyList()

        val out = mutableListOf<String>()
        while (true) {
            val nl = buffer.indexOf("\n")
            if (nl < 0) break
            val line = buffer.substring(0, nl).removeSuffix("\r")
            buffer.delete(0, nl + 1)
            if (line.isNotEmpty()) out += line
        }
        return out
    }

    fun reset() {
        buffer.setLength(0)
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests "*LineFramerTest*"`
Expected: PASS, 5 tests

- [ ] **Step 5: Commit**

```bash
git add android/app/src/main/java/com/mdp/grp11/transport/LineFramer.kt \
        android/app/src/test/java/com/mdp/grp11/transport/LineFramerTest.kt
git commit -m "feat(android): add newline framing for the RFCOMM byte stream"
```

---

## Task 8: Transport interface and FakeTransport

**Files:**
- Create: `android/app/src/main/java/com/mdp/grp11/transport/Transport.kt`
- Create: `android/app/src/main/java/com/mdp/grp11/transport/FakeTransport.kt`
- Test: `android/app/src/test/java/com/mdp/grp11/transport/FakeTransportTest.kt`

**Interfaces:**
- Consumes: nothing
- Produces: `data class DeviceInfo(val name: String, val address: String)`; `sealed interface ConnectTarget { data class Client(val device: DeviceInfo); data object Listen }`; `interface Transport { val incoming: Flow<String>; suspend fun connect(target: ConnectTarget): Result<DeviceInfo>; suspend fun send(line: String): Result<Unit>; fun close() }`; `class FakeTransport : Transport` with `val sent: List<String>`, `suspend fun deliver(line: String)`, `suspend fun dropLink()`, `var failNextConnect: Boolean`

- [ ] **Step 1: Write the failing tests**

`android/app/src/test/java/com/mdp/grp11/transport/FakeTransportTest.kt`:

```kotlin
package com.mdp.grp11.transport

import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class FakeTransportTest {

    private val device = DeviceInfo("AMD-TOOL", "3C:5A:B4:11:88:F2")

    @Test fun `records what the app sent`() = runTest {
        val t = FakeTransport()
        t.connect(ConnectTarget.Client(device))
        t.send("ADD,B1,(10,6)")
        t.send("SUB,B1")
        assertEquals(listOf("ADD,B1,(10,6)", "SUB,B1"), t.sent)
    }

    @Test fun `delivers a line to collectors`() = runTest {
        val t = FakeTransport()
        t.connect(ConnectTarget.Client(device))
        val received = mutableListOf<String>()
        val job = launch { t.incoming.collect { received += it } }
        t.deliver("ROBOT,1,1,N")
        job.cancel()
        assertEquals(listOf("ROBOT,1,1,N"), received)
    }

    @Test fun `connect can be made to fail`() = runTest {
        val t = FakeTransport()
        t.failNextConnect = true
        assertTrue(t.connect(ConnectTarget.Client(device)).isFailure)
        assertTrue(t.connect(ConnectTarget.Client(device)).isSuccess)
    }

    @Test fun `send fails once the link is dropped`() = runTest {
        val t = FakeTransport()
        t.connect(ConnectTarget.Client(device))
        t.dropLink()
        assertTrue(t.send("f").isFailure)
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests "*FakeTransportTest*"`
Expected: FAIL — `Unresolved reference: FakeTransport`

- [ ] **Step 3: Write the implementation**

`android/app/src/main/java/com/mdp/grp11/transport/Transport.kt`:

```kotlin
package com.mdp.grp11.transport

import kotlinx.coroutines.flow.Flow

data class DeviceInfo(val name: String, val address: String)

sealed interface ConnectTarget {
    /** Connect out, as the RPi expects (it runs `rfcomm listen`). */
    data class Client(val device: DeviceInfo) : ConnectTarget

    /** Accept an incoming connection, as the AMD tool expects. */
    data object Listen : ConnectTarget
}

/**
 * A framed, line-oriented link. Implementations emit only COMPLETE lines.
 */
interface Transport {
    val incoming: Flow<String>
    suspend fun connect(target: ConnectTarget): Result<DeviceInfo>
    suspend fun send(line: String): Result<Unit>
    fun close()
}
```

`android/app/src/main/java/com/mdp/grp11/transport/FakeTransport.kt`:

```kotlin
package com.mdp.grp11.transport

import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow

/**
 * In-memory Transport for tests and for developing without hardware.
 * The emulator has no Bluetooth SPP stack and the AMD tool needs a second
 * physical device, so this is the only way to exercise the app solo.
 */
class FakeTransport : Transport {

    private val _incoming = MutableSharedFlow<String>(extraBufferCapacity = 64)
    override val incoming: SharedFlow<String> = _incoming.asSharedFlow()

    private val _sent = mutableListOf<String>()
    val sent: List<String> get() = _sent

    private var connected = false
    var failNextConnect: Boolean = false

    override suspend fun connect(target: ConnectTarget): Result<DeviceInfo> {
        if (failNextConnect) {
            failNextConnect = false
            return Result.failure(IllegalStateException("fake: refused"))
        }
        connected = true
        val device = when (target) {
            is ConnectTarget.Client -> target.device
            ConnectTarget.Listen -> DeviceInfo("FAKE-PEER", "00:00:00:00:00:00")
        }
        return Result.success(device)
    }

    override suspend fun send(line: String): Result<Unit> {
        if (!connected) return Result.failure(IllegalStateException("fake: not connected"))
        _sent += line
        return Result.success(Unit)
    }

    override fun close() {
        connected = false
    }

    // --- levers only a fake has -------------------------------------------

    /** Simulate a line arriving from the peer. */
    suspend fun deliver(line: String) {
        _incoming.emit(line)
    }

    /** Simulate the peer vanishing mid-session. */
    fun dropLink() {
        connected = false
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests "*FakeTransportTest*"`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
git add android/app/src/main/java/com/mdp/grp11/transport/Transport.kt \
        android/app/src/main/java/com/mdp/grp11/transport/FakeTransport.kt \
        android/app/src/test/java/com/mdp/grp11/transport/FakeTransportTest.kt
git commit -m "feat(android): add Transport interface and in-memory FakeTransport"
```

---

## Task 9: ConnectionRepository and reconnect state machine

**Files:**
- Create: `android/app/src/main/java/com/mdp/grp11/connection/ConnectionState.kt`
- Create: `android/app/src/main/java/com/mdp/grp11/connection/ConnectionRepository.kt`
- Test: `android/app/src/test/java/com/mdp/grp11/connection/ConnectionRepositoryTest.kt`

**Interfaces:**
- Consumes: `Transport`, `ConnectTarget`, `DeviceInfo`, `decode`, `encode`, `Outbound`, `Config.BACKOFF_MS`
- Produces: `sealed interface ConnectionState { Idle; Connecting(device); Connected(device); Reconnecting(device, attempt); Failed(reason) }`; `class ConnectionRepository(transport, scope)` with `val state: StateFlow<ConnectionState>`, `val inbound: SharedFlow<Inbound>`, `val traffic: SharedFlow<TrafficLine>`, `suspend fun connect(target)`, `suspend fun send(msg: Outbound): Boolean`, `fun disconnect()`; `data class TrafficLine(val outbound: Boolean, val text: String, val delivered: Boolean)`

- [ ] **Step 1: Write the failing tests**

`android/app/src/test/java/com/mdp/grp11/connection/ConnectionRepositoryTest.kt`:

```kotlin
package com.mdp.grp11.connection

import com.mdp.grp11.protocol.Face
import com.mdp.grp11.protocol.Inbound
import com.mdp.grp11.protocol.Outbound
import com.mdp.grp11.transport.ConnectTarget
import com.mdp.grp11.transport.DeviceInfo
import com.mdp.grp11.transport.FakeTransport
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class ConnectionRepositoryTest {

    private val device = DeviceInfo("AMD-TOOL", "3C:5A:B4:11:88:F2")

    @Test fun `connect moves Idle to Connected`() = runTest {
        val fake = FakeTransport()
        val repo = ConnectionRepository(fake, TestScope(testScheduler))
        assertTrue(repo.state.value is ConnectionState.Idle)
        repo.connect(ConnectTarget.Client(device))
        assertEquals(ConnectionState.Connected(device), repo.state.value)
    }

    @Test fun `a malformed line does not stop later messages arriving`() = runTest {
        val fake = FakeTransport()
        val repo = ConnectionRepository(fake, TestScope(testScheduler))
        repo.connect(ConnectTarget.Client(device))

        val got = mutableListOf<Inbound>()
        val job = launch { repo.inbound.collect { got += it } }

        fake.deliver("TARGET,B2")        // truncated
        fake.deliver("ROBOT,3,4,E")      // must still arrive
        job.cancel()

        assertTrue(got[0] is Inbound.Unknown)
        assertEquals(Inbound.Pose(3, 4, Face.E), got[1])
    }

    @Test fun `send records an outbound traffic line`() = runTest {
        val fake = FakeTransport()
        val repo = ConnectionRepository(fake, TestScope(testScheduler))
        repo.connect(ConnectTarget.Client(device))

        val seen = mutableListOf<TrafficLine>()
        val job = launch { repo.traffic.collect { seen += it } }
        repo.send(Outbound.RemoveObstacle(3))
        job.cancel()

        assertEquals(TrafficLine(outbound = true, text = "SUB,B3", delivered = true), seen.last())
        assertEquals(listOf("SUB,B3"), fake.sent)
    }

    @Test fun `send while disconnected is dropped and marked undelivered`() = runTest {
        val fake = FakeTransport()
        val repo = ConnectionRepository(fake, TestScope(testScheduler))
        repo.connect(ConnectTarget.Client(device))
        fake.dropLink()

        val seen = mutableListOf<TrafficLine>()
        val job = launch { repo.traffic.collect { seen += it } }
        val ok = repo.send(Outbound.Move("f"))
        job.cancel()

        assertFalse(ok)
        assertFalse(seen.last().delivered)
        assertFalse(fake.sent.contains("f"))
    }

    @Test fun `disconnect returns to Idle`() = runTest {
        val fake = FakeTransport()
        val repo = ConnectionRepository(fake, TestScope(testScheduler))
        repo.connect(ConnectTarget.Client(device))
        repo.disconnect()
        assertTrue(repo.state.value is ConnectionState.Idle)
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests "*ConnectionRepositoryTest*"`
Expected: FAIL — `Unresolved reference: ConnectionRepository`

- [ ] **Step 3: Write the implementation**

`android/app/src/main/java/com/mdp/grp11/connection/ConnectionState.kt`:

```kotlin
package com.mdp.grp11.connection

import com.mdp.grp11.transport.DeviceInfo

sealed interface ConnectionState {
    data object Idle : ConnectionState
    data class Connecting(val device: DeviceInfo?) : ConnectionState
    data class Connected(val device: DeviceInfo) : ConnectionState
    data class Reconnecting(val device: DeviceInfo?, val attempt: Int) : ConnectionState
    data class Failed(val reason: String) : ConnectionState
}
```

`android/app/src/main/java/com/mdp/grp11/connection/ConnectionRepository.kt`:

```kotlin
package com.mdp.grp11.connection

import com.mdp.grp11.config.Config
import com.mdp.grp11.protocol.Inbound
import com.mdp.grp11.protocol.Outbound
import com.mdp.grp11.protocol.decode
import com.mdp.grp11.protocol.encode
import com.mdp.grp11.transport.ConnectTarget
import com.mdp.grp11.transport.DeviceInfo
import com.mdp.grp11.transport.Transport
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/** One line of Bluetooth traffic, for the raw log (C.1). */
data class TrafficLine(val outbound: Boolean, val text: String, val delivered: Boolean)

/**
 * Owns the link. Application-scoped, so it outlives every ViewModel and the
 * arena keeps its state across a rotation or a reconnect.
 *
 * The UI never touches a socket and never blocks on one - which is what C.8
 * actually tests.
 */
class ConnectionRepository(
    private val transport: Transport,
    private val scope: CoroutineScope,
) {

    private val _state = MutableStateFlow<ConnectionState>(ConnectionState.Idle)
    val state: StateFlow<ConnectionState> = _state.asStateFlow()

    private val _inbound = MutableSharedFlow<Inbound>(extraBufferCapacity = 64)
    val inbound: SharedFlow<Inbound> = _inbound.asSharedFlow()

    private val _traffic = MutableSharedFlow<TrafficLine>(extraBufferCapacity = 128)
    val traffic: SharedFlow<TrafficLine> = _traffic.asSharedFlow()

    private val writeLock = Mutex()
    private var readJob: Job? = null
    private var lastTarget: ConnectTarget? = null

    suspend fun connect(target: ConnectTarget) {
        lastTarget = target
        val known = (target as? ConnectTarget.Client)?.device
        _state.value = ConnectionState.Connecting(known)

        transport.connect(target)
            .onSuccess { device ->
                _state.value = ConnectionState.Connected(device)
                startReading()
            }
            .onFailure { e ->
                _state.value = ConnectionState.Failed(e.message ?: "connect failed")
            }
    }

    private fun startReading() {
        readJob?.cancel()
        readJob = scope.launch {
            transport.incoming.collect { line ->
                _traffic.emit(TrafficLine(outbound = false, text = line, delivered = true))
                // decode is total, so a bad line can never kill this loop.
                _inbound.emit(decode(line))
            }
        }
    }

    /** Returns true when the message actually reached the peer. */
    suspend fun send(msg: Outbound): Boolean {
        val text = encode(msg)
        val ok = writeLock.withLock { transport.send(text).isSuccess }
        _traffic.emit(TrafficLine(outbound = true, text = text, delivered = ok))
        if (!ok) beginReconnect()
        return ok
    }

    private fun beginReconnect() {
        val target = lastTarget ?: return
        if (_state.value is ConnectionState.Reconnecting) return
        val device = (target as? ConnectTarget.Client)?.device
        scope.launch {
            var attempt = 1
            while (true) {
                _state.value = ConnectionState.Reconnecting(device, attempt)
                delay(Config.BACKOFF_MS.getOrElse(attempt - 1) { Config.BACKOFF_MS.last() })
                val result = transport.connect(target)
                if (result.isSuccess) {
                    _state.value = ConnectionState.Connected(result.getOrThrow())
                    startReading()
                    return@launch
                }
                attempt++
            }
        }
    }

    fun disconnect() {
        readJob?.cancel()
        readJob = null
        transport.close()
        _state.value = ConnectionState.Idle
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests "*ConnectionRepositoryTest*"`
Expected: PASS, 5 tests

- [ ] **Step 5: Run the whole suite**

Run: `cd android && ./gradlew :app:testDebugUnitTest`
Expected: PASS — all tests from Tasks 3–9

- [ ] **Step 6: Commit**

```bash
git add android/app/src/main/java/com/mdp/grp11/connection/ \
        android/app/src/test/java/com/mdp/grp11/connection/
git commit -m "feat(android): add ConnectionRepository with reconnect state machine"
```

---

## Task 10: BluetoothSppTransport

**Files:**
- Create: `android/app/src/main/java/com/mdp/grp11/transport/BluetoothSppTransport.kt`

**Interfaces:**
- Consumes: `Transport`, `ConnectTarget`, `DeviceInfo`, `LineFramer`, `Config.SPP_UUID`
- Produces: `class BluetoothSppTransport(context: Context) : Transport`, plus `fun bondedDevices(): List<DeviceInfo>`

**No unit tests.** This is the only class in the plan that cannot be tested on the JVM — it needs a real radio and a real peer. It is verified in Task 18's demo scripts. Everything it does that *can* be tested lives in `LineFramer` (Task 7) and `ConnectionRepository` (Task 9).

- [ ] **Step 1: Write the implementation**

```kotlin
package com.mdp.grp11.transport

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothServerSocket
import android.bluetooth.BluetoothSocket
import android.content.Context
import com.mdp.grp11.config.Config
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.withContext
import java.io.IOException

/**
 * Real RFCOMM. Both roles matter:
 *  - Client, for the RPi, which runs `rfcomm listen` and is therefore server.
 *  - Listen, for the AMD tool, which connects TO the tablet and offers
 *    "Reconnect to last device". C.8 is graded by the peer reconnecting to us,
 *    so a client-only implementation cannot pass it.
 */
@SuppressLint("MissingPermission")   // callers gate on BLUETOOTH_CONNECT / _SCAN
class BluetoothSppTransport(context: Context) : Transport {

    private val adapter: BluetoothAdapter? =
        context.getSystemService(BluetoothManager::class.java)?.adapter

    private val framer = LineFramer()
    private val _incoming = MutableSharedFlow<String>(extraBufferCapacity = 64)
    override val incoming: Flow<String> = _incoming.asSharedFlow()

    private var socket: BluetoothSocket? = null
    private var serverSocket: BluetoothServerSocket? = null

    fun bondedDevices(): List<DeviceInfo> =
        adapter?.bondedDevices.orEmpty().map { DeviceInfo(it.name ?: it.address, it.address) }

    override suspend fun connect(target: ConnectTarget): Result<DeviceInfo> =
        withContext(Dispatchers.IO) {
            val a = adapter ?: return@withContext Result.failure(
                IllegalStateException("No Bluetooth adapter")
            )
            if (!a.isEnabled) return@withContext Result.failure(
                IllegalStateException("Bluetooth is off")
            )
            runCatching {
                // Discovery starves the radio and makes connect() flaky.
                a.cancelDiscovery()
                framer.reset()

                val s = when (target) {
                    is ConnectTarget.Client -> {
                        val remote = a.getRemoteDevice(target.device.address)
                        remote.createRfcommSocketToServiceRecord(Config.SPP_UUID)
                            .also { it.connect() }
                    }
                    ConnectTarget.Listen -> {
                        val server = a.listenUsingRfcommWithServiceRecord(
                            "MDP-GRP11", Config.SPP_UUID
                        )
                        serverSocket = server
                        server.accept().also { server.close(); serverSocket = null }
                    }
                }
                socket = s
                val remote = s.remoteDevice
                DeviceInfo(remote.name ?: remote.address, remote.address)
            }
        }

    /** Blocking read loop. Call from a coroutine on Dispatchers.IO. */
    suspend fun pump() = withContext(Dispatchers.IO) {
        val input = socket?.inputStream ?: return@withContext
        val buf = ByteArray(1024)
        try {
            while (true) {
                val n = input.read(buf)
                if (n < 0) break
                framer.feed(buf, n).forEach { _incoming.emit(it) }
            }
        } catch (_: IOException) {
            // Peer went away; ConnectionRepository handles the transition.
        }
    }

    override suspend fun send(line: String): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            val out = socket?.outputStream ?: error("not connected")
            out.write((line + "\n").toByteArray())
            out.flush()
        }
    }

    override fun close() {
        framer.reset()      // never let a half-line survive into the next session
        runCatching { socket?.close() }
        runCatching { serverSocket?.close() }
        socket = null
        serverSocket = null
    }
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd android && ./gradlew :app:compileDebugKotlin`
Expected: `BUILD SUCCESSFUL`

- [ ] **Step 3: Commit**

```bash
git add android/app/src/main/java/com/mdp/grp11/transport/BluetoothSppTransport.kt
git commit -m "feat(android): add real RFCOMM transport with client and server roles"
```

---

## Task 11: Theme tokens

**Files:**
- Create: `android/app/src/main/java/com/mdp/grp11/ui/theme/Theme.kt`

**Interfaces:**
- Consumes: nothing
- Produces: `MdpTheme(content: @Composable () -> Unit)`; `object MdpTokens` with `Ink`, `Cream`, `Paper`, `Blue`, `Pink`, `Yellow`, `Green`, `Muted` as `Color`, and `HardShadow: Dp`

Visual direction is fixed by the design canvas: cream ground, heavy ink outlines, hard offset shadows.

- [ ] **Step 1: Write the implementation**

```kotlin
package com.mdp.grp11.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

object MdpTokens {
    val Ink = Color(0xFF201C2B)
    val Cream = Color(0xFFF2EBDC)
    val Paper = Color(0xFFFDFBF5)
    val Blue = Color(0xFF3E7BE8)
    val Pink = Color(0xFFE8557F)
    val Yellow = Color(0xFFEFC33F)
    val Green = Color(0xFF4FB86B)
    val Muted = Color(0xFF6E6880)

    val HardShadow: Dp = 4.dp
    val GridStroke: Dp = 1.dp
    val GridMajorStroke: Dp = 2.dp
}

private val Scheme = lightColorScheme(
    primary = MdpTokens.Blue,
    onPrimary = Color.White,
    secondary = MdpTokens.Pink,
    background = MdpTokens.Cream,
    onBackground = MdpTokens.Ink,
    surface = MdpTokens.Paper,
    onSurface = MdpTokens.Ink,
    error = MdpTokens.Pink,
)

/** Single light scheme by design - the tablet is used under lab lighting. */
@Composable
fun MdpTheme(content: @Composable () -> Unit) {
    @Suppress("UNUSED_EXPRESSION") isSystemInDarkTheme()
    MaterialTheme(colorScheme = Scheme, content = content)
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd android && ./gradlew :app:compileDebugKotlin`
Expected: `BUILD SUCCESSFUL`

- [ ] **Step 3: Commit**

```bash
git add android/app/src/main/java/com/mdp/grp11/ui/theme/Theme.kt
git commit -m "feat(android): add theme tokens"
```

---

## Task 12: ArenaCanvas

**Files:**
- Create: `android/app/src/main/java/com/mdp/grp11/ui/ArenaCanvas.kt`
- Test: `android/app/src/test/java/com/mdp/grp11/ui/HitTestTest.kt`

**Interfaces:**
- Consumes: `Arena`, `Cell`, `Obstacle`, `Grid`, `Config`, `MdpTokens`
- Produces: `fun hitTest(arena: Arena, px: Float, py: Float, gridPx: Float): Obstacle?`; `@Composable fun ArenaCanvas(arena, selectedId, onPlace: (Cell) -> Unit, onSelect: (Int) -> Unit, onDragTo: (Int, Cell) -> Unit, onDropOutside: (Int) -> Unit, onCommit: (Int) -> Unit, modifier)`

- [ ] **Step 1: Write the failing hit-test tests**

`android/app/src/test/java/com/mdp/grp11/ui/HitTestTest.kt`:

```kotlin
package com.mdp.grp11.ui

import com.mdp.grp11.arena.Arena
import com.mdp.grp11.arena.Cell
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class HitTestTest {

    private val gridPx = 660f     // 33px cells

    private fun arenaWith(vararg cells: Cell): Arena {
        var a = Arena()
        cells.forEach { a = a.place(it).first }
        return a
    }

    @Test fun `a tap on the block selects it`() {
        val a = arenaWith(Cell(10, 10))
        // cell (10,10) centre in canvas px: x = 10*33+16.5, y = (19-10)*33+16.5
        assertEquals(1, hitTest(a, 346.5f, 313.5f, gridPx)?.id)
    }

    @Test fun `a tap just outside the block still selects it within 48dp`() {
        val a = arenaWith(Cell(10, 10))
        // 24px away - inside the 27px radius, outside the 33px cell
        assertEquals(1, hitTest(a, 346.5f + 24f, 313.5f, gridPx)?.id)
    }

    @Test fun `a tap beyond the radius selects nothing`() {
        val a = arenaWith(Cell(10, 10))
        assertNull(hitTest(a, 346.5f + 40f, 313.5f, gridPx))
    }

    @Test fun `overlapping targets resolve to the nearest centre`() {
        val a = arenaWith(Cell(10, 10), Cell(11, 10))
        // 4px right of block 1's centre: both within radius, 1 is nearer
        assertEquals(1, hitTest(a, 350.5f, 313.5f, gridPx)?.id)
        // 4px left of block 2's centre
        assertEquals(2, hitTest(a, 375.5f, 313.5f, gridPx)?.id)
    }

    @Test fun `empty arena hits nothing`() {
        assertNull(hitTest(Arena(), 300f, 300f, gridPx))
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests "*HitTestTest*"`
Expected: FAIL — `Unresolved reference: hitTest`

- [ ] **Step 3: Write ArenaCanvas**

```kotlin
package com.mdp.grp11.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import com.mdp.grp11.arena.Arena
import com.mdp.grp11.arena.Cell
import com.mdp.grp11.arena.Grid
import com.mdp.grp11.arena.Obstacle
import com.mdp.grp11.config.Config
import com.mdp.grp11.ui.theme.MdpTokens
import kotlin.math.min

/** 48dp = 7.6mm. A 33px cell is only 4.7mm, so hit area != render size. */
const val HIT_RADIUS_DP = 24f

/**
 * Nearest block whose centre is within the touch radius, or null.
 * Radius scales with the grid so it stays a constant physical size.
 */
fun hitTest(arena: Arena, px: Float, py: Float, gridPx: Float): Obstacle? {
    val cellPx = gridPx / Config.CELLS
    val radius = cellPx * 0.82f          // ~27px when a cell is 33px
    var best: Obstacle? = null
    var bestD = radius * radius
    arena.obstacles.forEach { o ->
        val (cx, cy) = Grid.centreOf(o.cell.x, o.cell.y, gridPx)
        val d = (px - cx) * (px - cx) + (py - cy) * (py - cy)
        if (d <= bestD) { bestD = d; best = o }
    }
    return best
}

@Composable
fun ArenaCanvas(
    arena: Arena,
    selectedId: Int?,
    onPlace: (Cell) -> Unit,
    onSelect: (Int) -> Unit,
    onDragTo: (Int, Cell) -> Unit,
    onDropOutside: (Int) -> Unit,
    onCommit: (Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    var gridPx by remember { mutableStateOf(0f) }
    var draggingId by remember { mutableStateOf<Int?>(null) }
    var outside by remember { mutableStateOf(false) }

    Box(modifier) {
        Canvas(
            Modifier
                .fillMaxSize()
                .onSizeChanged { gridPx = min(it.width, it.height).toFloat() }
                .pointerInput(arena, gridPx) {
                    detectTapGestures { pos ->
                        val hit = hitTest(arena, pos.x, pos.y, gridPx)
                        if (hit != null) onSelect(hit.id)
                        else onPlace(cellOf(pos, gridPx))
                    }
                }
                .pointerInput(arena, gridPx) {
                    detectDragGestures(
                        onDragStart = { pos ->
                            draggingId = hitTest(arena, pos.x, pos.y, gridPx)?.id
                            outside = false
                        },
                        onDrag = { change, _ ->
                            val id = draggingId ?: return@detectDragGestures
                            val p = change.position
                            outside = p.x < 0 || p.y < 0 || p.x > gridPx || p.y > gridPx
                            if (!outside) onDragTo(id, cellOf(p, gridPx))
                        },
                        onDragEnd = {
                            val id = draggingId ?: return@detectDragGestures
                            if (outside) onDropOutside(id) else onCommit(id)
                            draggingId = null
                        },
                        onDragCancel = { draggingId = null },
                    )
                }
        ) {
            val g = min(size.width, size.height)
            drawGrid(g)
            drawStartZone(g)
            arena.obstacles.forEach { drawObstacle(it, g, it.id == selectedId) }
            arena.robot?.let { drawRobot(it.cell, g) }
        }
    }
}

private fun cellOf(pos: Offset, gridPx: Float): Cell {
    val (x, y) = Grid.cellAt(pos.x, pos.y, gridPx)
    return Cell(x, y)
}

private fun DrawScope.drawGrid(gridPx: Float) {
    val cell = gridPx / Config.CELLS
    drawRect(MdpTokens.Paper, size = Size(gridPx, gridPx))
    for (i in 0..Config.CELLS) {
        val major = i % 5 == 0
        val colour = if (major) MdpTokens.Muted else MdpTokens.Muted.copy(alpha = 0.25f)
        val w = if (major) 2f else 1f
        drawLine(colour, Offset(i * cell, 0f), Offset(i * cell, gridPx), w)
        drawLine(colour, Offset(0f, i * cell), Offset(gridPx, i * cell), w)
    }
}

private fun DrawScope.drawStartZone(gridPx: Float) {
    val cell = gridPx / Config.CELLS
    val side = cell * Config.START_ZONE_CELLS
    drawRect(
        MdpTokens.Yellow.copy(alpha = 0.3f),
        topLeft = Offset(0f, gridPx - side),
        size = Size(side, side),
    )
}

private fun DrawScope.drawObstacle(o: Obstacle, gridPx: Float, selected: Boolean) {
    val cell = gridPx / Config.CELLS
    val left = o.cell.x * cell
    val top = Grid.toCanvasRow(o.cell.y) * cell
    val fill = if (o.target != null) MdpTokens.Pink else MdpTokens.Blue
    drawRect(fill, Offset(left, top), Size(cell, cell))
    if (selected) {
        drawRect(
            MdpTokens.Yellow,
            Offset(left - 3f, top - 3f),
            Size(cell + 6f, cell + 6f),
            style = androidx.compose.ui.graphics.drawscope.Stroke(3f),
        )
    }
    o.imageFace?.let { face -> drawFaceBar(face, left, top, cell) }
    o.target?.face?.let { face -> drawFaceBar(face, left, top, cell) }
}

private fun DrawScope.drawFaceBar(
    face: com.mdp.grp11.protocol.Face,
    left: Float,
    top: Float,
    cell: Float,
) {
    val t = cell * 0.18f
    val (offset, s) = when (face) {
        com.mdp.grp11.protocol.Face.N -> Offset(left, top) to Size(cell, t)
        com.mdp.grp11.protocol.Face.S -> Offset(left, top + cell - t) to Size(cell, t)
        com.mdp.grp11.protocol.Face.W -> Offset(left, top) to Size(t, cell)
        com.mdp.grp11.protocol.Face.E -> Offset(left + cell - t, top) to Size(t, cell)
    }
    drawRect(MdpTokens.Yellow, offset, s)
}

private fun DrawScope.drawRobot(cell: Cell, gridPx: Float) {
    val c = gridPx / Config.CELLS
    val left = cell.x * c
    val top = (Grid.toCanvasRow(cell.y) - 2) * c    // 3x3 anchored at bottom-left
    drawRect(MdpTokens.Yellow, Offset(left, top), Size(c * 3, c * 3))
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests "*HitTestTest*"`
Expected: PASS, 5 tests

- [ ] **Step 5: Commit**

```bash
git add android/app/src/main/java/com/mdp/grp11/ui/ArenaCanvas.kt \
        android/app/src/test/java/com/mdp/grp11/ui/HitTestTest.kt
git commit -m "feat(android): add arena canvas with radius hit-testing"
```

---

## Task 13: ControlPad and FaceCompass

**Files:**
- Create: `android/app/src/main/java/com/mdp/grp11/ui/ControlPad.kt`
- Create: `android/app/src/main/java/com/mdp/grp11/ui/FaceCompass.kt`

**Interfaces:**
- Consumes: `Config.moveTokens`, `Face`, `MdpTokens`
- Produces: `@Composable fun ControlPad(enabled: Boolean, onMove: (String) -> Unit, onStop: () -> Unit, modifier)`; `@Composable fun FaceCompass(label: String, current: Face?, onPick: (Face) -> Unit, onDone: () -> Unit, modifier)`

Every touch target here is **at least 56.dp** — 48dp is the floor and these are the controls used under time pressure.

- [ ] **Step 1: Write ControlPad**

```kotlin
package com.mdp.grp11.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.mdp.grp11.config.Config
import com.mdp.grp11.ui.theme.MdpTokens

/**
 * Six-way, because the car is Ackermann - it cannot strafe or turn on the spot.
 * The AMD tool's vocabulary has no forward-arc, so map our six onto its six
 * slots (see the spec's AMD integration section); every button then produces
 * visible motion, which is what C.3 tests.
 */
@Composable
fun ControlPad(
    enabled: Boolean,
    onMove: (String) -> Unit,
    onStop: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val t = Config.moveTokens
    Column(modifier, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            PadButton("FL", enabled, Modifier.weight(1f)) { onMove(t.rotateLeft) }
            PadButton("F", enabled, Modifier.weight(1f)) { onMove(t.forward) }
            PadButton("FR", enabled, Modifier.weight(1f)) { onMove(t.rotateRight) }
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            PadButton("BL", enabled, Modifier.weight(1f)) { onMove(t.strafeLeft) }
            PadButton("B", enabled, Modifier.weight(1f)) { onMove(t.reverse) }
            PadButton("BR", enabled, Modifier.weight(1f)) { onMove(t.strafeRight) }
        }
        Button(
            onClick = onStop,
            enabled = enabled,
            colors = ButtonDefaults.buttonColors(containerColor = MdpTokens.Pink),
            modifier = Modifier.fillMaxWidth().height(56.dp),
        ) { Text("STOP") }
    }
}

@Composable
private fun PadButton(
    label: String,
    enabled: Boolean,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    Button(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.height(56.dp).padding(0.dp),
    ) { Text(label) }
}
```

- [ ] **Step 2: Write FaceCompass**

```kotlin
package com.mdp.grp11.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.mdp.grp11.protocol.Face
import com.mdp.grp11.ui.theme.MdpTokens

/**
 * C.7 alternative interaction. A block face is 4.7mm x 1mm on this screen, so
 * edge-tapping is impossible; the checklist explicitly allows another method
 * provided it stays touch-based. Keys are 56dp.
 *
 * Tapping the active face clears it (emits FACE,...,NONE).
 */
@Composable
fun FaceCompass(
    label: String,
    current: Face?,
    onPick: (Face) -> Unit,
    onDone: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text("IMAGE FACE · $label")
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Box(Modifier.weight(1f))
            FaceKey("N", current == Face.N, Modifier.weight(1f)) { onPick(Face.N) }
            Box(Modifier.weight(1f))
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            FaceKey("W", current == Face.W, Modifier.weight(1f)) { onPick(Face.W) }
            Button(
                onClick = onDone,
                colors = ButtonDefaults.buttonColors(containerColor = MdpTokens.Green),
                modifier = Modifier.weight(1f).height(56.dp),
            ) { Text("OK") }
            FaceKey("E", current == Face.E, Modifier.weight(1f)) { onPick(Face.E) }
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Box(Modifier.weight(1f))
            FaceKey("S", current == Face.S, Modifier.weight(1f)) { onPick(Face.S) }
            Box(Modifier.weight(1f))
        }
    }
}

@Composable
private fun FaceKey(
    label: String,
    active: Boolean,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    Button(
        onClick = onClick,
        colors = ButtonDefaults.buttonColors(
            containerColor = if (active) MdpTokens.Yellow else MdpTokens.Cream
        ),
        modifier = modifier.height(56.dp),
    ) { Text(label, color = MdpTokens.Ink) }
}
```

- [ ] **Step 3: Verify it compiles**

Run: `cd android && ./gradlew :app:compileDebugKotlin`
Expected: `BUILD SUCCESSFUL`

- [ ] **Step 4: Commit**

```bash
git add android/app/src/main/java/com/mdp/grp11/ui/ControlPad.kt \
        android/app/src/main/java/com/mdp/grp11/ui/FaceCompass.kt
git commit -m "feat(android): add control pad and face compass"
```

---

## Task 14: StatusPanel, BtLogPanel and image labels

**Files:**
- Create: `android/app/src/main/java/com/mdp/grp11/protocol/ImagePool.kt`
- Create: `android/app/src/main/java/com/mdp/grp11/ui/StatusPanel.kt`
- Create: `android/app/src/main/java/com/mdp/grp11/ui/BtLogPanel.kt`
- Test: `android/app/src/test/java/com/mdp/grp11/protocol/ImagePoolTest.kt`

**Interfaces:**
- Consumes: `TrafficLine`, `MdpTokens`
- Produces: `fun imageLabel(id: Int): String`; `@Composable fun StatusPanel(status: String?, targetLine: String?, modifier)`; `@Composable fun BtLogPanel(lines: List<TrafficLine>, modifier)`

- [ ] **Step 1: Write the failing image pool test**

`android/app/src/test/java/com/mdp/grp11/protocol/ImagePoolTest.kt`:

```kotlin
package com.mdp.grp11.protocol

import org.junit.Assert.assertEquals
import org.junit.Test

class ImagePoolTest {

    @Test fun `digits map to 11 through 19`() {
        assertEquals("digit 1", imageLabel(11))
        assertEquals("digit 9", imageLabel(19))
    }

    @Test fun `letters skip I through R`() {
        assertEquals("letter A", imageLabel(20))
        assertEquals("letter H", imageLabel(27))
        assertEquals("letter S", imageLabel(28))
        assertEquals("letter Z", imageLabel(35))
    }

    @Test fun `arrows and stop occupy 36 to 40`() {
        assertEquals("up arrow", imageLabel(36))
        assertEquals("left arrow", imageLabel(39))
        assertEquals("stop", imageLabel(40))
    }

    @Test fun `ids outside the pool get a label rather than an error`() {
        assertEquals("unrecognised id", imageLabel(4))
        assertEquals("unrecognised id", imageLabel(99))
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests "*ImagePoolTest*"`
Expected: FAIL — `Unresolved reference: imageLabel`

- [ ] **Step 3: Write the implementation**

`android/app/src/main/java/com/mdp/grp11/protocol/ImagePool.kt`:

```kotlin
package com.mdp.grp11.protocol

/**
 * Image pool from MDP briefing(1).pdf p.15. IDs 11-40, thirty images.
 * The letters deliberately skip I through R.
 *
 * Used for the STATUS LINE only. C.9 requires the obstacle block itself to
 * display the numeric Target ID.
 */
private val IMAGE_LABELS: Map<Int, String> = buildMap {
    (11..19).forEach { put(it, "digit ${it - 10}") }
    "ABCDEFGH".forEachIndexed { i, c -> put(20 + i, "letter $c") }
    "STUVWXYZ".forEachIndexed { i, c -> put(28 + i, "letter $c") }
    put(36, "up arrow")
    put(37, "down arrow")
    put(38, "right arrow")
    put(39, "left arrow")
    put(40, "stop")
}

fun imageLabel(id: Int): String = IMAGE_LABELS[id] ?: "unrecognised id"
```

`android/app/src/main/java/com/mdp/grp11/ui/StatusPanel.kt`:

```kotlin
package com.mdp.grp11.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Card
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.mdp.grp11.ui.theme.MdpTokens

/**
 * C.4: "must only display selective information and not all the text data
 * that is being streamed". This shows MSG payloads and the last target only.
 * The raw stream lives in BtLogPanel.
 */
@Composable
fun StatusPanel(status: String?, targetLine: String?, modifier: Modifier = Modifier) {
    Card(modifier) {
        Column(Modifier.padding(12.dp)) {
            Text("STATUS", color = MdpTokens.Muted)
            Text(status ?: "Idle")
            if (targetLine != null) Text(targetLine, color = MdpTokens.Muted)
        }
    }
}
```

`android/app/src/main/java/com/mdp/grp11/ui/BtLogPanel.kt`:

```kotlin
package com.mdp.grp11.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import com.mdp.grp11.connection.TrafficLine
import com.mdp.grp11.ui.theme.MdpTokens

/**
 * C.1 evidence: bidirectional text, visibly both ways. Deliberately separate
 * from StatusPanel, which C.4 requires to be filtered.
 */
@Composable
fun BtLogPanel(lines: List<TrafficLine>, modifier: Modifier = Modifier) {
    Card(modifier) {
        Column(Modifier.padding(12.dp)) {
            Text("BLUETOOTH LOG · RAW", color = MdpTokens.Muted)
            LazyColumn {
                items(lines) { line ->
                    Row {
                        Text(
                            if (line.outbound) "TX " else "RX ",
                            fontFamily = FontFamily.Monospace,
                            color = if (line.outbound) MdpTokens.Yellow else MdpTokens.Green,
                        )
                        Text(
                            line.text + if (!line.delivered) "  (not sent)" else "",
                            fontFamily = FontFamily.Monospace,
                        )
                    }
                }
            }
        }
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests "*ImagePoolTest*"`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
git add android/app/src/main/java/com/mdp/grp11/protocol/ImagePool.kt \
        android/app/src/main/java/com/mdp/grp11/ui/StatusPanel.kt \
        android/app/src/main/java/com/mdp/grp11/ui/BtLogPanel.kt \
        android/app/src/test/java/com/mdp/grp11/protocol/ImagePoolTest.kt
git commit -m "feat(android): add status panel, raw log panel and image pool labels"
```

---

## Task 15: ArenaViewModel

**Files:**
- Create: `android/app/src/main/java/com/mdp/grp11/ui/ArenaViewModel.kt`
- Test: `android/app/src/test/java/com/mdp/grp11/ui/ArenaViewModelTest.kt`

**Interfaces:**
- Consumes: `ConnectionRepository`, `Arena`, `Cell`, `Outbound`, `Inbound`, `imageLabel`
- Produces: `class ArenaViewModel(repo: ConnectionRepository, scope: CoroutineScope)` with `val arena: StateFlow<Arena>`, `val selectedId: StateFlow<Int?>`, `val statusText: StateFlow<String?>`, `val targetLine: StateFlow<String?>`, `val traffic: StateFlow<List<TrafficLine>>`, and `fun place(cell)`, `fun select(id)`, `fun dragTo(id, cell)`, `fun commit(id)`, `fun dropOutside(id)`, `fun pickFace(face)`, `fun clearSelection()`, `fun move(token)`

The **commit-on-lift rule** lives here: `place` and `dragTo` change local state only; `commit` is the only thing that emits `ADD`, and only when the cell actually changed.

- [ ] **Step 1: Write the failing tests**

`android/app/src/test/java/com/mdp/grp11/ui/ArenaViewModelTest.kt`:

```kotlin
package com.mdp.grp11.ui

import com.mdp.grp11.arena.Cell
import com.mdp.grp11.connection.ConnectionRepository
import com.mdp.grp11.protocol.Face
import com.mdp.grp11.transport.ConnectTarget
import com.mdp.grp11.transport.DeviceInfo
import com.mdp.grp11.transport.FakeTransport
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class ArenaViewModelTest {

    private val device = DeviceInfo("AMD-TOOL", "3C:5A:B4:11:88:F2")

    private fun TestScope.viewModel(fake: FakeTransport): ArenaViewModel {
        val repo = ConnectionRepository(fake, this)
        return ArenaViewModel(repo, this)
    }

    @Test fun `placing does not transmit until commit`() = runTest {
        val fake = FakeTransport()
        val repo = ConnectionRepository(fake, TestScope(testScheduler))
        repo.connect(ConnectTarget.Client(device))
        val vm = ArenaViewModel(repo, TestScope(testScheduler))

        vm.place(Cell(10, 6))
        assertTrue("nothing should be sent on placement", fake.sent.isEmpty())

        vm.commit(1)
        assertEquals(listOf("ADD,B1,(10,6)"), fake.sent)
    }

    @Test fun `committing an unmoved block sends nothing`() = runTest {
        val fake = FakeTransport()
        val repo = ConnectionRepository(fake, TestScope(testScheduler))
        repo.connect(ConnectTarget.Client(device))
        val vm = ArenaViewModel(repo, TestScope(testScheduler))

        vm.place(Cell(10, 6))
        vm.commit(1)
        val after = fake.sent.size

        vm.select(1)
        vm.commit(1)
        assertEquals("a bare select must not re-announce", after, fake.sent.size)
    }

    @Test fun `dragging out removes and sends SUB`() = runTest {
        val fake = FakeTransport()
        val repo = ConnectionRepository(fake, TestScope(testScheduler))
        repo.connect(ConnectTarget.Client(device))
        val vm = ArenaViewModel(repo, TestScope(testScheduler))

        vm.place(Cell(10, 6)); vm.commit(1)
        vm.dropOutside(1)

        assertTrue(vm.arena.value.obstacles.isEmpty())
        assertTrue(fake.sent.contains("SUB,B1"))
    }

    @Test fun `picking a face sends FACE with the coordinate`() = runTest {
        val fake = FakeTransport()
        val repo = ConnectionRepository(fake, TestScope(testScheduler))
        repo.connect(ConnectTarget.Client(device))
        val vm = ArenaViewModel(repo, TestScope(testScheduler))

        vm.place(Cell(14, 15)); vm.commit(1)
        vm.select(1)
        vm.pickFace(Face.E)
        assertTrue(fake.sent.contains("FACE,B1,(14,15),E"))
    }

    @Test fun `picking the active face again clears it`() = runTest {
        val fake = FakeTransport()
        val repo = ConnectionRepository(fake, TestScope(testScheduler))
        repo.connect(ConnectTarget.Client(device))
        val vm = ArenaViewModel(repo, TestScope(testScheduler))

        vm.place(Cell(14, 15)); vm.commit(1)
        vm.select(1)
        vm.pickFace(Face.E)
        vm.pickFace(Face.E)
        assertTrue(fake.sent.contains("FACE,B1,(14,15),NONE"))
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests "*ArenaViewModelTest*"`
Expected: FAIL — `Unresolved reference: ArenaViewModel`

- [ ] **Step 3: Write the implementation**

```kotlin
package com.mdp.grp11.ui

import androidx.lifecycle.ViewModel
import com.mdp.grp11.arena.Arena
import com.mdp.grp11.arena.Cell
import com.mdp.grp11.connection.ConnectionRepository
import com.mdp.grp11.connection.TrafficLine
import com.mdp.grp11.protocol.Face
import com.mdp.grp11.protocol.Inbound
import com.mdp.grp11.protocol.Outbound
import com.mdp.grp11.protocol.imageLabel
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class ArenaViewModel(
    private val repo: ConnectionRepository,
    private val scope: CoroutineScope,
) : ViewModel() {

    private val _arena = MutableStateFlow(Arena())
    val arena: StateFlow<Arena> = _arena.asStateFlow()

    private val _selectedId = MutableStateFlow<Int?>(null)
    val selectedId: StateFlow<Int?> = _selectedId.asStateFlow()

    private val _statusText = MutableStateFlow<String?>(null)
    val statusText: StateFlow<String?> = _statusText.asStateFlow()

    private val _targetLine = MutableStateFlow<String?>(null)
    val targetLine: StateFlow<String?> = _targetLine.asStateFlow()

    private val _traffic = MutableStateFlow<List<TrafficLine>>(emptyList())
    val traffic: StateFlow<List<TrafficLine>> = _traffic.asStateFlow()

    /** Cell each obstacle occupied when its drag began, so commit knows if it moved. */
    private val dragOrigin = mutableMapOf<Int, Cell?>()

    init {
        scope.launch { repo.inbound.collect(::onInbound) }
        scope.launch {
            repo.traffic.collect { line -> _traffic.value = (listOf(line) + _traffic.value).take(200) }
        }
    }

    private fun onInbound(msg: Inbound) {
        when (msg) {
            is Inbound.Status -> _statusText.value = msg.text
            is Inbound.TargetFound -> {
                _arena.value = _arena.value.applyTarget(msg.obstacle, msg.targetId, msg.face)
                // Block shows the ID (C.9); the symbol goes here so a supervisor
                // can judge correctness without the lookup table.
                _targetLine.value =
                    "Target ${msg.targetId} · ${imageLabel(msg.targetId)} · at B${msg.obstacle}"
            }
            is Inbound.Pose -> _arena.value = _arena.value.applyPose(msg.x, msg.y, msg.heading)
            is Inbound.Unknown -> Unit   // already in the raw log
        }
    }

    fun place(cell: Cell) {
        val (next, placed) = _arena.value.place(cell)
        _arena.value = next
        if (placed != null) {
            _selectedId.value = placed.id
            dragOrigin[placed.id] = null      // null origin == newly placed
        }
    }

    fun select(id: Int) {
        _selectedId.value = id
        dragOrigin[id] = _arena.value.obstacle(id)?.cell
    }

    fun dragTo(id: Int, cell: Cell) {
        if (!dragOrigin.containsKey(id)) dragOrigin[id] = _arena.value.obstacle(id)?.cell
        _arena.value = _arena.value.move(id, cell)
    }

    /** The ONLY place ADD is transmitted. C.6 requires it on finger-lift. */
    fun commit(id: Int) {
        val o = _arena.value.obstacle(id) ?: return
        val origin = dragOrigin[id]
        val isNew = dragOrigin.containsKey(id) && origin == null
        if (isNew || (origin != null && origin != o.cell)) {
            scope.launch { repo.send(Outbound.AddObstacle(o.id, o.cell.x, o.cell.y)) }
        }
        dragOrigin.remove(id)
    }

    fun dropOutside(id: Int) {
        _arena.value = _arena.value.remove(id)
        if (_selectedId.value == id) _selectedId.value = null
        dragOrigin.remove(id)
        scope.launch { repo.send(Outbound.RemoveObstacle(id)) }
    }

    fun pickFace(face: Face) {
        val id = _selectedId.value ?: return
        val o = _arena.value.obstacle(id) ?: return
        val next = if (o.imageFace == face) null else face
        _arena.value = _arena.value.setFace(id, next)
        scope.launch { repo.send(Outbound.SetFace(id, o.cell.x, o.cell.y, next)) }
    }

    fun clearSelection() { _selectedId.value = null }

    fun move(token: String) {
        scope.launch { repo.send(Outbound.Move(token)) }
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests "*ArenaViewModelTest*"`
Expected: PASS, 5 tests

- [ ] **Step 5: Commit**

```bash
git add android/app/src/main/java/com/mdp/grp11/ui/ArenaViewModel.kt \
        android/app/src/test/java/com/mdp/grp11/ui/ArenaViewModelTest.kt
git commit -m "feat(android): add ArenaViewModel with commit-on-lift semantics"
```

---

## Task 16: DevicePickerSheet and MainScreen

**Files:**
- Create: `android/app/src/main/java/com/mdp/grp11/ui/DevicePickerSheet.kt`
- Create: `android/app/src/main/java/com/mdp/grp11/ui/MainScreen.kt`
- Create: `android/app/src/main/java/com/mdp/grp11/MdpApplication.kt`
- Modify: `android/app/src/main/java/com/mdp/grp11/MainActivity.kt`
- Modify: `android/app/src/main/AndroidManifest.xml` (add `android:name=".MdpApplication"`)

**Interfaces:**
- Consumes: everything above
- Produces: a running app

- [ ] **Step 1: Write the application container**

```kotlin
package com.mdp.grp11

import android.app.Application
import com.mdp.grp11.connection.ConnectionRepository
import com.mdp.grp11.transport.BluetoothSppTransport
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob

/**
 * Application-scoped so the connection and the arena outlive every ViewModel:
 * a rotation or a reconnect must not lose the course you just laid out.
 */
class MdpApplication : Application() {

    lateinit var appScope: CoroutineScope
        private set
    lateinit var transport: BluetoothSppTransport
        private set
    lateinit var connection: ConnectionRepository
        private set

    override fun onCreate() {
        super.onCreate()
        appScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
        transport = BluetoothSppTransport(this)
        connection = ConnectionRepository(transport, appScope)
    }
}
```

- [ ] **Step 2: Write DevicePickerSheet**

```kotlin
package com.mdp.grp11.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import com.mdp.grp11.transport.DeviceInfo

/** C.2: scan, select, connect. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DevicePickerSheet(
    devices: List<DeviceInfo>,
    onConnect: (DeviceInfo) -> Unit,
    onListen: () -> Unit,
    onDismiss: () -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Connect to device")
            devices.forEach { d ->
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column {
                        Text(d.name)
                        Text(d.address, fontFamily = FontFamily.Monospace)
                    }
                    Button(onClick = { onConnect(d) }, modifier = Modifier.height(56.dp)) {
                        Text("CONNECT")
                    }
                }
            }
            Button(onClick = onListen, modifier = Modifier.fillMaxWidth().height(56.dp)) {
                Text("WAIT FOR INCOMING (AMD)")
            }
        }
    }
}
```

- [ ] **Step 3: Write MainScreen and wire MainActivity**

`MainScreen.kt`:

```kotlin
package com.mdp.grp11.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.weight
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.clickable
import com.mdp.grp11.config.Config
import com.mdp.grp11.connection.ConnectionState

@Composable
fun MainScreen(vm: ArenaViewModel, state: ConnectionState, onOpenPicker: () -> Unit) {
    val arena by vm.arena.collectAsState()
    val selected by vm.selectedId.collectAsState()
    val status by vm.statusText.collectAsState()
    val targetLine by vm.targetLine.collectAsState()
    val traffic by vm.traffic.collectAsState()

    val connected = state is ConnectionState.Connected

    Row(Modifier.fillMaxSize().padding(12.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        ArenaCanvas(
            arena = arena,
            selectedId = selected,
            onPlace = vm::place,
            onSelect = vm::select,
            onDragTo = vm::dragTo,
            onDropOutside = vm::dropOutside,
            onCommit = vm::commit,
            modifier = Modifier.fillMaxHeight().aspectRatio(1f),
        )
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(
                connectionLabel(state),
                modifier = Modifier.fillMaxWidth().clickable { onOpenPicker() },
            )
            Text("OBSTACLES ${arena.obstacles.size} / 8")
            ControlPad(enabled = connected, onMove = vm::move, onStop = { vm.move(Config.moveTokens.stop) })
            val sel = selected?.let { arena.obstacle(it) }
            if (sel != null) {
                FaceCompass(
                    label = "B${sel.id}",
                    current = sel.imageFace,
                    onPick = vm::pickFace,
                    onDone = vm::clearSelection,
                )
            } else {
                StatusPanel(status, targetLine, Modifier.fillMaxWidth())
            }
            BtLogPanel(traffic, Modifier.fillMaxWidth().weight(1f))
        }
    }
}

private fun connectionLabel(state: ConnectionState): String = when (state) {
    is ConnectionState.Idle -> "NOT CONNECTED"
    is ConnectionState.Connecting -> "CONNECTING…"
    is ConnectionState.Connected -> state.device.name
    is ConnectionState.Reconnecting -> "RECONNECTING · RETRY ${state.attempt}"
    is ConnectionState.Failed -> "FAILED · ${state.reason}"
}
```

`MainActivity.kt` (replace the Task 1 stub):

```kotlin
package com.mdp.grp11

import android.Manifest
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.lifecycle.lifecycleScope
import com.mdp.grp11.transport.ConnectTarget
import com.mdp.grp11.ui.ArenaViewModel
import com.mdp.grp11.ui.DevicePickerSheet
import com.mdp.grp11.ui.MainScreen
import com.mdp.grp11.ui.theme.MdpTheme
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {

    private val permissions = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { /* state is reflected in the UI; nothing to do here */ }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val app = application as MdpApplication

        permissions.launch(
            arrayOf(
                Manifest.permission.BLUETOOTH_CONNECT,
                Manifest.permission.BLUETOOTH_SCAN,
                Manifest.permission.BLUETOOTH_ADVERTISE,
            )
        )

        val vm = ArenaViewModel(app.connection, app.appScope)

        setContent {
            MdpTheme {
                var showPicker by remember { mutableStateOf(false) }
                val state by app.connection.state.collectAsState()

                MainScreen(vm, state, onOpenPicker = { showPicker = true })

                if (showPicker) {
                    DevicePickerSheet(
                        devices = app.transport.bondedDevices(),
                        onConnect = { d ->
                            showPicker = false
                            lifecycleScope.launch {
                                app.connection.connect(ConnectTarget.Client(d))
                            }
                        },
                        onListen = {
                            showPicker = false
                            lifecycleScope.launch {
                                app.connection.connect(ConnectTarget.Listen)
                            }
                        },
                        onDismiss = { showPicker = false },
                    )
                }
            }
        }
    }
}
```

Add `android:name=".MdpApplication"` to the `<application>` tag in the manifest.

- [ ] **Step 4: Build and install on the tablet**

Run: `cd android && ./gradlew :app:installDebug`
Expected: app launches in landscape, arena grid visible, tapping empty cells places numbered blocks, dragging moves them, dragging off the edge removes them, tapping a block opens the compass.

- [ ] **Step 5: Run the whole suite**

Run: `cd android && ./gradlew :app:testDebugUnitTest`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add android/
git commit -m "feat(android): wire main screen, device picker and application container"
```

---

## Task 17: AMD tool send script

**Files:**
- Create: `AMDTOOL/scripts/mdp_grp11.cs`

**Interfaces:**
- Consumes: nothing (runs inside the AMD tool, not the app)
- Produces: AMD emitting `ROBOT,<x>,<y>,<N|S|E|W>` and `ADDOBSTACLE`-equivalent lines our decoder understands

Without this, C.9 and C.10 cannot be demonstrated against AMD — none of the shipped scripts emit our formats.

- [ ] **Step 1: Write the script**

```csharp
using System;
namespace ScriptNs
{
    public class ScriptContainer
    {
        // Emits the checklist's own formats so the Android app needs no
        // AMD-specific parsing.
        //
        // Two conversions are required:
        //  1. AMD's origin is TOP-LEFT with y increasing downward; the arena's
        //     is BOTTOM-LEFT with y increasing upward.
        //  2. AMD's direction is an ANGLE in degrees, North = 0, increasing
        //     clockwise. The checklist wants a letter.
        public static string MainScript(
            int[,] gridLayout,
            int[] robotPosition,
            bool posTgridF,
            bool addObstacle,
            int[] obstaclePosition)
        {
            int height = gridLayout.GetLength(1);

            if (posTgridF)
            {
                int x = robotPosition[0];
                int y = height - 1 - robotPosition[1];
                string dir = HeadingLetter(robotPosition[2]);
                return "ROBOT," + x + "," + y + "," + dir;
            }

            int ox = obstaclePosition[0];
            int oy = height - 1 - obstaclePosition[1];
            // AMD gives no obstacle number, so send position only; the app logs
            // it as Unknown rather than guessing an id.
            return (addObstacle ? "AMDADD," : "AMDSUB,") + "(" + ox + "," + oy + ")";
        }

        private static string HeadingLetter(int degrees)
        {
            int d = ((degrees % 360) + 360) % 360;
            if (d >= 315 || d < 45) return "N";
            if (d < 135) return "E";
            if (d < 225) return "S";
            return "W";
        }
    }
}
```

- [ ] **Step 2: Load and verify in the AMD tool**

1. AMD tool → Settings → **Default Arena Settings** → set Arena width **20**, Arena height **20**, Robot size 3.
2. Settings → **Custom Scripts** → load `AMDTOOL/scripts/mdp_grp11.cs`.
3. Settings → **Received Commands** → set FORWARD `f`, REVERSE `r`, ROTATE LEFT `tl`, ROTATE RIGHT `tr`, STRAFE LEFT `sl`, STRAFE RIGHT `sr` (match `Config.moveTokens`).
4. Connect to the tablet, drag AMD's virtual robot, and confirm the app's raw log shows `RX ROBOT,<x>,<y>,<letter>` and the robot moves to the matching cell.

Expected: the cell the app draws matches the cell AMD shows. If it is mirrored vertically, the y-flip in the script is wrong.

- [ ] **Step 3: Commit**

```bash
git add AMDTOOL/scripts/mdp_grp11.cs
git commit -m "feat(amd): add send script emitting the checklist protocol"
```

---

## Task 18: Checklist demo scripts

**Files:**
- Create: `docs/checklist-demos.md`

**Interfaces:**
- Consumes: the finished app
- Produces: a per-item demo script, used both for supervisor sign-off and as the video shot list

- [ ] **Step 1: Write the document**

Create `docs/checklist-demos.md` with one section per item. Each section has **Setup**, **Steps**, **Expected**, and a **Contributor** line (checklist items require contributor names — AGENTS.md §9.2 rule 7). Use this structure, filled in for every item C.1 through C.10:

```markdown
## C.1 — Bidirectional text over Bluetooth

**Setup:** AMD tool running on device B, arena set to 20×20, app installed on the tablet.

**Steps:**
1. In the app, open the device picker and tap `WAIT FOR INCOMING (AMD)`.
2. In AMD, Bluetooth → Scan For Devices → select the tablet → connect.
3. In AMD's `SEND TO REMOTE` box, type `MSG,[Hello]` and press SEND.
4. In the app, tap an empty arena cell and lift your finger.

**Expected:**
- App's raw log shows `RX MSG,[Hello]`; status panel shows `Hello`.
- AMD's `RECEIVED TEXT` panel shows `ADD,B1,(x,y)` with the cell you tapped.

**Contributor:** ______________________
```

Repeat for C.2 (scan/select/connect), C.3 (each pad button moves AMD's virtual robot),
C.4 (status shows only the `MSG` payload, not the raw stream), C.5 (numbered blocks and robot
heading visible), C.6 (place, drag, drag-out; messages fire only on lift), C.7 (compass sets a
face, block appearance changes, `FACE` transmitted), C.8 (**Disconnect** in AMD, app shows
`RECONNECTING · RETRY n` and stays responsive; **Connect** again in AMD and the app recovers with
no taps), C.9 (`TARGET,B2,11` then `TARGET,B2,11,N` from AMD change the block), C.10
(`ROBOT,7,2,E` moves and rotates the robot).

- [ ] **Step 2: Commit**

```bash
git add docs/checklist-demos.md
git commit -m "docs: add per-item checklist demo scripts"
```

---

## Self-Review Notes

**Spec coverage.** Every section of the spec maps to a task: §3 architecture → Tasks 1–2; §4
transport → Tasks 7–10; §5 codec → Tasks 5–6; §6 arena → Tasks 3–4; §7 UI → Tasks 11–16; §8 error
handling → the behaviour is asserted in the Task 4, 5, 9 and 15 tests; §9 testing → the test files
throughout; §10 AMD integration → Task 17; §12 demos → Task 18.

**Two spec items are deliberately deferred and are NOT in this plan.** Neither is needed for
checklist sign-off, and both are cheap to add afterwards:

- **`session/RunTimer.kt` and `SessionLog` export.** The run timer and log export are scope beyond
  C.1–C.10. `BtLogPanel` already holds the last 200 traffic lines in memory, so export is a file
  write on top of existing state.
- **`arena/ArenaStore.kt` (DataStore persistence).** Spec §8 calls for persisting the arena across
  process death. The DataStore dependency is already in the version catalog.

Add both as Tasks 19 and 20 before week 7 if time allows; raise them with the user if the timer is
wanted for the video.

**Known caveat in Task 12.** `ArenaCanvas` uses both `detectTapGestures` and `detectDragGestures`
in separate `pointerInput` modifiers. If they interfere on device (a slow tap being consumed as a
zero-distance drag), merge them into one `awaitPointerEventScope` block — the ViewModel semantics
do not change, only the gesture plumbing.

---

# AMENDMENT — 2026-08-21 (post comparison with two prior-year implementations)

Two prior-year apps for this same module were reviewed. Both independently built four things this
plan lacked. Three of them are not checklist items — they are what a competition run actually needs —
and one closes a genuine C.2 gap.

**Supersedes the "two spec items deliberately deferred" note in the Self-Review section below.** The
run timer and arena persistence are no longer deferred; they are Tasks 19 and 20.

| Addition | Why | Where |
|---|---|---|
| `ensureBonded()` + insecure-socket fallback | An unpaired device fails C.2 today | Task 10 (extended in place) |
| `beginExplore` / `beginFastest` / `sendArena` | **Nothing in the app can tell the robot to start a run** | Task 19 + Task 13 |
| Two run timers, one per graded task | Both tasks are scored on time; both prior groups built two | Task 19 + Task 16 |
| Arena save / load / reset | Re-entering 8 obstacles on 4.7 mm cells under a clock | Task 20 |

**Execution order:** Task 19 runs immediately after Task 10, before the UI tasks, because Tasks 13
and 16 consume what it produces.

## Amendment to Task 13 (ControlPad and FaceCompass)

Add a third composable to the same task, `TaskControls`, in a new file
`android/app/src/main/java/com/mdp/grp11/ui/TaskControls.kt`:

```kotlin
package com.mdp.grp11.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.mdp.grp11.config.Config
import com.mdp.grp11.session.RunKind
import com.mdp.grp11.ui.theme.MdpTokens

/**
 * Task-level commands. Without these the app can drive the robot manually but
 * cannot tell it to begin a run, which is what a competition round consists of.
 * The tokens match the AMD tool's Received Commands slots of the same names.
 */
@Composable
fun TaskControls(
    enabled: Boolean,
    running: RunKind?,
    onStart: (RunKind) -> Unit,
    onStop: () -> Unit,
    onSendArena: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(
                onClick = { onStart(RunKind.Exploration) },
                enabled = enabled && running == null,
                colors = ButtonDefaults.buttonColors(containerColor = MdpTokens.Green),
                modifier = Modifier.weight(1f).height(56.dp),
            ) { Text("IMAGE REC") }
            Button(
                onClick = { onStart(RunKind.FastestCar) },
                enabled = enabled && running == null,
                colors = ButtonDefaults.buttonColors(containerColor = MdpTokens.Blue),
                modifier = Modifier.weight(1f).height(56.dp),
            ) { Text("FASTEST") }
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(
                onClick = onSendArena,
                enabled = enabled,
                modifier = Modifier.weight(1f).height(56.dp),
            ) { Text("SEND ARENA") }
            OutlinedButton(
                onClick = onStop,
                enabled = enabled && running != null,
                modifier = Modifier.weight(1f).height(56.dp),
            ) { Text("END RUN") }
        }
    }
}
```

The start buttons must send `Config.taskTokens.beginExploration` / `.beginFastest` and
`Config.taskTokens.sendArena` — never inline the strings. Every control stays at 56.dp.

## Amendment to Task 16 (MainScreen wiring)

`MainScreen` additionally:

- renders `TaskControls` above `ControlPad`;
- renders the two elapsed times from `ArenaViewModel.runTimes` as `mm:ss`, labelled IMAGE REC and
  FASTEST, with the currently-running one visually emphasised;
- renders an arena toolbar row (Task 20's `ArenaToolbar`) above the canvas.

`MdpApplication` gains an `ArenaStore` instance built on the application `Context`, passed to
`ArenaViewModel` alongside the repository. Its `appScope` uses
`SupervisorJob() + Dispatchers.Main.immediate` — NOT `Dispatchers.IO` (ruling R16: the repository's
job fields are unsynchronised and are only safe on a confined dispatcher).

---

## Task 19: Task-start commands and run timers

**Files:**
- Modify: `android/app/src/main/java/com/mdp/grp11/config/Config.kt`
- Create: `android/app/src/main/java/com/mdp/grp11/session/RunTimer.kt`
- Test: `android/app/src/test/java/com/mdp/grp11/session/RunTimerTest.kt`

**Interfaces:**
- Consumes: nothing
- Produces: `Config.TaskTokens` (`beginExploration`, `beginFastest`, `sendArena`) and `Config.taskTokens`; `enum class RunKind { Exploration, FastestCar }`; `data class RunTimes(val exploration: Long, val fastestCar: Long, val running: RunKind?)`; `class RunTimer(nowMs: () -> Long)` with `start(kind)`, `stop()`, `reset(kind)`, `times(): RunTimes`

`RunTimer` takes a clock function rather than calling `System.currentTimeMillis()` directly. That is
what makes it testable without sleeping, and it is why this is pure Kotlin in `session/` rather than
something wired into a composable.

- [ ] **Step 1: Write the failing tests**

`android/app/src/test/java/com/mdp/grp11/session/RunTimerTest.kt`:

```kotlin
package com.mdp.grp11.session

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class RunTimerTest {

    private var clock = 0L
    private fun timer() = RunTimer { clock }

    @Test fun `a fresh timer is zero and idle`() {
        val t = timer()
        assertEquals(RunTimes(0L, 0L, null), t.times())
    }

    @Test fun `a running timer reports elapsed time`() {
        clock = 1_000
        val t = timer()
        t.start(RunKind.Exploration)
        clock = 4_500
        assertEquals(3_500L, t.times().exploration)
        assertEquals(0L, t.times().fastestCar)
        assertEquals(RunKind.Exploration, t.times().running)
    }

    @Test fun `stop freezes the elapsed value`() {
        clock = 0
        val t = timer()
        t.start(RunKind.Exploration)
        clock = 2_000
        t.stop()
        clock = 9_999
        assertEquals(2_000L, t.times().exploration)
        assertNull(t.times().running)
    }

    @Test fun `starting the other task banks the first one`() {
        clock = 0
        val t = timer()
        t.start(RunKind.Exploration)
        clock = 3_000
        t.start(RunKind.FastestCar)
        clock = 5_000
        assertEquals(3_000L, t.times().exploration)
        assertEquals(2_000L, t.times().fastestCar)
        assertEquals(RunKind.FastestCar, t.times().running)
    }

    @Test fun `resuming after stop accumulates rather than restarting`() {
        clock = 0
        val t = timer()
        t.start(RunKind.Exploration)
        clock = 2_000
        t.stop()
        clock = 10_000
        t.start(RunKind.Exploration)
        clock = 10_500
        assertEquals(2_500L, t.times().exploration)
    }

    @Test fun `reset zeroes only the named task`() {
        clock = 0
        val t = timer()
        t.start(RunKind.Exploration)
        clock = 3_000
        t.start(RunKind.FastestCar)
        clock = 5_000
        t.reset(RunKind.Exploration)
        assertEquals(0L, t.times().exploration)
        assertEquals(2_000L, t.times().fastestCar)
    }

    @Test fun `resetting the running task restarts its clock from now`() {
        clock = 0
        val t = timer()
        t.start(RunKind.Exploration)
        clock = 3_000
        t.reset(RunKind.Exploration)
        assertEquals(0L, t.times().exploration)
        clock = 4_000
        assertEquals(1_000L, t.times().exploration)
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests "*RunTimerTest*"`
Expected: FAIL — `Unresolved reference: RunTimer`

- [ ] **Step 3: Add the task tokens to Config**

Insert into `object Config`, directly after the existing `moveTokens` declaration:

```kotlin
    /**
     * Task-level commands, as distinct from movement. These match the AMD tool's
     * Settings -> Received Commands slots of the same names, and are what actually
     * starts a competition run.
     */
    data class TaskTokens(
        val beginExploration: String = "beginExplore",
        val beginFastest: String = "beginFastest",
        val sendArena: String = "sendArena",
    )

    val taskTokens = TaskTokens()
```

- [ ] **Step 4: Write RunTimer**

`android/app/src/main/java/com/mdp/grp11/session/RunTimer.kt`:

```kotlin
package com.mdp.grp11.session

enum class RunKind { Exploration, FastestCar }

data class RunTimes(
    val exploration: Long = 0L,
    val fastestCar: Long = 0L,
    val running: RunKind? = null,
)

/**
 * Two independent stopwatches, one per graded task. Both evaluation runs are
 * scored on time, so the tablet times them.
 *
 * Takes a clock function instead of reading the system clock, which is what
 * makes it testable without sleeping.
 */
class RunTimer(private val nowMs: () -> Long) {

    private val banked = mutableMapOf(
        RunKind.Exploration to 0L,
        RunKind.FastestCar to 0L,
    )
    private var running: RunKind? = null
    private var startedAt: Long = 0L

    /** Starts [kind]. Any other running task is stopped and its time banked. */
    fun start(kind: RunKind) {
        stop()
        running = kind
        startedAt = nowMs()
    }

    /** Banks the running task's elapsed time and goes idle. */
    fun stop() {
        val kind = running ?: return
        banked[kind] = (banked[kind] ?: 0L) + (nowMs() - startedAt)
        running = null
    }

    /** Zeroes [kind] only. If it is running, its clock restarts from now. */
    fun reset(kind: RunKind) {
        banked[kind] = 0L
        if (running == kind) startedAt = nowMs()
    }

    fun times(): RunTimes = RunTimes(
        exploration = elapsed(RunKind.Exploration),
        fastestCar = elapsed(RunKind.FastestCar),
        running = running,
    )

    private fun elapsed(kind: RunKind): Long {
        val base = banked[kind] ?: 0L
        return if (running == kind) base + (nowMs() - startedAt) else base
    }
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests "*RunTimerTest*"`
Expected: PASS, 7 tests

- [ ] **Step 6: Run the whole suite**

Run: `cd android && ./gradlew :app:testDebugUnitTest`
Expected: PASS — the Config change must not break anything

- [ ] **Step 7: Commit**

```bash
git add android/app/src/main/java/com/mdp/grp11/config/Config.kt \
        android/app/src/main/java/com/mdp/grp11/session/RunTimer.kt \
        android/app/src/test/java/com/mdp/grp11/session/RunTimerTest.kt
git commit -m "feat(android): add task-start tokens and per-task run timers"
```

---

## Task 20: Arena save, load and reset

**Files:**
- Create: `android/app/src/main/java/com/mdp/grp11/arena/ArenaCodec.kt`
- Create: `android/app/src/main/java/com/mdp/grp11/arena/ArenaStore.kt`
- Create: `android/app/src/main/java/com/mdp/grp11/ui/ArenaToolbar.kt`
- Test: `android/app/src/test/java/com/mdp/grp11/arena/ArenaCodecTest.kt`

**Interfaces:**
- Consumes: `Arena`, `Cell`, `Obstacle`, `Target`, `Face`
- Produces: `fun encodeArena(arena: Arena): String`; `fun decodeArena(text: String): Arena?`; `class ArenaStore(context: Context)` with `suspend save(name, arena)`, `suspend load(name): Arena?`, `suspend names(): List<String>`, `suspend delete(name)`; `@Composable fun ArenaToolbar(saved: List<String>, onSave: (String) -> Unit, onLoad: (String) -> Unit, onReset: () -> Unit, modifier)`

The serialisation is deliberately split from the storage: `ArenaCodec` is pure Kotlin and fully
testable, `ArenaStore` is a thin DataStore wrapper with no logic worth testing.

Format is line-based and human-readable so a broken save can be diagnosed by eye:

```
V1
R 1 1 N
O 1 4 13 N 11 N
O 2 9 7 - - -
```

`R` is the robot (x, y, heading), `O` is an obstacle (id, x, y, imageFace, targetId, targetFace),
and `-` means absent.

- [ ] **Step 1: Write the failing tests**

`android/app/src/test/java/com/mdp/grp11/arena/ArenaCodecTest.kt`:

```kotlin
package com.mdp.grp11.arena

import com.mdp.grp11.protocol.Face
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ArenaCodecTest {

    @Test fun `empty arena round-trips`() {
        val a = Arena()
        assertEquals(a, decodeArena(encodeArena(a)))
    }

    @Test fun `obstacles and robot round-trip`() {
        var a = Arena().place(Cell(4, 13)).first
        a = a.place(Cell(9, 7)).first
        a = a.applyPose(1, 1, Face.N)
        assertEquals(a, decodeArena(encodeArena(a)))
    }

    @Test fun `annotated face and reported target survive independently`() {
        var a = Arena().place(Cell(9, 7)).first
        a = a.setFace(1, Face.N)
        a = a.applyTarget(1, 11, Face.E)
        val back = decodeArena(encodeArena(a))!!
        val o = back.obstacle(1)!!
        assertEquals(Face.N, o.imageFace)
        assertEquals(11, o.target!!.id)
        assertEquals(Face.E, o.target!!.face)
    }

    @Test fun `a target with no face round-trips`() {
        var a = Arena().place(Cell(5, 5)).first
        a = a.applyTarget(1, 4, null)
        val back = decodeArena(encodeArena(a))!!
        assertEquals(4, back.obstacle(1)!!.target!!.id)
        assertNull(back.obstacle(1)!!.target!!.face)
    }

    @Test fun `ids are preserved rather than reallocated`() {
        var a = Arena().place(Cell(5, 5)).first
        a = a.place(Cell(6, 6)).first
        a = a.place(Cell(7, 7)).first
        a = a.remove(2)
        val back = decodeArena(encodeArena(a))!!
        assertEquals(listOf(1, 3), back.obstacles.map { it.id }.sorted())
    }

    @Test fun `malformed input decodes to null rather than throwing`() {
        val junk = listOf(
            "", "   ", "V2\n", "nonsense",
            "V1\nO 1 4\n", "V1\nO x y z - - -\n", "V1\nR 1 1\n", "V1\nR 1 1 Q\n",
        )
        junk.forEach { assertNull("expected null for '$it'", decodeArena(it)) }
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests "*ArenaCodecTest*"`
Expected: FAIL — `Unresolved reference: encodeArena`

- [ ] **Step 3: Write ArenaCodec**

`android/app/src/main/java/com/mdp/grp11/arena/ArenaCodec.kt`:

```kotlin
package com.mdp.grp11.arena

import com.mdp.grp11.protocol.Face

private const val VERSION = "V1"
private const val ABSENT = "-"

/** Line-based and human-readable, so a broken save can be diagnosed by eye. */
fun encodeArena(arena: Arena): String = buildString {
    appendLine(VERSION)
    arena.robot?.let { appendLine("R ${it.cell.x} ${it.cell.y} ${it.heading.name}") }
    arena.obstacles.sortedBy { it.id }.forEach { o ->
        append("O ${o.id} ${o.cell.x} ${o.cell.y} ")
        append(o.imageFace?.name ?: ABSENT)
        append(" ")
        append(o.target?.id?.toString() ?: ABSENT)
        append(" ")
        appendLine(o.target?.face?.name ?: ABSENT)
    }
}

/** Total: any malformed input returns null rather than throwing. */
fun decodeArena(text: String): Arena? {
    val lines = text.lines().map { it.trim() }.filter { it.isNotEmpty() }
    if (lines.isEmpty() || lines[0] != VERSION) return null

    var robot: RobotPose? = null
    val obstacles = mutableListOf<Obstacle>()

    for (line in lines.drop(1)) {
        val f = line.split(" ").filter { it.isNotEmpty() }
        when (f.getOrNull(0)) {
            "R" -> {
                if (f.size != 4) return null
                val x = f[1].toIntOrNull() ?: return null
                val y = f[2].toIntOrNull() ?: return null
                val h = Face.parse(f[3]) ?: return null
                robot = RobotPose(Cell(x, y), h)
            }
            "O" -> {
                if (f.size != 7) return null
                val id = f[1].toIntOrNull() ?: return null
                val x = f[2].toIntOrNull() ?: return null
                val y = f[3].toIntOrNull() ?: return null
                val imageFace = if (f[4] == ABSENT) null else Face.parse(f[4]) ?: return null
                val targetId = if (f[5] == ABSENT) null else f[5].toIntOrNull() ?: return null
                val targetFace = if (f[6] == ABSENT) null else Face.parse(f[6]) ?: return null
                obstacles += Obstacle(
                    id = id,
                    cell = Cell(x, y),
                    imageFace = imageFace,
                    target = targetId?.let { Target(it, targetFace) },
                )
            }
            else -> return null
        }
    }
    return Arena(obstacles = obstacles, robot = robot)
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests "*ArenaCodecTest*"`
Expected: PASS, 6 tests

- [ ] **Step 5: Write ArenaStore**

`android/app/src/main/java/com/mdp/grp11/arena/ArenaStore.kt`:

```kotlin
package com.mdp.grp11.arena

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.first

private val Context.arenaDataStore by preferencesDataStore(name = "arena_layouts")

/**
 * Named arena layouts. Re-entering eight obstacles on 4.7mm cells under a clock
 * is the failure mode this exists to prevent.
 */
class ArenaStore(private val context: Context) {

    suspend fun save(name: String, arena: Arena) {
        context.arenaDataStore.edit { it[stringPreferencesKey(name)] = encodeArena(arena) }
    }

    suspend fun load(name: String): Arena? {
        val text = context.arenaDataStore.data.first()[stringPreferencesKey(name)] ?: return null
        return decodeArena(text)
    }

    suspend fun names(): List<String> =
        context.arenaDataStore.data.first().asMap().keys.map { it.name }.sorted()

    suspend fun delete(name: String) {
        context.arenaDataStore.edit { it.remove(stringPreferencesKey(name)) }
    }
}
```

- [ ] **Step 6: Write ArenaToolbar**

`android/app/src/main/java/com/mdp/grp11/ui/ArenaToolbar.kt`:

```kotlin
package com.mdp.grp11.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

@Composable
fun ArenaToolbar(
    saved: List<String>,
    onSave: (String) -> Unit,
    onLoad: (String) -> Unit,
    onReset: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var showSave by remember { mutableStateOf(false) }
    var showLoad by remember { mutableStateOf(false) }
    var confirmReset by remember { mutableStateOf(false) }
    var name by remember { mutableStateOf("") }

    Row(modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedButton(
            onClick = { name = ""; showSave = true },
            modifier = Modifier.weight(1f).height(56.dp),
        ) { Text("SAVE") }

        OutlinedButton(
            onClick = { showLoad = true },
            enabled = saved.isNotEmpty(),
            modifier = Modifier.weight(1f).height(56.dp),
        ) { Text("LOAD") }

        OutlinedButton(
            onClick = { confirmReset = true },
            modifier = Modifier.weight(1f).height(56.dp),
        ) { Text("RESET") }

        DropdownMenu(expanded = showLoad, onDismissRequest = { showLoad = false }) {
            saved.forEach { n ->
                DropdownMenuItem(
                    text = { Text(n) },
                    onClick = { showLoad = false; onLoad(n) },
                )
            }
        }
    }

    if (showSave) {
        AlertDialog(
            onDismissRequest = { showSave = false },
            title = { Text("Save layout") },
            text = {
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    singleLine = true,
                    label = { Text("Name") },
                )
            },
            confirmButton = {
                TextButton(
                    onClick = { showSave = false; if (name.isNotBlank()) onSave(name.trim()) },
                ) { Text("SAVE") }
            },
            dismissButton = { TextButton(onClick = { showSave = false }) { Text("CANCEL") } },
        )
    }

    // Reset wipes a layout that took real effort to enter, so it is confirmed.
    if (confirmReset) {
        AlertDialog(
            onDismissRequest = { confirmReset = false },
            title = { Text("Clear the arena?") },
            text = { Text("Removes every obstacle. This cannot be undone.") },
            confirmButton = {
                TextButton(onClick = { confirmReset = false; onReset() }) { Text("CLEAR") }
            },
            dismissButton = { TextButton(onClick = { confirmReset = false }) { Text("CANCEL") } },
        )
    }
}
```

- [ ] **Step 7: Run the whole suite**

Run: `cd android && ./gradlew :app:testDebugUnitTest`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add android/app/src/main/java/com/mdp/grp11/arena/ArenaCodec.kt \
        android/app/src/main/java/com/mdp/grp11/arena/ArenaStore.kt \
        android/app/src/main/java/com/mdp/grp11/ui/ArenaToolbar.kt \
        android/app/src/test/java/com/mdp/grp11/arena/ArenaCodecTest.kt
git commit -m "feat(android): add arena save, load and reset"
```

---

## Amendment to Task 15 (ArenaViewModel)

`ArenaViewModel` additionally takes `runTimer: RunTimer` and `arenaStore: ArenaStore`, and exposes:

- `val runTimes: StateFlow<RunTimes>` — ticked every 250ms while a run is active
- `val savedLayouts: StateFlow<List<String>>`
- `fun startRun(kind: RunKind)` — starts the timer AND sends the matching task token
- `fun endRun()` — stops the timer
- `fun sendArena()` — sends `Config.taskTokens.sendArena`
- `fun saveLayout(name: String)`, `fun loadLayout(name: String)`, `fun resetArena()`

`startRun` must do both things: a start button that moves the robot without starting the clock, or
starts the clock without moving the robot, is worse than useless during a scored run.

`resetArena()` sets `_arena.value = Arena()` and clears `selectedId`. It does NOT transmit anything —
clearing the tablet's view of the arena is a local editing action, and the RPi learns the new layout
from the `ADD` messages that follow.
