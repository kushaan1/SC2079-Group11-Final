# Derived from Pante/SC2079 (AY2023 S2, Group 14). See algorithm/PROVENANCE.md
"""
Structured reporting for obstacles the planner could not plan.

An obstacle that silently vanishes from a plan is lost points with no diagnostic. The
reference dropped them with a ``print()``, which is invisible to the RPi, invisible to a
test, and invisible to anyone reading a JSON response. This module holds the two types that
make a dropped obstacle **data** instead.

The types live here, above both ``world.objective`` and ``search.search``, because both
layers produce them: goal-pose generation can fail (:attr:`UnreachableReason.NO_OBJECTIVES`)
and the search over generated goal poses can fail (:attr:`UnreachableReason.NO_PATH`). They
are plain dataclasses rather than pydantic models for the same reason ``Segment`` is: the
planner layer states the domain fact, and the HTTP layer decides how to serialise it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class UnreachableReason(str, Enum):
    """
    Why the planner produced no path to an obstacle.

    There are exactly two reasons, and they are NOT interchangeable — they point at
    different problems and at different fixes:

    - :attr:`NO_OBJECTIVES` — goal-pose generation produced nothing. Every candidate pose in
      the standoff band was rejected by ``World.contains()``, so the search was never given a
      target. This is a *geometry* failure, not a routing one.

      **It does not say WHICH geometry, and you must not guess.** ``World.contains()``
      rejects a pose for either of two unrelated reasons — it lies outside the arena's free
      band, or inside another obstacle's inflated keep-out — and reports neither. The two
      have opposite remedies, so this reason code alone is not enough to tune on:

      * *Wall clearance* — the obstacle faces a wall it sits too close to, and its poses are
        already beyond the boundary. Widening the standoff band pushes them further out and
        never helps; only LOWERING ``config.STANDOFF_MIN_CM`` brings them back inside.
      * *Neighbour crowding* — a nearby obstacle's keep-out swallows the poses. Here
        widening ``config.LATERAL_TOLERANCE_CM``, or pushing the band out far enough to
        clear the neighbour entirely, is what helps.

      To tell them apart, plan the obstacle ON ITS OWN: still no pose means the wall; poses
      alone but none in company means a neighbour. Both modes occur in the pathological
      arena in ``smoke.py``, one obstacle each. A coverage tool would quantify the
      wall-clearance mode across the arena; it does not measure the crowding mode.
    - :attr:`NO_PATH` — goal poses exist, but the search reached none of them from where the
      robot stood. This is a *reachability* failure: the target is fine, the route is not
      (boxed in by other obstacles, or the turning primitives cannot thread the gap).

    A ``str`` enum, so ``json.dumps`` and pydantic both emit the bare name and a client can
    compare against the literal string.
    """

    NO_OBJECTIVES = 'NO_OBJECTIVES'
    NO_PATH = 'NO_PATH'


@dataclass(frozen=True)
class UnreachableObstacle:
    """
    One obstacle the plan does not visit, and why.

    Frozen so it is hashable and safe to compare as a set in a test.

    :param image_id: The ``image_id`` of the obstacle that was dropped. This is the handle
        every other team knows the obstacle by — the Android tablet sets it, the RPi relays
        it, and CV reports against it — so it, not a grid coordinate, is what identifies a
        dropped obstacle.
    :param reason: Which of the two failures occurred. See :class:`UnreachableReason`.
    """

    image_id: int
    reason: UnreachableReason
