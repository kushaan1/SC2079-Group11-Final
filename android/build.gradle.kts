plugins {
    alias(libs.plugins.android.application) apply false
    // NOTE: org.jetbrains.kotlin.android is intentionally NOT applied here.
    // AGP 9.x ships built-in Kotlin support; applying kotlin-android on top of it
    // fails with "Cannot add extension with name 'kotlin', as there is an
    // extension already registered with that name." See task-1-report.md.
    alias(libs.plugins.kotlin.compose) apply false
}
