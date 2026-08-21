package com.mdp.grp11.arena

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.first

/**
 * Named arena layouts. Re-entering eight obstacles on 4.7mm cells under a clock
 * is the failure mode this exists to prevent.
 *
 * An interface so callers can be tested against an in-memory fake. That seam
 * matters because `preferencesDataStore` caches its store per NAME, not per
 * Context, and never re-consults the Context afterwards - harmless for the one
 * instance a running app creates, fatal for test isolation, since two stores
 * built from different Contexts silently share one backing file.
 */
interface ArenaStore {
    suspend fun save(name: String, arena: Arena)
    suspend fun load(name: String): Arena?
    suspend fun names(): List<String>
    suspend fun delete(name: String)
}

private val Context.arenaDataStore by preferencesDataStore(name = "arena_layouts")

/**
 * Thin DataStore wrapper with no logic worth testing on the JVM (needs an
 * Android Context); the encode/decode risk lives in ArenaCodec, which is
 * covered by ArenaCodecTest instead.
 */
class PreferencesArenaStore(private val context: Context) : ArenaStore {

    override suspend fun save(name: String, arena: Arena) {
        context.arenaDataStore.edit { it[stringPreferencesKey(name)] = encodeArena(arena) }
    }

    override suspend fun load(name: String): Arena? {
        val text = context.arenaDataStore.data.first()[stringPreferencesKey(name)] ?: return null
        return decodeArena(text)
    }

    override suspend fun names(): List<String> =
        context.arenaDataStore.data.first().asMap().keys.map { it.name }.sorted()

    override suspend fun delete(name: String) {
        context.arenaDataStore.edit { it.remove(stringPreferencesKey(name)) }
    }
}
