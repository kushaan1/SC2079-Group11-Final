"""
What a move costs. Two models: DISTANCE_CELLS is the search's original objective (grid cells,
arc_length cells per turn); TIME_SECONDS is the estimate the optimiser minimises and the
simulator clock shows. Both read config at call time.
"""
from __future__ import annotations

from math import radians, sqrt

from typing import Iterable, Protocol

import config
from pathfinding.search.instructions import Move, Pivot, PivotInstruction, Turn, TurnInstruction
# The two steering locks one pivot alternates, keyed by which way its nose swings. Imported from
# the geometry rather than restated here, for the reason that table's own comment gives: it is
# derived from `turn._ANTICLOCKWISE`, and a second copy could disagree with it silently. What
# disagreement would cost HERE is a pivot priced against the wrong two radii - wrong only by the
# forward/backward gap, half a percent at the shipped numbers, and invisible in a route.
from pathfinding.search.pivot import _LOCKS
from pathfinding.world.primitives import Direction


class Weights(Protocol):
    def turn(self, turn: TurnInstruction, cell_size: int = 1) -> float: ...

    def pivot(self, instruction: PivotInstruction, cell_size: int = 1) -> float: ...

    def straight(self, cells: float, cell_size: int = 1) -> float: ...


class _Distance:
    """
    The search's original objective: grid cells. A straight costs its cell count, a turn costs
    ``arc_length`` in cells and a pivot the sum of its strokes' arcs, so the halves add.
    Consumers that want centimetres multiply by ``cell_size`` themselves (the simulator does);
    at the default 1 cm cell the two are the same number.
    """

    def turn(self, turn: TurnInstruction, cell_size: int = 1) -> float:
        return turn.arc_length(cell_size)

    def pivot(self, instruction: PivotInstruction, cell_size: int = 1) -> float:
        """
        The ground a pivot's wheels cover, in cells: the sum of its strokes' arc lengths.

        A pivot arrives where it started, so the tempting number here is zero - and zero is the
        one answer this must not give. This model prices a turn at its ARC LENGTH, the ground
        covered rather than the displacement achieved, and a shuffle is several such arcs driven
        alternately. Charging displacement instead would hand the distance-weighted search a
        free self-loop it could take as often as it liked, at every state, for nothing.

        Half the strokes run on the forward lock and half on the backward one - that is what
        makes a shuffle a shuffle - and each sweeps ``degrees / strokes``, so the total is
        ``(strokes / 2) * radians(theta) * (R_forward + R_backward)``. Both radii go through
        :meth:`TurnInstruction.radius`, which reads ``config.TURN_RADIUS_CM`` at call time and
        floors it into cells exactly as `pivot.py` floors it, so the cost and the geometry are
        derived from one set of numbers rather than two that have to be kept in step.

        The stroke count CANCELS out of that expression - ``(s / 2) * radians(d / s)`` is
        ``radians(d) / 2`` for any ``s`` - and it is written out anyway, in the form the
        manoeuvre is actually derived in, because the cancellation is the interesting part
        rather than an accident to tidy away. It says the ground a shuffle covers is the same
        however finely it is chopped up, so the STM owner may retune ``PIVOT_STROKES_PER_45``
        without repricing a single route: only the drift and the swept box respond to that
        choice, which is exactly the ground `config.py` argues it on. `tests/test_pivot.py`
        pins the invariance, and pins it as behaviour rather than as an implementation detail -
        collapsed to `radians(d) / 2` this would read as a formula that simply forgot about
        strokes, which is a different and much less trustworthy-looking claim.

        The figures this produces are not small: at the shipped radii a 90 degree pivot covers
        about 60 cells of wheel travel against a quarter turn's 63, for none of that turn's
        52 by 28 cm of progress. Nearly as dear as the arc and achieving nothing - the same
        verdict :meth:`_Time.pivot` reaches by a different route, which is what one would want
        of two models of the same manoeuvre.
        """
        strokes = instruction.strokes()
        theta = instruction.degrees / strokes
        forward, backward = _LOCKS[instruction.clockwise]
        return (strokes / 2) * radians(theta) * (
            forward.radius(cell_size) + backward.radius(cell_size)
        )

    def straight(self, cells: float, cell_size: int = 1) -> float:
        return cells


class _Time:
    """Estimated seconds: a charge proportional to the swing per turn or pivot, distance over
    speed per straight."""

    def turn(self, turn: TurnInstruction, cell_size: int = 1) -> float:
        # TURN_TIME_S is quoted per 90 degrees. A 45 is the same steering lock held for half as
        # long - same radius, half the arc - so it is charged half. Flat-rating both would price
        # two 45s exactly like one 90 that covers twice the ground, which is the sort of tie the
        # optimiser resolves by picking the wrong one.
        return config.TURN_TIME_S * turn.degrees / 90

    def pivot(self, instruction: PivotInstruction, cell_size: int = 1) -> float:
        """
        Seconds for one pivot: ``PIVOT_TIME_S`` per 45 degrees, the whole shuffle included.

        PIVOT_TIME_S is quoted per 45 where TURN_TIME_S is quoted per 90, because 45 is the
        smallest pivot there is: a 90 is not a manoeuvre of its own, it is the same shuffle kept
        up for twice as many strokes, so it is charged twice. ``cell_size`` is accepted to match
        :meth:`turn` and ignored for the same reason - a manoeuvre's duration is a property of
        the car, not of the grid resolution the planner happens to reason on.

        **The economics, which are the whole point of the primitive.** At the figures shipped
        today a 45 degree pivot costs 2.0 s against 1.5 s for a 45 degree arc, and a 90 costs
        4.0 against 3.0. A pivot is therefore ALWAYS dearer in time than the turn it replaces,
        and it gains no ground while being dearer: a quarter-turn arc carries the robot (52, 28)
        cm of useful travel, a shuffle carries it about 6, and that 6 is drift it did not ask
        for rather than progress.

        That inequality is deliberate, and what it buys is that a pivot is never a cheaper way
        of doing what a turn already does. What it does NOT buy - and an earlier draft of this
        docstring, and of the design spec, both claimed that it did - is that a pivot stays out
        of open ground. The comparison above is against the SINGLE turn a pivot replaces, and
        the search does not substitute one move for one move: it substitutes a sequence. A
        quarter turn buys its heading and 52 by 28 cm of displacement in the same breath, and
        where that displacement is not where the route wanted to go it has to be undone - by a
        straight, or by another turn, or by both.

        So a pivot wins wherever the corrective travel it avoids is dearer than the premium it
        charges, and that happens on perfectly open arenas. `04-five-obstacles`, image 11,
        priced under this model, from the robot's own start pose to the same goal-pose set with
        only the flag changed:

            without   FORWARD 50, BACKWARD_RIGHT, BACKWARD 30, FORWARD_RIGHT, BACKWARD 20   9.33 s
            with      FORWARD 5, PIVOT_RIGHT_90, FORWARD 5, FORWARD_LEFT, BACKWARD 20       8.00 s

        The mechanism is legible in the first three commands. Without a pivot the route has to
        drive 50 cm up the arena to buy the room for a quarter turn, and then reverse 30 cm of
        that straight back out again, because it wanted the heading and not the journey. With
        one it rotates after 5 cm. The pivot is dearer than the `BACKWARD_RIGHT` it stands in
        for and 1.33 s cheaper than that turn plus the 75 cm of straight the turn dragged in
        with it. The largest such saving on this arena is image 13's, 23.17 s to 18.33 s.

        Whole routes move the same way: :func:`~pathfinding.search.tour.plan_optimal` takes
        this arena from 62.33 s to 52.00 s with the flag on. Per-LEG figures out of that
        comparison are not like for like and should not be quoted - the visit order changes
        between the two plans, so a given obstacle's leg starts from a different pose in each.
        The per-leg numbers above are one-obstacle searches from one fixed start pose, which is
        the comparison that isolates the primitive. The primitive is doing better than it was
        specified to, not worse.

        The claim this model supports is therefore the narrow one, and it is the one to quote:
        a pivot costs more than the turn it replaces, so the search reaches for one only where
        rotating on the spot saves more travel than the premium costs. Nothing fences the
        primitive off from open space and nothing needs to - where an arc's displacement IS
        wanted, the arc is both cheaper and productive and wins on its own.

        It is the INEQUALITY that matters here rather than the constants, and it is asserted in
        `tests/test_pivot.py` rather than left to this docstring, because the small plausible
        mistake breaks it: charge PIVOT_TIME_S per 90 degrees by symmetry with TURN_TIME_S and a
        45 drops to 1.0 s, under the arc, and the search starts being paid to rotate.
        """
        return config.PIVOT_TIME_S * instruction.degrees / 45

    def straight(self, cells: float, cell_size: int = 1) -> float:
        return cells * cell_size / config.ROBOT_SPEED_CM_S


DISTANCE_CELLS: Weights = _Distance()
TIME_SECONDS: Weights = _Time()


# A diagonal step crosses both axes, so one cell of it is this much ground.
_DIAGONAL = sqrt(2)


def straight_cells(direction: Direction, cells: float) -> float:
    """
    The ground covered by ``cells`` steps along ``direction``, in cells.

    A diagonal step crosses both axes, so it covers sqrt(2) cells rather than one. Everything
    that prices a straight goes through here - this function, the search's move tables, and the
    centimetres in a MoveInstruction - so a route is chosen under the same numbers it is
    reported and driven under. Pricing a diagonal at 1 in the search and 1.41 in the report is
    not a rounding difference: it makes the search prefer diagonals it would not have chosen if
    it were paying for them.
    """
    return cells * _DIAGONAL if direction.diagonal else cells


def move_cost(move: Turn | Pivot | Move, weights: Weights, cell_size: int) -> float:
    """
    The cost of one move under ``weights``.

    The straight case is the fallthrough, which is why every other kind of move must be named
    above it: an unrecognised move is not an error here, it is silently charged
    ``len(move.vectors)`` cells of forward travel. For a pivot that is a handful of cells - the
    search would be told a rotation on the spot is nearly free and would take one wherever it
    liked, which is the exact opposite of what the pricing is for.
    """
    if isinstance(move, Turn):
        return weights.turn(move.turn, cell_size)
    if isinstance(move, Pivot):
        return weights.pivot(move.pivot, cell_size)
    cells = len(move.vectors)
    if move.vectors:
        cells = straight_cells(move.vectors[0].direction, cells)
    return weights.straight(cells, cell_size)


def seconds(moves: Iterable[Turn | Pivot | Move], cell_size: int) -> float:
    """Estimated driving time of a sequence of moves under the time model."""
    return sum((move_cost(m, TIME_SECONDS, cell_size) for m in moves), 0.0)
