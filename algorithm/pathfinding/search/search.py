# Derived from Pante/SC2079 (AY2023 S2, Group 14). See algorithm/PROVENANCE.md
from __future__ import annotations

import logging
from dataclasses import dataclass

from pathfinding import cost
from pathfinding.report import UnreachableObstacle, UnreachableReason
from pathfinding.search.instructions import Turn, TurnInstruction, Move, MoveInstruction, MiscInstruction
from pathfinding.search.segment import segment
from pathfinding.world.objective import ObjectiveGeneration
from pathfinding.world.primitives import Vector
from pathfinding.world.world import World, Obstacle

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """
    A complete plan: what the robot will do, and what it will NOT do.

    ``unreachable`` is the whole point of this type. The reference returned a bare
    ``list[Segment]``, so an obstacle that fell out of the plan left no trace anywhere a
    caller could see — the warning went to stdout on the planning machine and the HTTP
    response simply had one fewer segment than the request had obstacles. At competition
    time that is lost points with no diagnostic.

    :param segments: One segment per obstacle the robot will actually visit, in visit order.
    :param unreachable: Every obstacle that will NOT be visited, each with the reason.

        ``segments`` and ``unreachable`` partition the world's obstacles: every obstacle
        appears in exactly one of them, and no ``image_id`` appears in both. That is
        enforced, not merely intended — :func:`require_accounting` rejects an
        :class:`~pathfinding.world.objective.ObjectiveGeneration` that does not account for
        exactly ``world.obstacles``, and both functions that build a SearchResult
        (:func:`search` and :func:`~pathfinding.search.tour.plan_optimal`) call it first, so
        a non-partitioning result cannot be constructed by the only code that constructs one.

        Order is deterministic, and the two planners produce it differently:

        - :func:`search` appends
          :attr:`~pathfinding.report.UnreachableReason.NO_OBJECTIVES` entries first (carried
          through from goal-pose generation, in ``world.obstacles`` order), then the
          :attr:`~pathfinding.report.UnreachableReason.NO_PATH` entries in goal-pose order —
          the order of the ``remaining`` dict at the moment it gave up.
        - :func:`~pathfinding.search.tour.plan_optimal` also carries the NO_OBJECTIVES
          entries through first, then makes ONE pass over the obstacles that had goal poses,
          in ``world.obstacles`` order, appending every one its chosen route does not
          photograph. So its NO_PATH entries are in ``world.obstacles`` order, and they are
          derived from the route that won rather than decided in advance — which is what
          keeps the two lists partitioning when several candidate routes were in play.

        Compare it as a set if that order is not what a caller cares about.
    """

    segments: list[Segment]
    unreachable: list[UnreachableObstacle]


def require_accounting(world: World, generated: ObjectiveGeneration) -> None:
    """
    The precondition behind :class:`SearchResult`'s partition guarantee, enforced rather than
    merely written down.

    ``generated`` must account for exactly the obstacles in ``world``. That holds by
    construction for ``generate_objectives(world)``, and stops holding the moment anyone
    hands over a filtered dict. The controller serialises ``unreachable`` over HTTP as the
    definitive list of obstacles the robot will not visit, so a result that quietly fails to
    partition is a wire-level lie about the plan - the exact class of silent failure the
    structured report exists to remove. It also catches two obstacles that collapsed into one
    dict key, by comparing image_ids as a multiset rather than a set.

    Every function that builds a SearchResult calls this FIRST - :func:`search` and
    :func:`~pathfinding.search.tour.plan_optimal` alike. Microseconds on <=8 obstacles, and
    it fails at the mistake rather than seconds later with a plausible-looking answer.

    :raises ValueError: If ``generated`` does not account for exactly ``world.obstacles``.
    """
    offered = sorted([obstacle.image_id for obstacle in generated.objectives]
                     + [entry.image_id for entry in generated.unreachable])
    present = sorted(obstacle.image_id for obstacle in world.obstacles)
    if offered != present:
        raise ValueError(
            f"ObjectiveGeneration does not account for this world's obstacles: it offers "
            f"image_ids {offered}, the world holds {present}. Pass the ObjectiveGeneration "
            f"that generate_objectives() returned for THIS world; to plan a subset of the "
            f"obstacles, build a World containing that subset."
        )


def search(world: World, generated: ObjectiveGeneration) -> SearchResult:
    """
    Plan a route visiting as many obstacles as it can, greedily nearest-first.

    :param world: The world.
    :param generated: The output of
        :func:`~pathfinding.world.objective.generate_objectives` for this same world. The
        whole object is taken, not just its dict, so that the obstacles which never got a
        goal pose are carried into the result instead of being lost between the two calls —
        that is what makes NO_OBJECTIVES and NO_PATH genuinely distinguishable rather than
        guessed at from a set difference.
    :return: A :class:`SearchResult` holding the segments and every obstacle not visited.
    :raises ValueError: If ``generated`` does not account for exactly ``world.obstacles``.
    """
    require_accounting(world, generated)

    # Copy before mutating. The reference popped from the caller's dict, so after a search
    # the caller's `objectives` was empty and the same world could not be re-planned or
    # inspected. The inner (Vector, set[Vector]) values are shared, never mutated.
    remaining = dict(generated.objectives)

    # The NO_OBJECTIVES half is produced by the layer that can actually observe it, and is
    # carried through verbatim. This function only ever appends NO_PATH.
    unreachable: list[UnreachableObstacle] = list(generated.unreachable)

    segments: list[Segment] = []
    current = world.robot.vector

    # The reference looped `for _ in world.obstacles` - once per OBSTACLE rather than once
    # per remaining goal-pose set. When some obstacles had no goal poses, the FIRST surplus
    # iteration called segment() with nothing left to find, exhausted the entire grid, and
    # returned None; the reference read that None as failure and returned immediately. So
    # exactly ONE wasted exhaustive search ever happened, not one per surplus obstacle - but
    # that single call cost 11.9 s on the pathological arena, against 0 ms here.
    #
    # The two loop forms yield identical segments whenever the number of goal-pose sets does
    # not exceed len(world.obstacles), since each successful iteration pops exactly one.
    # generate_objectives emits at most one entry per obstacle and so cannot violate that;
    # the precondition check above now enforces it rather than leaving it assumed.
    while remaining:
        seg = segment(world, current, remaining)
        if seg is None:
            # NO_PATH, not NO_OBJECTIVES: everything still in `remaining` HAS goal poses -
            # generate_objectives put it here precisely because it had some. segment() runs a
            # single search against ALL of them at once and returns None only when the
            # frontier is exhausted, so reaching here means not one of them is reachable.
            #
            # Honest caveat: "unreachable" is relative to where this plan left the robot
            # standing. A different visit order might have reached some of these. Fixing that
            # means real tour optimisation (2-opt), which is deliberately out of scope; the
            # reason code describes what this plan did, not a proof of impossibility.
            for obstacle in remaining:
                unreachable.append(UnreachableObstacle(obstacle.image_id, UnreachableReason.NO_PATH))
                logger.warning(
                    "No path to image_id %s (%s face, %s-%s) from %s: it has %s goal pose(s), "
                    "none reachable. Skipping.",
                    obstacle.image_id,
                    obstacle.direction.value,
                    obstacle.south_west,
                    obstacle.north_east,
                    current,
                    len(remaining[obstacle][1]),
                )
            break

        obstacle, _, path = seg
        segments.append(Segment.compress(world, seg))
        current, _ = path[-1]
        remaining.pop(obstacle)

    return SearchResult(segments, unreachable)


@dataclass
class Segment:
    image_id: int
    cost: int                     # path length in grid cells (== cm at the default 1 cm cell)
    instructions: list[TurnInstruction | MoveInstruction | MiscInstruction]
    vectors: list[Vector]
    moves: list[Turn | Move]      # the segment's parts in driving order; turn arcs de-interleaved
    seconds: float                # estimated driving time of `moves`; excludes the capture dwell

    @classmethod
    def compress(cls, world: World, information: tuple[Obstacle, float, list[tuple[Vector, Turn | Move | None]]]) -> Segment:
        # The search's own cost is discarded: it is denominated in whatever the caller asked the
        # search to minimise, which for a time-weighted search is seconds. Re-costing the moves
        # under DISTANCE_CELLS keeps `cost` one unit whichever weights planned the leg. For a
        # distance-weighted search the two numbers are equal, so greedy planning is unchanged.
        obstacle, _search_cost, parts = information
        instructions: list[TurnInstruction | MoveInstruction | MiscInstruction] = []
        vectors: list[Vector] = []
        moves: list[Turn | Move] = []
        previous = parts[0][0]

        for vector, move in parts:
            match move:
                case Turn():
                    move = Turn(move.turn, _ordered_arc(move.vectors, previous))
                    instructions.append(move.turn)
                    vectors.extend(move.vectors)
                    moves.append(move)

                case Move() if instructions and isinstance(instructions[-1], MoveInstruction) and instructions[-1].move == move.move:
                    instructions[-1].amount += len(move.vectors) * world.cell_size
                    vectors.extend(move.vectors)
                    moves.append(move)

                case Move():
                    instructions.append(MoveInstruction(move=move.move, amount=len(move.vectors) * world.cell_size))
                    vectors.extend(move.vectors)
                    moves.append(move)

            if move is not None:
                previous = vector

        instructions.append(MiscInstruction.CAPTURE_IMAGE)

        # Not named `cost`: that would make the module-level `cost` import a local of this
        # method and turn the two reads above into an UnboundLocalError.
        distance = round(sum(cost.move_cost(m, cost.DISTANCE_CELLS, world.cell_size) for m in moves))

        return cls(obstacle.image_id, distance, instructions, vectors, moves, cost.seconds(moves, world.cell_size))


def _ordered_arc(cells: list[Vector], start: Vector) -> list[Vector]:
    """
    Put a turn's cells in driving order.

    ``turn.__offsets`` fills the arc from both ends at once and appends ``a0, b0, a1, b1, ...`` then
    the end pose, so the list it returns is a collision-check SET, not a path. Split the two
    interleaved halves, join them at the 45-degree point, pick the direction that begins nearest
    ``start`` (the pose before the turn), drop consecutive duplicates, and keep the end pose last.
    """
    *arc, end = cells
    a, b = arc[0::2], arc[1::2]
    forward = a + b[::-1]
    backward = b + a[::-1]

    def gap(v: Vector) -> int:
        return abs(v.x - start.x) + abs(v.y - start.y)

    ordered = forward if gap(forward[0]) <= gap(backward[0]) else backward
    result: list[Vector] = []
    for v in ordered + [end]:
        if not result or (v.x, v.y) != (result[-1].x, result[-1].y):
            result.append(v)
    return result
