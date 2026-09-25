"""
Every turn command ends where the tape says it does.

`config.TURN_DISPLACEMENT_CM` holds, per command, how far the robot centre moved across and
along its starting heading in one command, measured on the car (spec §2). The planner's turn
model has two parameters per command - the radius its rear pivot rides and how far ahead of
that pivot the centre sits - and `TurnInstruction.fit` solves both from that pair, so the
planned end pose matches the measurement by construction. This file is what fails if either
the fit or the geometry that consumes it drifts: an end pose more than a cell from the tape,
from any of the eight headings.

Before this model the two tables held a centre-to-centre chord per command and read it as a
radius, which put every planned 90 about 20-27 cm past the real car. The first assertion below
is the one that failed then.
"""
import math

import pytest

import config
from pathfinding.search.instructions import TurnInstruction
from pathfinding.search.turn import centre_arc, turn
from pathfinding.world.primitives import Direction, Point, Vector
from pathfinding.world.world import Robot, World

_LEFT_LOCK = ("FORWARD_LEFT", "BACKWARD_LEFT")
_ANTICLOCKWISE = ("FORWARD_LEFT", "BACKWARD_RIGHT")


def empty_world() -> World:
    return World(config.GRID_SIZE, Robot.planned(Direction.NORTH, Point(0, 0), Point(30, 30)), [])


def expected_end(start: Vector, instruction: TurnInstruction) -> tuple[float, float]:
    """The tape's answer rotated into `start`'s heading: across toward the steering side, along the heading."""
    across, along = config.TURN_DISPLACEMENT_CM[instruction.value]
    ux, uy = start.direction.unit
    sx, sy = (-uy, ux) if instruction.lock in _LEFT_LOCK else (uy, -ux)
    return start.x + across * sx + along * ux, start.y + across * sy + along * uy


@pytest.mark.parametrize("direction", list(Direction), ids=lambda d: d.value)
@pytest.mark.parametrize("instruction", list(TurnInstruction), ids=lambda t: t.value)
def test_every_turn_ends_where_the_tape_says(direction, instruction):
    start = Vector(direction, 100, 100)
    path = turn(empty_world(), start, instruction)
    assert path is not None, "mid-arena, every turn must fit"
    end = path[-1]
    ex, ey = expected_end(start, instruction)
    assert abs(end.x - ex) <= 1.0 and abs(end.y - ey) <= 1.0, \
        f"{instruction.value} from {direction.value}: planned ({end.x - 100}, {end.y - 100}), tape ({ex - 100:.1f}, {ey - 100:.1f})"
    turned = -instruction.degrees if instruction.lock in _ANTICLOCKWISE else instruction.degrees
    assert end.direction == Direction.of_degrees(direction.degrees + turned)


@pytest.mark.parametrize("instruction", list(TurnInstruction), ids=lambda t: t.value)
def test_a_command_ends_the_same_from_every_cardinal_heading(instruction):
    """
    Read in the command's own frame, the rounded end is the same from all four cardinals - the
    tape pair rounded half AWAY FROM ZERO - so no command ends at 16 from north and 15 from
    south. Half-up rounding broke that twice over: it is not mirror-symmetric (-21.5 rounds to
    -21, 21.5 to 22), and ``Direction.unit`` carries float noise (cos 90 degrees is 6e-17, not
    0) that tipped an exact tape half one way or the other depending on the heading.
    """
    def away(value: float) -> int:
        return int(math.copysign(math.floor(abs(value) + 0.5), value))

    across, along = config.TURN_DISPLACEMENT_CM[instruction.value]
    ends = set()
    for direction in (Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST):
        ux, uy = direction.step                 # exact integers for a cardinal
        sx, sy = (-uy, ux) if instruction.lock in _LEFT_LOCK else (uy, -ux)
        end = turn(empty_world(), Vector(direction, 100, 100), instruction)[-1]
        dx, dy = end.x - 100, end.y - 100
        ends.add((dx * sx + dy * sy, dx * ux + dy * uy))
    assert ends == {(away(across), away(along))}, f"{instruction.value}: {sorted(ends)}"


def test_the_fit_is_the_hand_derivation_for_a_quarter_turn():
    """
    For a 90 the two equations collapse to sums and differences, which is how the numbers were
    checked by hand before any code existed: forward R = (across + along) / 2 and
    lead = (across - along) / 2; backward swaps the roles because the centre trails the pivot.
    """
    for t in TurnInstruction:
        if t.degrees != 90:
            continue
        across, along = config.TURN_DISPLACEMENT_CM[t.value]
        radius, lead = t.fit(1)
        if t.forward:
            assert radius == pytest.approx((across + along) / 2), t
            assert lead == pytest.approx((across - along) / 2), t
        else:
            assert radius == pytest.approx((across - along) / 2), t
            assert lead == pytest.approx((-along - across) / 2), t


def test_the_fit_reproduces_its_own_measurement():
    """Putting (R, L) back through the model must give the pair it was solved from - for the 45s too."""
    for t in TurnInstruction:
        across, along = t.displacement(1)
        radius, lead = t.fit(1)
        theta = math.radians(t.degrees)
        s, c = math.sin(theta), 1 - math.cos(theta)
        if t.forward:
            assert radius * c + lead * s == pytest.approx(across), t
            assert radius * s - lead * c == pytest.approx(along), t
        else:
            assert radius * c - lead * s == pytest.approx(across), t
            assert -(radius * s + lead * c) == pytest.approx(along), t


def test_a_45_is_calibrated_on_its_own(monkeypatch):
    """
    A 45 is not half a 90 and a 90 is not two 45s: each command has its own tape pair. Changing
    the 45's entry moves the 45 and leaves the 90 alone - which also proves the table is read at
    call time and that the arc cache keys on the pair.
    """
    world = empty_world()
    start = Vector(Direction.NORTH, 100, 100)
    before_45 = turn(world, start, TurnInstruction.FORWARD_LEFT_45)[-1]
    before_90 = turn(world, start, TurnInstruction.FORWARD_LEFT)[-1]

    table = dict(config.TURN_DISPLACEMENT_CM)
    table["FORWARD_LEFT_45"] = (30.0, 30.0)
    monkeypatch.setattr(config, "TURN_DISPLACEMENT_CM", table)

    assert turn(world, start, TurnInstruction.FORWARD_LEFT_45)[-1] != before_45
    assert turn(world, start, TurnInstruction.FORWARD_LEFT)[-1] == before_90


def test_the_shipped_table_covers_all_eight_commands():
    """Config is the STM owner's to edit; a missing or nonsensical entry must fail here, not on a live request."""
    assert set(config.TURN_DISPLACEMENT_CM) == {t.value for t in TurnInstruction}
    for t in TurnInstruction:
        across, along = config.TURN_DISPLACEMENT_CM[t.value]
        assert across > 0, f"{t.value}: every command moved toward its steering side"
        assert (along > 0) == t.forward, f"{t.value}: forward commands go forward, backward ones back"
        radius, lead = t.fit(1)
        assert radius > 0 and 0 < lead < 20, f"{t.value}: fit ({radius:.1f}, {lead:.1f}) is not a rear pivot behind the centre"


def test_the_arc_does_not_depend_on_the_planning_footprint():
    """The pivot point is measured, so a 21 cm and a 31 cm planning box trace the same arc."""
    start = Vector(Direction.EAST, 100, 100)
    big = World(config.GRID_SIZE, Robot.planned(Direction.NORTH, Point(0, 0), Point(30, 30)), [])
    small = World(config.GRID_SIZE, Robot.planned(Direction.NORTH, Point(0, 0), Point(20, 20)), [])
    assert turn(big, start, TurnInstruction.BACKWARD_RIGHT) == turn(small, start, TurnInstruction.BACKWARD_RIGHT)


@pytest.mark.parametrize("direction", list(Direction), ids=lambda d: d.value)
@pytest.mark.parametrize("instruction", list(TurnInstruction), ids=lambda t: t.value)
def test_the_collision_checked_arc_is_the_rear_pivots_circle(direction, instruction):
    """
    The cells ``turn()`` collision-checks are the REAR PIVOT's arc: they begin where the rear
    pivot begins (``lead`` behind the start), finish where it finishes (``lead`` behind the tape
    end, along the end heading), and every one lies on the circle of the fitted radius about the
    instantaneous centre of rotation.

    This test exists because nothing else would notice if that arc were wrong. The end pose comes
    straight from the tape and ``centre_arc`` from the frame, both computed independently of the
    sampled cells, so an arc swept the wrong way - round the circle the other way, or walked from
    the wrong end - still ends on the right pose, still matches the translation oracle in
    test_turn_cache.py, and is still 8-connected, while the planner collision-checks the wrong
    cells. Measured 2026-09-25: with the sweep reversed in memory, every other test in this file,
    test_turn_cache.py and test_diagonals.py passed but two incidental arena comparisons.

    Tolerances: a cell is a point of the circle rounded to whole cells, so it is within half a
    cell of that point on each axis, and so within 1/sqrt(2) of the circle; the 1e-9 is the float
    noise the rounding helper snaps away before it rounds.
    """
    start = Vector(direction, 100, 100)
    path = turn(empty_world(), start, instruction)
    assert path is not None, "mid-arena, every turn must fit"
    radius, lead = instruction.fit(1)
    ux, uy = direction.unit
    sx, sy = (-uy, ux) if instruction.lock in _LEFT_LOCK else (uy, -ux)
    icr = (start.x - lead * ux + radius * sx, start.y - lead * uy + radius * sy)

    end = path[-1]
    vx, vy = end.direction.unit
    ex, ey = expected_end(start, instruction)
    rear_start = (start.x - lead * ux, start.y - lead * uy)
    rear_end = (ex - lead * vx, ey - lead * vy)

    def near(cell, point) -> bool:
        return abs(cell.x - point[0]) <= 0.5 + 1e-9 and abs(cell.y - point[1]) <= 0.5 + 1e-9

    # turn() appends the end pose only when the arc does not already finish on it. With the
    # shipped table it always does append - the centre sits 7-14 cm ahead of the rear pivot -
    # but the rule is the planner's, so the test follows it rather than assuming it.
    arc = path if near(end, rear_end) else path[:-1]
    where = f"{instruction.value} from {direction.value}"
    assert arc, f"{where}: a turn always checks at least one cell"
    assert near(arc[0], rear_start), \
        f"{where}: arc starts at ({arc[0].x}, {arc[0].y}), rear pivot at {rear_start}"
    assert near(arc[-1], rear_end), \
        f"{where}: arc ends at ({arc[-1].x}, {arc[-1].y}), rear pivot at {rear_end}"
    for cell in arc:
        off = abs(math.dist((cell.x, cell.y), icr) - radius)
        assert off <= 1 / math.sqrt(2) + 1e-9, \
            f"{where}: ({cell.x}, {cell.y}) is {off:.3f} off the rear pivot's circle"


@pytest.mark.parametrize("direction", list(Direction), ids=lambda d: d.value)
@pytest.mark.parametrize("instruction", list(TurnInstruction), ids=lambda t: t.value)
def test_the_centre_arc_is_finely_sampled_and_ends_on_the_end_pose(direction, instruction):
    start = Vector(direction, 100, 100)
    points = centre_arc(start, instruction, 1)
    spacing = config.CENTRE_PATH_SPACING_CM
    assert points, "a turn moves the centre, so there is always at least the end point"
    previous = (start.x, start.y)
    for point in points:
        assert math.dist(previous, point) <= spacing + 1e-9, (instruction, direction, previous, point)
        previous = point
    ex, ey = expected_end(start, instruction)
    assert points[-1] == pytest.approx((ex, ey), abs=1e-6)
    # And the planner's rounded end pose is that last point, rounded.
    end = turn(empty_world(), start, instruction)[-1]
    assert abs(end.x - points[-1][0]) <= 0.5 + 1e-9 and abs(end.y - points[-1][1]) <= 0.5 + 1e-9
