"""
The pivot primitive: `config.PIVOT_TURNS`.

A pivot is a shuffle turn - full steering lock forward, full lock back the other way, both
strokes swinging the nose the SAME way - which rotates an Ackermann car close to on the spot.
It is experimental and off by default, so, exactly like `test_diagonals.py`, this module marks
itself and is the only place in the suite where pivots are switched on.
"""
import math

import numpy as np
import pytest

import config
from pathfinding import cost
from pathfinding.search.instructions import (
    MiscInstruction, Move, MoveInstruction, Pivot, PivotInstruction, Straight, Turn,
    TurnInstruction,
)
from pathfinding.search.pivot import pivot
from pathfinding.search.search import Segment
from pathfinding.search.segment import _TURNS, _ranks, _tables, segment
from pathfinding.search.turn import turn
from pathfinding.world.objective import generate_objectives
from pathfinding.world.primitives import Direction, Point, Vector
from pathfinding.world.world import Obstacle, Robot, World
from simulator.geometry import HEADING_DEG
from simulator.playback import CAPTURE_DWELL_FRAMES, Playback
from simulator.routes import Route

pytestmark = pytest.mark.pivots


def test_the_pivots_marker_switches_the_flag_on():
    """
    Nothing else asserts the marker works, and every later pivot test trusts that it does.

    The additive guarantee - with the flag off the planner is what it was - is carried by the
    rest of the suite running with pivots OFF. That is only evidence if the marker is what
    switches them on here, rather than `config.PIVOT_TURNS`' default happening to suit
    whichever test ran last.
    """
    assert config.PIVOT_TURNS is True


def test_a_pivot_is_priced_above_zero_seconds():
    """
    A pivot changes the heading and goes nowhere, so at zero seconds it is a free self-loop in
    the search graph and the optimiser may rotate as much as it likes for nothing.

    The figure itself is a placeholder the STM owner will replace, so it is not asserted here;
    that it stays strictly positive is a condition the search depends on, not a measurement.
    """
    assert config.PIVOT_TIME_S > 0


def test_the_stroke_count_is_even():
    """
    A shuffle is pairs of strokes, one forward and one back, and the pair is what cancels most
    of the translation. An odd `PIVOT_STROKES_PER_45` would end a pivot mid-shuffle, a whole
    stroke's displacement from where the planner thinks the car stopped - and nothing
    downstream would catch it, because the heading would still be exactly right.
    """
    assert config.PIVOT_STROKES_PER_45 > 0
    assert config.PIVOT_STROKES_PER_45 % 2 == 0


# What each member means, spelled out rather than re-derived from its name: a test that parses
# the suffix the same way the property does would pass however wrong the parsing is.
_PIVOTS = {
    "PIVOT_LEFT_45": (45, False),
    "PIVOT_RIGHT_45": (45, True),
    "PIVOT_LEFT_90": (90, False),
    "PIVOT_RIGHT_90": (90, True),
}


@pytest.mark.parametrize("instruction", tuple(PivotInstruction))
def test_a_pivot_knows_its_own_size_and_sense(instruction):
    """
    Everything downstream is derived from these two: the geometry turns `degrees` into strokes
    and `clockwise` into which lock leads, and the cost model prices `degrees`. A member added
    later without an entry in `_PIVOTS` fails here with a KeyError, and a member DELETED from
    the enum fails the table check below rather than quietly shrinking this test to three
    cases. Either way the prompt is to decide what the enum means before the geometry guesses.

    `clockwise` follows `turn.py`'s convention - its `_ANTICLOCKWISE` pair is the one that
    swings the nose left - so RIGHT is clockwise, and a left pivot is the negative swing.
    """
    assert set(_PIVOTS) == {p.name for p in PivotInstruction}
    degrees, clockwise = _PIVOTS[instruction.name]

    assert instruction.degrees == degrees
    assert instruction.clockwise is clockwise


def test_a_pivot_counts_its_strokes_from_config_at_call_time(monkeypatch):
    """
    `config.py`'s call-time rule, in the one place this task can enforce it.

    The stroke count is a placeholder the STM owner replaces once the firmware's shuffle is
    settled, and the coverage tools set these names at runtime. A `strokes()` that read
    `config.PIVOT_STROKES_PER_45` at import would keep planning the count the module happened
    to load with, silently, while the config file said something else.
    """
    assert PivotInstruction.PIVOT_LEFT_45.strokes() == config.PIVOT_STROKES_PER_45
    assert PivotInstruction.PIVOT_LEFT_90.strokes() == 2 * config.PIVOT_STROKES_PER_45

    monkeypatch.setattr(config, "PIVOT_STROKES_PER_45", 6)

    assert PivotInstruction.PIVOT_LEFT_45.strokes() == 6
    assert PivotInstruction.PIVOT_RIGHT_90.strokes() == 12


def test_a_pivot_move_carries_its_instruction_and_its_path():
    """
    The shape `Segment.compress` and `cost.move_cost` branch on, beside `Turn` and `Move`: one
    instruction and the cells the car passes through, in driving order.

    Its own dataclass for the same reason the enum is its own enum - every
    `isinstance(move, Turn)` already in the planner and the simulator must stay False for a
    pivot, or a pivot gets priced and drawn as an arc it never drove.
    """
    cells = [Vector(Direction.NORTH, 100, 100), Vector(Direction.NORTHEAST, 101, 100)]

    move = Pivot(PivotInstruction.PIVOT_RIGHT_45, cells)

    assert move.pivot is PivotInstruction.PIVOT_RIGHT_45
    assert move.vectors == cells
    assert not isinstance(move, (Turn, Move))


def test_a_pivot_is_not_a_turn_instruction():
    """
    The decision the whole additive guarantee rests on, asserted where someone adding a fifth
    pivot token will trip over it.

    `segment._TURNS` is `tuple(TurnInstruction)`, and the four-heading planner is the subset
    `tuple(t for t in _TURNS if t.degrees == 90)`. A `PIVOT_LEFT_90` living in that enum would
    be picked up by that filter as an ordinary quarter turn: every route the service ships
    would change, with `config.PIVOT_TURNS` still False and no test in the suite so much as
    naming pivots. The filter is reproduced here rather than imported because it is the
    expression, not the table, that has to keep yielding four locks.
    """
    assert not set(PivotInstruction) & set(TurnInstruction)
    assert {t.value for t in TurnInstruction if t.degrees == 90} == {
        "FORWARD_LEFT", "FORWARD_RIGHT", "BACKWARD_LEFT", "BACKWARD_RIGHT",
    }
    # The values are the wire tokens, so they have to survive serialisation as themselves.
    assert all(p.value == p.name for p in PivotInstruction)
    assert PivotInstruction.PIVOT_LEFT_45 == "PIVOT_LEFT_45"


def empty_world():
    """A world with nothing in it but the boundary band, so geometry is all that can fail."""
    robot = Robot.planned(Direction.NORTH, Point(0, 0), Point(30, 30))
    return World(config.GRID_SIZE, robot, [])


@pytest.mark.parametrize("instruction", tuple(PivotInstruction))
def test_a_pivot_swings_the_heading_by_its_own_size(instruction):
    """
    The reason a pivot exists at all: it buys a heading, and it must buy exactly the one asked
    for from wherever the car happens to be pointing.

    Every heading, because the shuffle is derived once and served from a cache keyed on the
    start direction - a sign error in the stroke loop that happens to cancel from NORTH will
    not cancel from SOUTHEAST. A pivot that swung 90 where 45 was asked, or swung the wrong
    way, would still return a legal-looking path; nothing else in this module would notice.
    """
    world = empty_world()
    for direction in Direction:
        swing = instruction.degrees if instruction.clockwise else -instruction.degrees
        path = pivot(world, Vector(direction, 100, 100), instruction)

        assert path is not None, (direction, instruction)
        assert path[-1].direction == Direction.of_degrees(direction.degrees + swing), \
            (direction, instruction)


@pytest.mark.parametrize("instruction", tuple(PivotInstruction))
def test_a_pivot_barely_moves_the_robot(instruction):
    """
    The property that makes a pivot a pivot rather than an expensive turn.

    One 90 degree `FORWARD_RIGHT` arc carries the centre (52, 28) cm away from where it
    started - asserted below, so that number cannot rot - and the search reaches for a pivot
    precisely where that displacement is unwanted or will not fit. A shuffle that alternated
    its locks from the wrong one of the pair, or that put a turning circle on the wrong side of
    the car, would still end on the heading it promised and would still produce a connected
    path in driving order; what it would stop doing is cancelling, and it would drive away like
    an arc. This is the test that sees that, and the only one that does.

    15 cells is a bound, not a measurement: the real figure is under 7 at the placeholder
    radii, and the slack is there so that re-measuring `TURN_RADIUS_CM` does not fail a test
    that is asserting the wrong thing. What it rules out is a manoeuvre of an arc's magnitude.
    """
    world = empty_world()
    arc = turn(world, Vector(Direction.NORTH, 100, 100), TurnInstruction.FORWARD_RIGHT)[-1]
    assert (arc.x - 100, arc.y - 100) == (52, 28), "the arc this is contrasted with has moved"

    for direction in Direction:
        end = pivot(world, Vector(direction, 100, 100), instruction)[-1]
        drift = math.hypot(end.x - 100, end.y - 100)

        assert drift < 15, (direction, instruction, drift)


@pytest.mark.parametrize("handedness", ("LEFT", "RIGHT"))
def test_two_45_degree_pivots_land_where_one_90_does(handedness):
    """
    The claim the 90 rests on: it is not a manoeuvre of its own, it is the same shuffle kept up
    for twice as many strokes. If that is true then driving two 45s must put the robot where one
    90 would have, and this is the test that fails when it stops being true - a 90 that divides
    its swing by a fixed two strokes instead of by its own stroke count, a stroke count that
    does not scale with the pivot's size, or a 90 written as a case of its own. None of those is
    visible to the tests above, because each is still a perfectly good shuffle: it ends on the
    heading it promised and it goes almost nowhere. It is just not the shuffle a 45 is made of,
    so the search would price a route in 45s and the car would drive a different one in 90s.

    It also pins what lets the STM owner tune `PIVOT_STROKES_PER_45`: the swing per stroke is
    `45 / PIVOT_STROKES_PER_45` whatever the pivot's size, so the two sides of this comparison
    stay the same four strokes at any stroke count, not only at the default.

    One cell of tolerance because the intermediate pose is rasterised onto the integer grid
    before the second 45 starts from it, which one 90 never has to do.
    """
    world = empty_world()
    forty_five = PivotInstruction[f"PIVOT_{handedness}_45"]
    ninety = PivotInstruction[f"PIVOT_{handedness}_90"]

    for direction in Direction:
        start = Vector(direction, 100, 100)
        whole = pivot(world, start, ninety)[-1]
        first = pivot(world, start, forty_five)[-1]
        second = pivot(world, first, forty_five)[-1]

        assert second.direction == whole.direction, (direction, handedness)
        assert max(abs(second.x - whole.x), abs(second.y - whole.y)) <= 1, (direction, handedness)


@pytest.mark.parametrize("instruction", tuple(PivotInstruction))
def test_a_pivot_is_the_same_manoeuvre_from_every_heading(instruction):
    """
    The trap this module exists to avoid, caught by its one observable consequence.

    A pivot is defined relative to the car, so turning the car 45 degrees before it starts must
    turn the whole manoeuvre with it: the drift is the same length from all eight headings and
    only its direction changes. That holds exactly when the derivation carries the heading as a
    continuous angle. It stops holding the moment anything reaches for `Direction.unit`
    mid-manoeuvre - the obvious thing to reach for, and what a turn legitimately does - because
    the intermediate heading of a shuffle is 22.5 degrees at the default stroke count, which no
    `Direction` names. `Direction.of_degrees` would round it to NORTH going one way round and to
    EAST going the other, and the eight headings would stop being rotations of one another.

    That failure is nearly invisible from anywhere else: it keeps the end heading exact, keeps
    the path connected, and leaves the drift small enough to pass the bound above from most
    headings. Here it shows up as a spread of 5.3 to 9.2 cells against the one allowed.

    A cell of tolerance, not zero, because the drift is rounded onto the integer grid at the
    end: the cardinal headings and the diagonal ones round differently, which is the 0.4 cell
    alternation this sees at the placeholder radii.
    """
    world = empty_world()
    drifts = [
        math.hypot(end.x - 100, end.y - 100)
        for end in (pivot(world, Vector(d, 100, 100), instruction)[-1] for d in Direction)
    ]

    assert max(drifts) - min(drifts) <= 1, (instruction, drifts)


@pytest.mark.parametrize("perturbed", (
    "the forward radii", "the backward radii", "the pivot offset", "the stroke count",
))
def test_the_shape_follows_the_config_it_was_derived_from(perturbed, monkeypatch):
    """
    `config.py`'s call-time rule, and the cache key that rule depends on, in one assertion.

    Every number a pivot's shape is made of is a placeholder the STM owner is expected to
    replace, and `pivot()` caches the shape it derives. Two ways to get this wrong and neither
    shows up as an error: read the constants once at import, or leave one of them out of the
    cache key. Both end with the planner serving a shape for a manoeuvre the car no longer
    drives, from the second call onward, with `config.py` saying something else entirely.

    The two radii are perturbed separately, not together, and that is the point of the extra
    case rather than tidiness. A pivot alternates two locks and so carries TWO radii in its key;
    moving both at once would be satisfied by a key that held either one of them. Moving them
    one at a time is what pins both.

    The backward case earns its keep twice over, because the backward radius is the number a
    shuffle uses and an identically named turn does not: a stroke loop that reached for the
    forward radius on both strokes - a plausible slip, the two strokes being otherwise
    symmetrical - passes every other test in this file and fails only this one.
    """
    # Each changed to something the default is not, in the direction that moves the shape: a
    # radius because it is what each stroke arcs around, the offset because it is what sets
    # `lead`, the stroke count because it is what sets the swing per stroke.
    changed = {
        "the forward radii":
            ("TURN_RADIUS_CM", dict(config.TURN_RADIUS_CM, FORWARD_LEFT=25, FORWARD_RIGHT=25)),
        "the backward radii":
            ("TURN_RADIUS_CM", dict(config.TURN_RADIUS_CM, BACKWARD_LEFT=25, BACKWARD_RIGHT=25)),
        "the pivot offset": ("TURN_PIVOT_OFFSET_CM", 9),
        "the stroke count": ("PIVOT_STROKES_PER_45", 4),
    }
    name, value = changed[perturbed]
    world = empty_world()

    def shape(instruction):
        path = pivot(world, Vector(Direction.NORTH, 100, 100), instruction)
        return [(v.direction, v.x, v.y) for v in path]

    before = {instruction: shape(instruction) for instruction in PivotInstruction}
    monkeypatch.setattr(config, name, value)

    assert all(shape(instruction) != before[instruction]
               for instruction in PivotInstruction), perturbed


def test_a_pivot_that_does_not_fit_is_refused():
    """
    The other half of the module: deriving the shape is no use unless a pivot that will not fit
    comes back as None, and the shape is what decides that, not the cell it starts on.

    The obstacle here is placed so the cell the robot stands on stays free and it could still
    drive five cells straight ahead - only the swing to the east is blocked. That is the case
    worth pinning, because it is the one a cheaper check would get wrong: refusing on the start
    cell alone would let a pivot swing through the obstacle, and refusing on the whole
    bounding box would turn down the left-hand pivots, which have room.

    The pose beyond the arena's north edge is not a contrived input. A turn's and a pivot's end
    pose are deliberately NOT collision-checked, so the search does hold poses outside the
    arena and does expand them - `segment.py` pads its index space for exactly that. The shape
    is checked for bounds BEFORE the grid is indexed, because numpy reads a negative coordinate
    as an offset from the far edge and a pivot leaving the arena to the west would otherwise be
    answered by the eastern wall.
    """
    robot = Robot.planned(Direction.NORTH, Point(0, 0), Point(30, 30))
    world = World(config.GRID_SIZE, robot,
                  [Obstacle(Direction.WEST, Point(125, 100), Point(134, 109), 1)])
    start = Vector(Direction.NORTH, 100, 100)

    assert world.contains(start)
    assert all(world.contains(Vector(Direction.NORTH, 100, 100 + n)) for n in range(1, 6))

    assert pivot(world, start, PivotInstruction.PIVOT_RIGHT_45) is None
    assert pivot(world, start, PivotInstruction.PIVOT_RIGHT_90) is None
    assert pivot(world, start, PivotInstruction.PIVOT_LEFT_45) is not None
    assert pivot(world, start, PivotInstruction.PIVOT_LEFT_90) is not None

    beyond = Vector(Direction.NORTH, 100, config.GRID_SIZE - 10)
    assert all(pivot(empty_world(), beyond, i) is None for i in PivotInstruction)


def test_a_pivot_costs_the_configured_seconds_and_reads_them_at_call_time(monkeypatch):
    """
    The time model's whole claim about a pivot: `PIVOT_TIME_S` per 45 degrees, and a 90 costs
    twice a 45 because it is literally twice the shuffling.

    Asserted against a MONKEYPATCHED figure rather than against the literal 2.0, because that is
    the only thing that separates the two implementations which both pass at the default: one
    that reads `config.PIVOT_TIME_S` on every call, and one that bound it at import - or that
    wrote 2.0 out. 2.0 is a working figure the STM owner offered on 2026-09-11 so that the cost
    model could be written against something, explicitly not a stopwatch reading, so the day it
    is replaced is the day the difference between those two starts costing routes.

    The cell size is accepted and ignored, as it is for a turn: seconds are seconds whatever
    grid resolution the planner happens to be running at.
    """
    assert cost.TIME_SECONDS.pivot(PivotInstruction.PIVOT_LEFT_45) \
        == pytest.approx(config.PIVOT_TIME_S)

    monkeypatch.setattr(config, "PIVOT_TIME_S", 7.5)

    for handedness in ("LEFT", "RIGHT"):
        forty_five = cost.TIME_SECONDS.pivot(PivotInstruction[f"PIVOT_{handedness}_45"])
        ninety = cost.TIME_SECONDS.pivot(PivotInstruction[f"PIVOT_{handedness}_90"])

        assert forty_five == pytest.approx(7.5), handedness
        assert ninety == pytest.approx(2 * forty_five), handedness

    assert cost.TIME_SECONDS.pivot(PivotInstruction.PIVOT_LEFT_90, 5) == pytest.approx(15.0)


def test_a_pivot_is_always_dearer_in_time_than_the_arc_it_replaces():
    """
    The economics the primitive rests on, and the reason it needs no fencing off from open
    ground: at the placeholder figures a 45 degree pivot is 2.0 s against the 45 degree arc's
    1.5, and a 90 is 4.0 against 3.0. The pivot is dearer AND it arrives nowhere - the quarter
    turn asserted above carries the centre (52, 28) cm, a pivot under 7 - so an optimiser
    minimising seconds reaches for one only where that displacement is unwanted or will not fit:
    tight corners, U-turns, squaring up for a final approach. On an open route it never wins.

    Invert the inequality and the flag stops being safe to switch on: a pivot cheaper than the
    arc is a rotation the search gets paid to take, and it would pepper straight corridors with
    them. The production change that produces it is small and plausible - charging `PIVOT_TIME_S`
    per 90 degrees by symmetry with `TURN_TIME_S`, which prices a 45 at 1.0 s, below the arc.

    Stated as a comparison against the turn model rather than against 2.0 and 1.5 so that it
    keeps meaning this when either figure is replaced by a measurement. If a measured pivot does
    come in cheaper than the arc, this is the right place to find that out and re-read the
    search integration in that light.
    """
    for instruction in PivotInstruction:
        arc = (TurnInstruction.FORWARD_RIGHT_45 if instruction.degrees == 45
               else TurnInstruction.FORWARD_RIGHT)

        assert cost.TIME_SECONDS.pivot(instruction) > cost.TIME_SECONDS.turn(arc), instruction


# The two steering locks one shuffle alternates, forward stroke first, spelled out rather than
# imported from `pivot._LOCKS`. The cost model is required to REUSE that table; a test that read
# it too could not tell whether the model reached into the right half of it.
_STROKE_LOCKS = {
    True: ("FORWARD_RIGHT", "BACKWARD_LEFT"),
    False: ("FORWARD_LEFT", "BACKWARD_RIGHT"),
}


@pytest.mark.parametrize("instruction", tuple(PivotInstruction))
def test_a_pivot_is_charged_the_ground_its_wheels_cover(instruction):
    """
    The distance model's answer to a manoeuvre that goes nowhere: not zero.

    `DISTANCE_CELLS` is the search's original objective and it prices a turn at its ARC LENGTH -
    the ground the car covers, never the displacement it achieves. A pivot is several such arcs
    driven alternately, so it is charged their sum: half its strokes on the forward lock and
    half on the backward one, each sweeping `degrees / strokes`. Charge the displacement instead
    and a pivot comes out near zero, which hands the distance-weighted search the free
    self-loop `test_a_pivot_is_priced_above_zero_seconds` rules out for the clock.

    The figure is in cells, like everything else in this model, so that the two halves of a
    route's cost still add.
    """
    strokes = instruction.strokes()
    forward, backward = _STROKE_LOCKS[instruction.clockwise]
    expected = (strokes / 2) * math.radians(instruction.degrees / strokes) * (
        config.TURN_RADIUS_CM[forward] + config.TURN_RADIUS_CM[backward]
    )

    assert cost.DISTANCE_CELLS.pivot(instruction) == pytest.approx(expected)
    assert cost.DISTANCE_CELLS.pivot(instruction) > 0


@pytest.mark.parametrize("handedness", ("LEFT", "RIGHT"))
def test_a_90_degree_pivot_is_charged_twice_a_45(handedness):
    """
    A 90 is not a manoeuvre of its own: it is the same shuffle kept up for twice as many
    strokes, so it covers twice the ground.

    Its own test, parametrised over the handedness rather than folded into the case above as a
    sub-assertion, for an honest count. Inside a test parametrised over all four instructions
    this claim reads as four checks and is two, because on the 45 degree cases it compares a
    pivot against itself and reduces to `x == x`.

    What it pins is that the charge is PROPORTIONAL to the pivot's own swing. It fails on a
    swing read from a constant rather than from `instruction.degrees`, and on a flat charge per
    pivot regardless of size - both of which leave a perfectly plausible positive number that
    every other assertion in this file accepts at one size.

    What it does NOT pin, checked rather than assumed, is the stroke count. `(s / 2) *
    radians(d / s)` is `radians(d) / 2` for every `s`, whether or not that `s` scales with the
    pivot's size, so a stroke count frozen at 2 still prices a 90 at exactly twice a 45. The
    stroke count's invariance has its own test; the geometry's version of the two-45s-make-a-90
    claim is `test_two_45_degree_pivots_land_where_one_90_does`. The time model's half of this
    claim is asserted where the seconds are and is not duplicated here.
    """
    forty_five = PivotInstruction[f"PIVOT_{handedness}_45"]
    ninety = PivotInstruction[f"PIVOT_{handedness}_90"]

    assert cost.DISTANCE_CELLS.pivot(ninety) == pytest.approx(
        2 * cost.DISTANCE_CELLS.pivot(forty_five))


def test_a_pivot_is_priced_against_the_two_locks_it_actually_alternates(monkeypatch):
    """
    The one way to get `_Distance.pivot` wrong that nothing else in this file can see.

    A clockwise pivot shuffles FORWARD_RIGHT with BACKWARD_LEFT; an anticlockwise one shuffles
    FORWARD_LEFT with BACKWARD_RIGHT. Look the radii up under the other handedness - or under
    the forward lock twice, the two strokes being otherwise symmetrical - and the cost is still
    positive, still scales with the swing, still reads config at call time, and is wrong by the
    gap between the radii. At the placeholder 40/37/39/39 that gap is under half a percent:
    exactly the size of error that survives review and then quietly picks the wrong route.

    So the radii are driven apart until the mistake cannot hide. WHICH WAY they are driven apart
    is the whole substance of this test, and the two obvious choices each have a blind spot:

    * Equal within each handedness (40/40 against 10/10) catches the swap and misses reading one
      lock twice completely - `2*40 / 2*10` is the same ratio of 4 as `80 / 20`, so the mutant
      answers exactly what the correct model answers.
    * Equal in SUM across the two handednesses (40/40 against 70/10) catches reading one lock
      twice and misses the swap, because exchanging two equal sums changes nothing.

    The pairs must therefore be non-proportional AND unequal in sum, which 40+40 against 30+10
    is: the correct ratio is 2, a swapped handedness gives 0.5, reading the forward lock twice
    gives 1.33 and the backward lock twice gives 4. The expected ratio is stated rather than
    recomputed from the formula, which keeps this an independent check on WHICH radii are read
    instead of a restatement of what is done with them - and, incidentally, pins that they are
    read at call time, since a model holding the shipped radii would answer about 0.99 here.
    """
    monkeypatch.setattr(config, "TURN_RADIUS_CM", {
        "FORWARD_RIGHT": 40, "BACKWARD_LEFT": 40,   # the clockwise shuffle: 80 cells of radius
        "FORWARD_LEFT": 30, "BACKWARD_RIGHT": 10,   # the anticlockwise one: 40, and not 40/40
    })

    for size in (45, 90):
        clockwise = cost.DISTANCE_CELLS.pivot(PivotInstruction[f"PIVOT_RIGHT_{size}"])
        anticlockwise = cost.DISTANCE_CELLS.pivot(PivotInstruction[f"PIVOT_LEFT_{size}"])

        assert clockwise == pytest.approx(2 * anticlockwise), size


@pytest.mark.parametrize("instruction", tuple(PivotInstruction))
def test_a_pivots_distance_stays_in_cells_at_any_cell_size(instruction):
    """
    `_Distance` is documented as grid cells and its consumers multiply by `cell_size`
    themselves, so a pivot has to shrink with a coarser grid exactly as a turn's arc length
    does. Ignore the argument - easy to do, since the TIME model legitimately does - and a pivot
    would be charged centimetres while every straight beside it was charged cells: at any cell
    size but 1 the search would be told a pivot costs several times what it does and would never
    take one.

    Floor division rather than a scale factor, because that is how a radius becomes cells
    everywhere else in the planner (`TurnInstruction.radius` floors, and so does the geometry in
    `pivot.py`). A cost model dividing by 5.0 instead would price a manoeuvre the car does not
    drive.
    """
    strokes = instruction.strokes()
    forward, backward = _STROKE_LOCKS[instruction.clockwise]
    expected = (strokes / 2) * math.radians(instruction.degrees / strokes) * (
        config.TURN_RADIUS_CM[forward] // 5 + config.TURN_RADIUS_CM[backward] // 5
    )

    assert cost.DISTANCE_CELLS.pivot(instruction, 5) == pytest.approx(expected)
    assert cost.DISTANCE_CELLS.pivot(instruction, 5) < cost.DISTANCE_CELLS.pivot(instruction)


def test_move_cost_prices_a_pivot_as_a_pivot():
    """
    The branch, and what happens without it: `move_cost` ENDS in the straight case, so a `Pivot`
    it does not recognise is not an error - it is silently charged `len(vectors)` cells of
    forward travel. A pivot's centre path is a handful of cells, so the search would be told
    that rotating on the spot costs about a fifth of a second and would rotate wherever it
    pleased, which is precisely the behaviour the pricing above exists to prevent.

    Checked under both models because they fail differently: the distance model's fallthrough is
    merely wrong, the time model's is wrong AND cheap, and cheap is what changes routes.
    `cost.seconds` is checked as well - it is what `Segment.seconds` and the simulator clock
    read, and it carries its own view of what a move can be.
    """
    instruction = PivotInstruction.PIVOT_RIGHT_90
    cells = [Vector(Direction.NORTH, 100, 100 + n) for n in range(8)]
    move = Pivot(instruction, cells)

    assert cost.move_cost(move, cost.TIME_SECONDS, 1) \
        == pytest.approx(cost.TIME_SECONDS.pivot(instruction, 1))
    assert cost.move_cost(move, cost.DISTANCE_CELLS, 1) \
        == pytest.approx(cost.DISTANCE_CELLS.pivot(instruction, 1))
    assert cost.seconds([move], 1) == pytest.approx(cost.TIME_SECONDS.pivot(instruction, 1))

    # And not what those same eight cells would have cost as the straight they are not.
    assert cost.move_cost(move, cost.TIME_SECONDS, 1) != pytest.approx(
        cost.move_cost(Move(Straight.FORWARD, cells), cost.TIME_SECONDS, 1))


def test_a_pivots_distance_does_not_move_when_the_stroke_count_does(monkeypatch):
    """
    A fact about the manoeuvre worth pinning precisely because it is surprising: the ground a
    shuffle covers does NOT depend on how many strokes it is chopped into. Each stroke sweeps
    `degrees / strokes` at a fixed radius and there are `strokes` of them, so the count cancels
    - total wheel travel is the total rotation times the radius however the rotation is
    chopped up. Only the drift and the swept box respond to `PIVOT_STROKES_PER_45`, which is why
    `config.py` argues that choice on those grounds and never on cost.

    So the STM owner may retune the stroke count without repricing a single route, and this is
    where that promise is kept. It also pins the shape of the sum, which is the part the
    cancellation makes easy to get wrong unnoticed: a formula that lost its `strokes / 2`
    factor, or that swept the whole `degrees` per stroke rather than its share, is still
    positive and still looks reasonable, and at the default two strokes a 45 degree pivot comes
    out at exactly the right number either way. What it stops being is invariant, so it shows up
    here and only here.
    """
    before = {instruction: cost.DISTANCE_CELLS.pivot(instruction)
              for instruction in PivotInstruction}

    monkeypatch.setattr(config, "PIVOT_STROKES_PER_45", 6)

    assert {instruction: cost.DISTANCE_CELLS.pivot(instruction)
            for instruction in PivotInstruction} == pytest.approx(before)


# ---------------------------------------------------------------------------------------
# Search integration: the move tables, the rotation clearance, and what a traced pivot
# rebuilds as. Everything above this line is the primitive on its own; everything below is
# the primitive wired into the Dijkstra.
#
# `_tables` and `_ranks` are private and are imported anyway, because the additive guarantee
# is a statement ABOUT the table - which moves are in it, in which order, under which codes -
# and there is no public surface that shows that. Asserting it through a planned route
# instead would only show that today's arenas happen not to notice a reordering.
# ---------------------------------------------------------------------------------------

# The pivot code table, written out rather than imported from `segment._PIVOTS`, for the
# reason `_STROKE_LOCKS` above is written out: a test that read the table under test could not
# tell whether the codes were assigned from it in order.
_PIVOT_CODES = (
    PivotInstruction.PIVOT_LEFT_45,
    PivotInstruction.PIVOT_RIGHT_45,
    PivotInstruction.PIVOT_LEFT_90,
    PivotInstruction.PIVOT_RIGHT_90,
)


class _NoPivotPricing:
    """
    `cost.DISTANCE_CELLS`, except that pricing a pivot is an error.

    The decisive form of "no pivot move can leak in with the flag off", and it is aimed at one
    consequence in particular. `_Distance.pivot` returns a float where `_Distance.turn` returns
    a rounded int, so a pivot edge puts FRACTIONAL priorities on a distance-weighted frontier -
    and the frontier is `(cost, index)` pairs whose ties are broken by the index. A fraction
    that reaches the heap changes which of two equal-cost expansions pops first, and therefore
    which route is returned, without changing any route's cost. That is the one way the
    additive guarantee could fail while every price and every legality mask was still correct.

    Asserting on the tables' contents cannot see it, because a pivot priced but then dropped
    would leave no trace. Refusing to price one can: `_tables` asks `weights` for a cost for
    every move it records, so this raises if a pivot is so much as considered.
    """

    def turn(self, turn, cell_size: int = 1) -> float:
        return cost.DISTANCE_CELLS.turn(turn, cell_size)

    def straight(self, cells: float, cell_size: int = 1) -> float:
        return cost.DISTANCE_CELLS.straight(cells, cell_size)

    def pivot(self, instruction, cell_size: int = 1) -> float:
        raise AssertionError(f"priced {instruction.value} with config.PIVOT_TURNS off")


def _ordinary_moves(diagonals: bool, chunks) -> int:
    """How many moves a direction's table holds before any pivot is appended."""
    turns = [t for t in TurnInstruction if diagonals or t.degrees == 90]
    return len(turns) + len(chunks)


def _pivot_of(code: int, chunks) -> PivotInstruction:
    """The instruction a pivot move code names, decoded the way `_Search.__move` must."""
    return _PIVOT_CODES[code - len(_TURNS) - len(chunks) - 1]


@pytest.mark.parametrize("diagonals", (False, True))
def test_pivot_move_codes_are_appended_after_the_straights(diagonals, monkeypatch):
    """
    The additive guarantee, stated as the property the rest of the suite's evidence rests on.

    `_tables`' own docstring says two moves may reach one state at the same cost and the FIRST
    one recorded keeps it. So the table's order is not presentation - it is the tie-break, and
    every route the service ships today is a function of it. Appending the pivots after the
    straight chunks, rather than slotting them in beside the turns they resemble, is what makes
    a route with `PIVOT_TURNS` off provably the route it was before pivots existed.

    Two assertions, and the second is the substantive one:

    * with the flag OFF a direction's table holds exactly the turns and the straight chunks,
      under exactly the codes it held them under, so no pivot can leak in; and
    * with the flag ON that whole prefix is still there, byte for byte - the same legality
      masks, the same index deltas, the same prices, the same codes - with the pivots after it.

    The prefix comparison is what a bare count cannot give: a table that recomputed the turns
    under a different padding, or that reordered FORWARD before BACKWARD, would pass a count
    and change routes. Comparing the tuples compares the legality masks as bytes.

    The behavioural half of the guarantee is the rest of the suite, which `conftest.py` pins to
    `PIVOT_TURNS = False`: `tests/test_segment_fast.py` against its committed baseline and
    `tests/test_turn_cache.py` against the pre-cache Python loop are the two canaries. If
    either moves, this property has been broken however green this test is.
    """
    monkeypatch.setattr(config, "DIAGONAL_HEADINGS", diagonals)
    world = empty_world()
    ranks = _ranks()

    monkeypatch.setattr(config, "PIVOT_TURNS", False)
    pad, stride, without, chunks = _tables(world, _NoPivotPricing(), (), ranks)

    monkeypatch.setattr(config, "PIVOT_TURNS", True)
    padded, strode, with_pivots, chunked = _tables(world, cost.DISTANCE_CELLS, (), ranks)

    # The index space itself must not move: a pivot never ends outside the arena, so it asks
    # for no padding a turn did not already ask for.
    assert (padded, strode, chunked) == (pad, stride, chunks)

    ordinary = _ordinary_moves(diagonals, chunks)
    turns = len([t for t in TurnInstruction if diagonals or t.degrees == 90])
    codes = list(range(1, turns + 1)) + list(range(len(_TURNS) + 1, len(_TURNS) + 1 + len(chunks)))

    for rank, direction in enumerate(ranks):
        assert [move[3] for move in without[rank]] == codes, direction
        assert with_pivots[rank][:ordinary] == without[rank], direction
        assert len(with_pivots[rank]) > ordinary, direction
        assert all(move[3] > len(_TURNS) + len(chunks)
                   for move in with_pivots[rank][ordinary:]), direction


@pytest.mark.parametrize("diagonals", (False, True))
def test_a_pivot_is_offered_only_where_its_end_heading_exists(diagonals, monkeypatch):
    """
    What makes the 45 degree pivots appear exactly when the diagonals do, with no second flag.

    A 45 degree pivot from NORTH ends NORTHEAST, and NORTHEAST is only a search state when
    `DIAGONAL_HEADINGS` is on - `_ranks()` is what decides that. So the rule is not "emit the
    45s when the diagonals are on", which would be the same fact written down twice and free to
    drift; it is "emit a pivot when its END HEADING is a rank", and the composition falls out.
    Get it wrong the generous way and the search records a transition into a rank that does not
    exist, which is an index into another heading's plane of the state array: a silently
    corrupt expansion rather than a crash.

    The index delta is checked against the geometry as well, because the delta is the whole
    content of the move - which pose the search believes it arrives at. A pivot that swings the
    heading correctly and then files the transition under the starting rank would leave every
    assertion about the shape above still true.
    """
    monkeypatch.setattr(config, "DIAGONAL_HEADINGS", diagonals)
    world = empty_world()
    ranks = _ranks()
    rank_of = {direction: rank for rank, direction in enumerate(ranks)}

    pad, stride, tables, chunks = _tables(world, cost.DISTANCE_CELLS, (), ranks)
    cells = stride * stride
    expected = set(PivotInstruction) if diagonals else {
        PivotInstruction.PIVOT_LEFT_90, PivotInstruction.PIVOT_RIGHT_90,
    }

    for rank, direction in enumerate(ranks):
        offered = {}
        for _legal, delta, _price, code in tables[rank]:
            if code > len(_TURNS) + len(chunks):
                offered[_pivot_of(code, chunks)] = delta

        assert set(offered) == expected, direction

        for instruction, delta in offered.items():
            end = pivot(world, Vector(direction, 100, 100), instruction)[-1]
            assert (rank_of[end.direction] - rank) * cells \
                + (end.x - 100) * stride + (end.y - 100) == delta, (direction, instruction)


def _table_of(world, direction):
    """
    One heading's move table out of a real search, as ``(chunks, {code: is_legal(x, y)})``.

    Reaches into `_tables` because the rotation clearance is visible nowhere else. It is a
    property of the mask the SEARCH reads, and `pivot()` - which answers the world's ordinary
    grid - is deliberately blind to it: the primitive's contract is that its centre path is
    exactly those cells, and getting the extra clearance in is the caller's job. So "the search
    refuses this pivot here" is not a question any public surface can be asked.

    The cell arithmetic mirrors `_Search.run`'s: a mask is one byte per cell of the padded
    stride-by-stride grid, in C order, so the state at ``(x, y)`` is at ``(x + pad) * stride +
    y + pad``.
    """
    ranks = _ranks()
    pad, stride, tables, chunks = _tables(world, cost.DISTANCE_CELLS, (), ranks)

    def reader(legal):
        return lambda x, y: bool(legal[(x + pad) * stride + (y + pad)])

    return chunks, {code: reader(legal) for legal, _delta, _price, code in tables[ranks.index(direction)]}


def _pivot_code(instruction: PivotInstruction, chunks) -> int:
    """The code `_tables` must file this pivot under: appended after the straight chunks."""
    return len(_TURNS) + len(chunks) + 1 + _PIVOT_CODES.index(instruction)


def _clearance(world) -> int:
    """The spec's `delta`: how much more room a rotating robot needs than a sliding one."""
    return math.ceil(world.robot.north_length * (math.sqrt(2) - 1))


def _nearest_blocked(world, cells):
    """``(chebyshev, euclidean)`` from the closest of ``cells`` to any blocked cell."""
    blocked = np.argwhere(~world.grid)
    chebyshev, euclidean = math.inf, math.inf
    for x, y in cells:
        gaps = np.abs(blocked - (x, y))
        chebyshev = min(chebyshev, int(gaps.max(axis=1).min()))
        euclidean = min(euclidean, float(np.hypot(gaps[:, 0], gaps[:, 1]).min()))
    return chebyshev, euclidean


def _crowded_world():
    """
    A world built so that one pivot, and only that pivot, runs out of ROTATION clearance.

    The obstacle's inflated box stops at x = 78. `PIVOT_LEFT_90` from (100, 100) swings the
    centre out to x = 82, four clear cells short of it, so every cell of that pivot's centre
    path is free on the ordinary grid and `pivot()` returns a path. Four cells is not enough
    room to rotate in: the robot is off its axis for the whole manoeuvre and needs its
    circumscribed radius, seven cells more than the half-extent the grid was inflated by.

    Nothing else at that cell is affected. The robot stands clear, it may drive straight ahead,
    and `PIVOT_RIGHT_90` swings the other way into open arena. That is the contrast the
    clearance model has to produce, and a model that refused on the start cell alone, or on the
    pivot's bounding box, would flatten it.
    """
    robot = Robot.planned(Direction.NORTH, Point(0, 0), Point(30, 30))
    return World(config.GRID_SIZE, robot,
                 [Obstacle(Direction.EAST, Point(48, 100), Point(57, 109), 1)])


def test_a_pivot_is_refused_where_the_rotation_clearance_is_missing():
    """
    The clearance model's own test, and the silent failure it exists to prevent.

    `World.grid` marks the cells the robot's CENTRE may occupy, inflating every obstacle by the
    robot's half-extent. That is only sound for a square sliding along its own heading. A
    rotating 31 cm square sweeps a circle of radius `half_extent * sqrt(2)`, about 21 cells, so
    a pivot needs roughly six more cells on every side than a straight move from the same cell.
    Check a pivot against the ordinary grid and the planner emits a route that looks perfectly
    legal and clips the obstacle - no exception, no warning, nothing in the plan to inspect.
    The car finds out.

    So the assertions are deliberately a contradiction between two answers about the same cell:
    `pivot()` says the manoeuvre fits, because it is answering the grid it was handed, and the
    search's own table says no. The table is the one that decides, and it is right.
    """
    world = _crowded_world()
    start = Vector(Direction.NORTH, 100, 100)
    chunks, table = _table_of(world, Direction.NORTH)

    left = _pivot_code(PivotInstruction.PIVOT_LEFT_90, chunks)
    right = _pivot_code(PivotInstruction.PIVOT_RIGHT_90, chunks)
    forward = len(_TURNS) + 1 + chunks.index((Straight.FORWARD, config.STRAIGHT_CHUNK_CELLS[0]))

    # The ordinary grid is happy: the cell is free, the straight fits, and every cell of the
    # pivot's centre path is free - which is exactly the answer that would be wrong to trust.
    assert world.contains(start)
    assert pivot(world, start, PivotInstruction.PIVOT_LEFT_90) is not None
    assert table[forward](100, 100)

    assert not table[left](100, 100)
    assert table[right](100, 100), "the pivot with room to swing was refused as well"

    # And the refusal is this obstacle's doing, not a blanket ban on pivoting.
    _, open_ground = _table_of(empty_world(), Direction.NORTH)
    assert open_ground[left](100, 100)


def test_the_rotation_clearance_is_a_disc_and_not_a_box():
    """
    WHY eroding by an L2 disc is exactly the condition, pinned as the two cases that separate
    the disc from the box someone will eventually simplify it to.

    Obstacle inflation is L-infinity: an axis-aligned box grown by the robot's half-extent. A
    rotating robot needs that box grown to its circumscribed radius with ROUNDED CORNERS - the
    Minkowski sum with a disc - because the corner of the sweep is the corner of a circle, not
    of a square. Eroding the already-inflated grid by an L2 disc of radius
    `ceil(half_extent * (sqrt(2) - 1))` grows the box by exactly that much and rounds it.

    The two worlds below differ only in where the obstacle sits, and they are on opposite sides
    of that distinction:

    * crowded: the nearest blocked cell is due west of the swing, four cells away. Inside the
      disc and inside the box; both metrics refuse, and the pivot is refused.
    * cornered: the nearest blocked cell is a CORNER, seven cells west and seven south of the
      same swing. Chebyshev 7, Euclidean 9.9. An L-infinity erosion by 7 would refuse this one
      too - and be wrong to: the robot's sweep is a circle and clears that corner with 2.9
      cells to spare. The disc offers it.

    Getting this wrong the box way is not a crash and not a clipped obstacle. It is a planner
    that quietly turns down legal manoeuvres in exactly the tight corners the primitive was
    added for, which is the failure that never gets reported because the route still works.
    """
    delta = _clearance(empty_world())
    assert delta == 7, "the 31 cm robot's rotation clearance has moved"

    robot = Robot.planned(Direction.NORTH, Point(0, 0), Point(30, 30))
    cornered = World(config.GRID_SIZE, robot,
                     [Obstacle(Direction.EAST, Point(45, 66), Point(54, 75), 1)])

    for world, inside in ((_crowded_world(), True), (cornered, False)):
        chunks, table = _table_of(world, Direction.NORTH)
        code = _pivot_code(PivotInstruction.PIVOT_LEFT_90, chunks)
        path = pivot(world, Vector(Direction.NORTH, 100, 100), PivotInstruction.PIVOT_LEFT_90)
        assert path is not None, "the ordinary grid already refuses it, so this proves nothing"

        chebyshev, euclidean = _nearest_blocked(world, [(100, 100)] + [(v.x, v.y) for v in path])

        # Both worlds are inside the BOX, so an L-infinity erosion cannot tell them apart.
        assert chebyshev <= delta
        assert (euclidean <= delta) is inside, (chebyshev, euclidean)
        assert table[code](100, 100) is not inside


def _pocket_world():
    """
    A sealed corridor 37 cells wide, with the target obstacle set into its far wall.

    Four obstacles stacked at x = 72 block x = 51..102 at every y, so the free strip along the
    west wall - x = 14..50 - is a dead end with no way round. The robot starts in it at
    (23, 60) facing NORTH. The second obstacle faces WEST, into the corridor, and is the only
    one whose goal poses are inside it.

    37 cells is chosen, and it is the whole point of the arena. The narrowest quarter turn out
    of NORTH is BACKWARD_LEFT, which sweeps 37 cells to the west of wherever it starts and so
    needs 38; the widest, FORWARD_LEFT, needs 52. A 90 degree pivot sweeps 19 cells to one side
    and needs 7 more for the rotation clearance, so it fits in 34. The corridor is therefore
    wide enough to turn on the spot in and too narrow to turn in, which is exactly the
    situation the primitive was added for and is otherwise hard to come by: with a backward
    straight available the planner can usually reach any pose it can see, and a pocket tight
    enough to prevent that is usually tight enough to prevent a pivot too.
    """
    robot = Robot.planned(Direction.NORTH, Point(8, 45), Point(38, 75))
    return World(config.GRID_SIZE, robot, [
        Obstacle(Direction.EAST, Point(72, 21), Point(81, 30), 1),
        Obstacle(Direction.WEST, Point(72, 73), Point(81, 82), 2),
        Obstacle(Direction.EAST, Point(72, 125), Point(81, 134), 3),
        Obstacle(Direction.EAST, Point(72, 177), Point(81, 186), 4),
    ])


def _pocket_route(world):
    """The raw search result for `_pocket_world`, and the moves along it."""
    found = segment(world, world.robot.vector, generate_objectives(world).objectives)
    assert found is not None, "the pocket's obstacle is unreachable even with pivots on"
    return found, [move for _pose, move in found[2] if move is not None]


def test_an_obstacle_out_of_reach_without_pivots_is_reachable_with_them():
    """
    The payoff, in its strong form: an obstacle the planner cannot reach at all, and reaches
    once it may turn on the spot. Same world, same weights, one flag.

    The arena is built rather than borrowed, and `_pocket_world` says why it has to be. The
    corridor is 37 cells wide, which is below every quarter turn's sweep out of NORTH and above
    a 90 degree pivot's. So the robot, which starts facing NORTH, can never face anything else
    without a pivot - and the obstacle's goal poses all face EAST.

    The proof is not left to the two None/not-None answers, which would also be produced by an
    arena that merely got harder. The search's own move table is asserted directly: at the only
    x the robot can ever occupy, every one of the four quarter turns is refused at every y in
    the arena. With the flag off there is no move in the graph that changes the robot's
    heading, so the None is not a budget, a bound or a tie-break - it is the whole EAST-facing
    half of the state space being disconnected from where the robot stands.
    """
    world = _pocket_world()
    start = world.robot.vector
    assert (start.direction, start.x) == (Direction.NORTH, 23)

    _chunks, table = _table_of(world, Direction.NORTH)
    quarters = sorted(code for code in table if code <= len(_TURNS))
    assert [_TURNS[code - 1] for code in quarters] == [
        t for t in TurnInstruction if t.degrees == 90], "a quarter turn is missing from the table"
    for code in quarters:
        assert not any(table[code](start.x, y) for y in range(config.GRID_SIZE)), \
            f"{_TURNS[code - 1].value} fits in the corridor after all"

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(config, "PIVOT_TURNS", False)
        assert segment(world, start, generate_objectives(world).objectives) is None

    found, moves = _pocket_route(world)
    obstacle, _cost, _parts = found

    assert obstacle.image_id == 2
    assert [move.pivot for move in moves if isinstance(move, Pivot)] \
        == [PivotInstruction.PIVOT_RIGHT_90]


def test_a_traced_pivot_comes_back_as_a_pivot_move():
    """
    `_Search.__move` decodes a move code into the object that made it, and a pivot's codes sit
    in a third range after the turns and the straight chunks.

    The decode is arithmetic over two lengths, one of which (`chunks`) is config read at search
    time, so it is the kind of thing that is right for the shipped chunk set and wrong for
    another. Off by one into the straights and a pivot is rebuilt as a five-cell FORWARD: the
    route still traces, the poses still line up, and the robot is told to drive through the
    corner it was supposed to rotate in.

    So the move is checked against the primitive itself - same instruction, same cells, in the
    same order - and against the pose the search recorded beside it. Those come from two
    different places: the cells from `pivot()` re-run on the pose the move started from, the
    pose from the index the table's delta landed on. A delta that disagreed with the geometry
    would show up here as the last cell missing the recorded pose.
    """
    world = _pocket_world()
    found, moves = _pocket_route(world)
    parts = found[2]

    shuffles = [(before, after, move)
                for (before, _), (after, move) in zip(parts, parts[1:])
                if isinstance(move, Pivot)]
    assert len(shuffles) == 1

    before, after, move = shuffles[0]
    assert move.pivot is PivotInstruction.PIVOT_RIGHT_90
    assert move.vectors == pivot(world, before, move.pivot)
    assert move.vectors[-1] == after
    assert not isinstance(move, (Turn, Move))


def test_compress_carries_a_pivot_into_the_segment():
    """
    `Segment.compress` matches on the kind of move, and its match has no fallthrough: a `Pivot`
    it does not name is not an error, it is a move that vanishes.

    What survives is a segment whose `vectors` jump from the cell before the pivot to the cell
    after it, whose `instructions` never mention it, and whose `cost` and `seconds` are the
    route without it. Every one of those is internally consistent and wrong, and the wire
    format has no place to notice - the robot is handed a plan that drives straight into the
    manoeuvre's end pose facing the wrong way.

    The invariants asserted are the two `compress` is FOR: the moves come out in driving order
    with nothing dropped, and `vectors` is exactly their cells concatenated. Then the
    instruction list is spelled out, because a pivot must not be swallowed by the straight run
    it interrupts: the two forward chunks before it merge into one 10 cm command, and the pivot
    is its own instruction after them.
    """
    world = _pocket_world()
    found, moves = _pocket_route(world)
    compressed = Segment.compress(world, found)

    assert any(isinstance(move, Pivot) for move in moves)
    assert compressed.moves == moves
    assert compressed.vectors == [vector for move in moves for vector in move.vectors]

    assert [instruction if not isinstance(instruction, MoveInstruction)
            else (instruction.move, instruction.amount)
            for instruction in compressed.instructions] == [
        (Straight.FORWARD, 10),
        PivotInstruction.PIVOT_RIGHT_90,
        MiscInstruction.CAPTURE_IMAGE,
    ]

    assert compressed.cost == round(
        sum(cost.move_cost(move, cost.DISTANCE_CELLS, world.cell_size) for move in moves))
    assert compressed.seconds == pytest.approx(cost.seconds(moves, world.cell_size))


def test_a_straight_after_a_pivot_starts_a_new_command():
    """
    The merge rule `compress` applies to consecutive straights, checked across a pivot.

    A run of FORWARD chunks is accumulated into ONE `MoveInstruction` and converted to
    centimetres once, which is what keeps a merged diagonal run from drifting a centimetre per
    merge. A pivot in the middle of such a run ends it: the car stops, shuffles round and sets
    off again, and the two halves are different commands on different headings. Fold them
    together and the STM is told to drive the whole distance before the rotation - which is a
    plausible thing for a `Pivot` case to cause, since it is the case that has to leave the
    accumulator alone.
    """
    north = [Vector(Direction.NORTH, 23, 60 + n) for n in range(1, 6)]
    east = [Vector(Direction.EAST, 29 + n, 57) for n in range(1, 6)]
    shuffle = Pivot(PivotInstruction.PIVOT_RIGHT_90, [Vector(Direction.EAST, 29, 57)])
    world = _pocket_world()
    obstacle = world.obstacles[1]

    parts = [(Vector(Direction.NORTH, 23, 60), None),
             (north[-1], Move(Straight.FORWARD, north)),
             (shuffle.vectors[-1], shuffle),
             (east[-1], Move(Straight.FORWARD, east))]

    compressed = Segment.compress(world, (obstacle, 0.0, parts))

    assert [instruction if not isinstance(instruction, MoveInstruction)
            else (instruction.move, instruction.amount)
            for instruction in compressed.instructions] == [
        (Straight.FORWARD, 5),
        PivotInstruction.PIVOT_RIGHT_90,
        (Straight.FORWARD, 5),
        MiscInstruction.CAPTURE_IMAGE,
    ]
    assert compressed.vectors == north + shuffle.vectors + east


@pytest.mark.parametrize("cell, corner", (
    ("the cell it starts from", (70, 63)),
    ("the cell it comes to rest on", (76, 60)),
))
def test_both_ends_of_a_pivots_path_are_checked_for_rotation_clearance(cell, corner):
    """
    The two cells at the ends of a pivot's centre path, each of which is easy to leave out and
    neither of which any other test in this file can see.

    `pivot()`'s sampling loop begins at STEP 1, so the path it returns never contains the cell
    the manoeuvre starts from - the cell the car is standing on as it begins to rotate, and the
    one cell it is certain to occupy. Fold the returned path straight into a mask and that cell
    is checked by nothing. At the other end the path's last cell IS the end pose, so treating a
    pivot like a turn - arc checked, end pose appended unchecked - drops the cell the car comes
    to rest on, still rotated off its axis.

    Both are single cells at the edge of a roughly thirty-cell path, so an arena that catches
    one has to be built to isolate it: every OTHER cell of the pivot must have its seven cells
    of rotation clearance while that one does not. Obstacle inflation is a rectangle 52 cells
    on a side, so the only shape that can be brought that close to one cell of a path without
    touching its neighbours is a CORNER, and each world here is one obstacle placed so that its
    inflated north-east corner falls seven cells from the cell under test and more than seven
    from every other. The pivot is legal on the ordinary grid in both.

    Left out, the mask says yes and the planner drives a rotation through an obstacle at one
    end of it or the other. Nothing downstream looks again.
    """
    robot = Robot.planned(Direction.NORTH, Point(0, 0), Point(30, 30))
    south_west = Point(*corner)
    world = World(config.GRID_SIZE, robot,
                  [Obstacle(Direction.EAST, south_west,
                            Point(south_west.x + 9, south_west.y + 9), 1)])
    start = Vector(Direction.NORTH, 100, 100)
    path = pivot(world, start, PivotInstruction.PIVOT_RIGHT_90)

    assert world.contains(start)
    assert path is not None, "the ordinary grid already refuses it, so this proves nothing"

    delta = _clearance(world)
    interior = [(v.x, v.y) for v in path[:-1]]
    under_test = (start.x, start.y) if "starts" in cell else (path[-1].x, path[-1].y)

    # Exactly one cell of the manoeuvre is short of clearance, and it is the one named.
    assert _nearest_blocked(world, [under_test])[1] <= delta, cell
    assert _nearest_blocked(world, set(interior) - {under_test})[1] > delta, cell

    chunks, table = _table_of(world, Direction.NORTH)
    assert not table[_pivot_code(PivotInstruction.PIVOT_RIGHT_90, chunks)](100, 100)


def test_the_virtual_boundary_is_not_eroded_but_is_still_a_wall():
    """
    The arena's edge is a LINE ON THE FLOOR, and the clearance model must not promote it to an
    obstacle. This is the test that fails if someone erodes `free_cells` wholesale.

    `config.BOUNDARY_CLEARANCE_ADJUST_CM` is negative on purpose: the boundary is virtual, so
    clipping it costs nothing and the keep-out band is deliberately one centimetre SOFTER than
    the robot's half-extent. Eroding that band by the rotation disc inverts the intent - the
    same line would be seven cells HARDER than a real obstacle for a pivot and a centimetre
    softer than one for every other primitive, in the same search, from the same grid. It is
    not a small effect either: on `04-five-obstacles` it costs about 17% of all free cells.

    Two cells, one either side of the sharp edge, and they pull in opposite directions:

    * At x = 32 a `PIVOT_LEFT_90` swings its centre out to x = 14, the first legal cell of the
      arena. Every cell of the manoeuvre is a legal centre cell, and the only thing within
      seven cells of the swing is the virtual line. It must be OFFERED. Under an erosion of
      the whole grid it is refused, and this assertion is what says so.
    * At x = 31 the same swing reaches x = 13, which is inside the keep-out band. The robot's
      CENTRE may not go there, virtual boundary or not, and the corresponding hard property is
      that the eroded grid stays a subset of the free one. It must be REFUSED - and it is
      refused for the ordinary reason, which `pivot()` agrees with.

    So relaxing the boundary for the clearance disc must not relax it for the path itself.
    """
    world = empty_world()
    chunks, table = _table_of(world, Direction.NORTH)
    code = _pivot_code(PivotInstruction.PIVOT_LEFT_90, chunks)

    fits = pivot(world, Vector(Direction.NORTH, 32, 100), PivotInstruction.PIVOT_LEFT_90)
    assert fits is not None
    assert min(vector.x for vector in fits) == 14, "the swing no longer grazes the band"
    assert table[code](32, 100), "the virtual boundary was eroded as though it were an obstacle"

    assert pivot(world, Vector(Direction.NORTH, 31, 100), PivotInstruction.PIVOT_LEFT_90) is None
    assert not table[code](31, 100)


@pytest.mark.parametrize("world_of, instruction", (
    (empty_world, PivotInstruction.PIVOT_LEFT_90),
    (empty_world, PivotInstruction.PIVOT_RIGHT_90),
    (_crowded_world, PivotInstruction.PIVOT_LEFT_90),
    (_pocket_world, PivotInstruction.PIVOT_RIGHT_90),
))
def test_every_pivot_the_table_offers_is_one_the_ordinary_grid_allows(world_of, instruction):
    """
    The eroded grid must stay a SUBSET of the free one, over every cell of every arena.

    Rotation clearance is an extra condition on top of the ordinary one, never a replacement
    for it, and the two places that assumption is cashed in are both silent when it breaks.
    `_Search.__move` re-runs `pivot()` against the world's ordinary grid to rebuild a traced
    move and asserts the result is not None - that assertion is sound only because erosion
    clears cells and never frees them. And a pivot the table offered but the grid refuses is a
    centre path through an obstacle or over the arena's edge.

    Relaxing the virtual boundary for the disc is exactly the change that could break it, since
    it hands the erosion a grid in which the keep-out band is free, so the subset property is
    asserted here cell by cell rather than read off the `& free_cells` that produces it.
    """
    world = world_of()
    chunks, table = _table_of(world, Direction.NORTH)
    offered = [(x, y)
               for x in range(world.size) for y in range(world.size)
               if table[_pivot_code(instruction, chunks)](x, y)]

    assert offered, "nothing was offered, so the subset property is vacuous here"
    assert all(pivot(world, Vector(Direction.NORTH, x, y), instruction) is not None
               for x, y in offered)


def _pocket_playback():
    """
    The pocket route as the simulator animates it: one segment, one 90 degree pivot in it.

    Built through `Segment.compress` and `Route` rather than by hand, so the frames come off
    the same `segment.moves` list the window plays and not a fixture that agrees with the
    animator by construction.
    """
    world = _pocket_world()
    found, _moves = _pocket_route(world)
    compressed = Segment.compress(world, found)
    route = Route([compressed], [], "test", 0.0, world.robot, world.cell_size)
    return world, compressed, Playback(route)


def _frames_of(playback, compressed, wanted):
    """
    `(index of its first frame, its frames)` for one move of a compressed segment.

    Relies on the rule every other consumer of `Playback` relies on - one frame per cell of
    `move.vectors`, in driving order - so a move that animated to some other number of frames
    would misalign every move after it. `test_playback.py::test_frames_are_cells_plus_dwell`
    pins the same rule from the other end, for routes without pivots in them.
    """
    start = 0
    for move in compressed.moves:
        if move is wanted:
            return start, playback.frames[start:start + len(move.vectors)]
        start += len(move.vectors)
    raise AssertionError("that move is not in this segment")


def _swept(frames, instruction, end_deg):
    """How far round its own swing each frame is, in degrees, 0 at the start and `degrees` at the end."""
    sense = 1 if instruction.clockwise else -1
    start_deg = (end_deg - sense * instruction.degrees) % 360
    return [((frame.pose.heading_deg - start_deg) * sense) % 360 for frame in frames]


def test_playback_rotates_through_a_pivot():
    """
    The payoff: the car must be seen to ROTATE through a pivot, not slide through it.

    A pivot's cells all carry the POST-pivot heading, exactly as a turn's arc cells do, because
    `Vector` has nowhere to put the 22.5 degrees a shuffle passes through. Played back as they
    stand, every frame below would sit at the full swing and the car would cross the manoeuvre
    already facing where it ends up - which is what a `Pivot` used to do, since it is neither a
    `Turn` nor a `Move` and fell through to the branch that walks vectors as straight travel.

    So the assertion is on the frames strictly BETWEEN the two headings, and it is one that can
    actually fail: the bug produced a list of 90.0s, and that is the trap
    `test_diagonals.py::test_playback_rotates_through_a_45_degree_turn` records having fallen
    into - "the set of headings mod 45" was satisfied by any non-empty frame list at all.
    """
    world, compressed, playback = _pocket_playback()
    shuffles = [move for move in compressed.moves if isinstance(move, Pivot)]
    assert len(shuffles) == 1, "no pivot in this route, so it proves nothing about pivots"
    move, = shuffles
    start, frames = _frames_of(playback, compressed, move)

    end_deg = HEADING_DEG[move.vectors[-1].direction]
    swing = move.pivot.degrees
    swept = _swept(frames, move.pivot, end_deg)

    # One frame per cell, so the pivot occupies exactly its own cells in the timeline and every
    # move after it still lines up.
    assert len(playback.frames) == len(compressed.vectors) + CAPTURE_DWELL_FRAMES
    assert len(frames) == len(move.vectors)

    # Monotone, starting past the start heading and ending exactly on the end heading. Monotone
    # is the physical claim: both strokes of a shuffle swing the nose the same way, so the
    # heading never backs up part way through.
    assert swept == sorted(swept)
    assert 0 < swept[0] < swing and swept[-1] == swing
    assert frames[-1].pose.heading_deg == end_deg

    between = [s for s in swept if 0 < s < swing]
    assert len(between) >= len(frames) // 2, (
        f"only {len(between)} of {len(frames)} frames face anywhere between "
        f"{(end_deg - swing) % 360} and {end_deg}; the car is not rotating, it is sliding")
    # And finely enough to read as a rotation rather than a snap.
    assert max(b - a for a, b in zip(swept, swept[1:])) <= 5

    # Placed ON the cells. A pivot's path is the robot's CENTRE, where a turn's arc is the rear
    # point `lead` behind it, so the turn branch's lift onto a circle and its `lead` offset are
    # both wrong here and would walk the car away from the cells the planner collision-checked.
    assert [(frame.pose.x, frame.pose.y) for frame in frames] \
        == [(vector.x, vector.y) for vector in move.vectors]
    assert playback.frames[start - 1].pose.heading_deg == (end_deg - swing * (
        1 if move.pivot.clockwise else -1)) % 360
