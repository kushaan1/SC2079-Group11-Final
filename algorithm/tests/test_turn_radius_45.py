"""
A 45 degree turn has its own measured radius; it is not the 90's radius held half as long.

Measured on our chassis on 2026-09-18, the four 45 degree commands displaced the car 7-19% less
along its heading than a half-held 90 degree arc predicts, so the half-arc model lands the
planned car a few cm past where the real one stops. `config.TURN_RADIUS_45_CM` holds a radius
per direction derived from those measurements, and `TurnInstruction.radius` reads it for the
`_45` members. Every consumer - the traced arc in `turn.py`, `arc_length`, the cost models -
goes through `radius()`, so the geometry follows, not only the price.
"""
from math import radians, sin

import pytest

import config
from pathfinding.search.instructions import TurnInstruction as T
from pathfinding.search.turn import turn
from pathfinding.world.primitives import Direction, Point, Vector
from pathfinding.world.world import Robot, World


@pytest.fixture
def distinct_radii(monkeypatch):
    """Radii chosen so the 45 and 90 tables can never be confused for each other."""
    monkeypatch.setattr(config, "TURN_RADIUS_CM",
                        {"FORWARD_LEFT": 60, "FORWARD_RIGHT": 60, "BACKWARD_LEFT": 60, "BACKWARD_RIGHT": 60})
    # a 21 cm displacement along the heading after a 45 is a radius of 21 / sin 45 = 30
    monkeypatch.setattr(config, "TURN_45_DISPLACEMENT_CM",
                        {"FORWARD_LEFT": 21, "FORWARD_RIGHT": 21, "BACKWARD_LEFT": 21, "BACKWARD_RIGHT": 21})


@pytest.mark.diagonals
def test_a_45_reads_its_own_radius(distinct_radii):
    assert T.FORWARD_LEFT.radius(1) == 60
    assert T.FORWARD_LEFT_45.radius(1) == 30
    assert T.BACKWARD_RIGHT_45.radius(1) == 30


@pytest.mark.diagonals
def test_a_45_arc_length_is_priced_from_its_own_radius(distinct_radii):
    assert T.FORWARD_LEFT_45.arc_length(1) == round(30 * radians(45))
    assert T.FORWARD_LEFT.arc_length(1) == round(60 * radians(90))


@pytest.mark.diagonals
def test_the_traced_45_arc_follows_the_45_radius(distinct_radii):
    """
    The geometry, not only the cost: the car's displacement along its heading after a 45 is
    R45 * sin(45), and with R45 = 30 that is ~21 cm - a 60 cm half-arc would carry it ~42.
    """
    robot = Robot.planned(Direction.NORTH, Point(85, 85), Point(115, 115))
    world = World(config.GRID_SIZE, robot, [])
    start = Vector(Direction.NORTH, 100, 100)
    result = turn(world, start, T.FORWARD_LEFT_45)
    assert result is not None, "the arc must fit mid-arena"
    end = result[-1]
    along = end.y - start.y
    # The arc is traced on a 1 cm grid by a point 12 cm behind the centre, so the analytic
    # figure is approximate: what matters is that it is the 45 table's answer, not the 90's.
    assert abs(along - 21) < abs(along - 42), f"moved {along} cm along heading; the 45 table predicts ~21, the 90 table ~42"
    assert 15 <= along <= 27


def test_the_shipped_45_table_covers_all_four_directions():
    """Config is the STM owner's to edit; a missing key must fail here, not on a live request."""
    assert set(config.TURN_45_DISPLACEMENT_CM) == {"FORWARD_LEFT", "FORWARD_RIGHT", "BACKWARD_LEFT", "BACKWARD_RIGHT"}
    assert all(isinstance(r, int) and r > 0 for r in config.TURN_45_DISPLACEMENT_CM.values())
    # and the derivation lands where the STM measured
    assert {t.lock: t.radius(1) for t in T if t.degrees == 45} == {"FORWARD_LEFT": 34, "FORWARD_RIGHT": 52, "BACKWARD_LEFT": 38, "BACKWARD_RIGHT": 45}
