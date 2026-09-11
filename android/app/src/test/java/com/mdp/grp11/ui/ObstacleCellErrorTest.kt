package com.mdp.grp11.ui

import com.mdp.grp11.arena.Arena
import com.mdp.grp11.arena.Cell
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ObstacleCellErrorTest {

    private fun arenaWith(vararg cells: Cell): Arena {
        var a = Arena()
        cells.forEach { a = a.place(it).first }
        return a
    }

    @Test fun `a free in-bounds cell has no error`() {
        val a = arenaWith(Cell(10, 6))
        assertNull(obstacleCellError(a, id = 1, x = "12", y = "8"))
    }

    @Test fun `the cell the block already occupies has no error`() {
        val a = arenaWith(Cell(10, 6))
        assertNull(obstacleCellError(a, id = 1, x = "10", y = "6"))
    }

    @Test fun `a blank field is reported as not a number`() {
        val a = arenaWith(Cell(10, 6))
        assertEquals("Enter 0-19", obstacleCellError(a, id = 1, x = "", y = "6"))
    }

    @Test fun `a non-numeric field is reported as not a number`() {
        val a = arenaWith(Cell(10, 6))
        assertEquals("Enter 0-19", obstacleCellError(a, id = 1, x = "12", y = "x"))
    }

    @Test fun `a coordinate past the last cell is out of range`() {
        val a = arenaWith(Cell(10, 6))
        assertEquals("Out of range", obstacleCellError(a, id = 1, x = "20", y = "6"))
    }

    @Test fun `a negative coordinate is out of range`() {
        val a = arenaWith(Cell(10, 6))
        assertEquals("Out of range", obstacleCellError(a, id = 1, x = "12", y = "-1"))
    }

    @Test fun `the start zone is named as the reason`() {
        val a = arenaWith(Cell(10, 6))
        assertEquals("In the start zone", obstacleCellError(a, id = 1, x = "3", y = "3"))
    }

    @Test fun `an occupied cell names the block that holds it`() {
        val a = arenaWith(Cell(10, 6), Cell(12, 8))
        assertEquals("Occupied by B2", obstacleCellError(a, id = 1, x = "12", y = "8"))
    }

    @Test fun `surrounding whitespace is tolerated`() {
        val a = arenaWith(Cell(10, 6))
        assertNull(obstacleCellError(a, id = 1, x = " 12 ", y = "8 "))
    }

    // --- an EMPTY slot: no cell of its own to be excused from occupancy -------

    @Test fun `an empty slot on a free cell has no error`() {
        val a = arenaWith(Cell(10, 6))
        assertNull(obstacleCellError(a, id = 2, x = "12", y = "8"))
    }

    @Test fun `an empty slot is refused on every occupied cell, naming the holder`() {
        val a = arenaWith(Cell(10, 6))
        assertEquals("Occupied by B1", obstacleCellError(a, id = 2, x = "10", y = "6"))
    }
}
