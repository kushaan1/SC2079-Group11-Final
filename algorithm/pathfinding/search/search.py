# Derived from Pante/SC2079 (AY2023 S2, Group 14). See algorithm/PROVENANCE.md
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import config
from pathfinding import cost
from pathfinding.report import UnreachableObstacle, UnreachableReason
from pathfinding.search.instructions import (
    MiscInstruction, Move, MoveInstruction, Pivot, PivotInstruction, Turn, TurnInstruction,
)
from pathfinding.search.segment import segment
from pathfinding.search.turn import centre_arc
from pathfinding.world.objective import ObjectiveGeneration
from pathfinding.world.primitives import Point, Vector
from pathfinding.world.world import World, Obstacle

logger = logging.getLogger(__name__)


def split_straight(amount: int, limit: int) -> list[int]:
    """
    Break one straight of ``amount`` cm into commands of at most ``limit`` cm each.

    Divides as evenly as the integers allow rather than taking the limit greedily. Greedy would
    turn 105 into ``100 + 5``, and a 5 cm command is the worst case the STM can be handed: its
    error is nearly all fixed overhead, so the shorter the move the worse it is proportionally.
    ``53 + 52`` covers the same ground at the same cost and drives better.

    :param amount: the distance to drive, in centimetres. Always at least 1.
    :param limit: the longest single command allowed. Anything below 1 means no cap.
    :return: the command amounts in driving order, summing to ``amount``, each at least 1.
    """
    if limit < 1 or amount <= limit:
        return [amount]
    pieces = -(-amount // limit)          # ceil, without importing math for one call
    base, remainder = divmod(amount, pieces)
    return [base + 1] * remainder + [base] * (pieces - remainder)


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
    # A new member of an existing union, exactly as the diagonals' FORWARD_LEFT_45 was: with
    # `config.PIVOT_TURNS` off no PivotInstruction can be produced, so this widens the type
    # without widening what the service actually emits.
    instructions: list[TurnInstruction | PivotInstruction | MoveInstruction | MiscInstruction]
    vectors: list[Vector]
    moves: list[Turn | Pivot | Move]   # the parts in driving order; turn() samples arcs that way
    seconds: float                # estimated driving time of `moves`; excludes the capture dwell
    # The robot's centre pose AFTER each entry of `instructions`, one-to-one, CAPTURE_IMAGE
    # included (it repeats the last). What the RPi reports to the tablet after each command,
    # so it never has to model the motion itself - see PathfindingResponseSegment.poses.
    poses: list[Vector] = field(default_factory=list)
    # The robot's centre through the whole segment in driving order: the start pose, then every
    # entry of `poses` with the centre's arc through each turn (at most
    # config.CENTRE_PATH_SPACING_CM between points) and the centre cells of each pivot in
    # between. This is the line the tablet draws the route from; `vectors` is the collision
    # check's rear-pivot cells and sits `lead` behind the car inside every turn.
    centre_path: list[Point] = field(default_factory=list)

    @classmethod
    def compress(cls, world: World, information: tuple[Obstacle, float, list[tuple[Vector, Turn | Pivot | Move | None]]]) -> Segment:
        # The search's own cost is discarded: it is denominated in whatever the caller asked the
        # search to minimise, which for a time-weighted search is seconds. Re-costing the moves
        # under DISTANCE_CELLS keeps `cost` one unit whichever weights planned the leg. For a
        # distance-weighted search the two numbers are equal, so greedy planning is unchanged.
        obstacle, _search_cost, parts = information
        instructions: list[TurnInstruction | PivotInstruction | MoveInstruction | MiscInstruction] = []
        vectors: list[Vector] = []
        moves: list[Turn | Pivot | Move] = []
        # The pose after each instruction, kept in step with `instructions` through the merge
        # below and the split after it. `parts` pairs every move with the state it reached, and
        # its first entry is the segment's start with no move.
        start = parts[0][0]
        after: list[Vector] = []
        # The move behind each instruction, kept in step with `instructions` exactly as `after`
        # is: appended wherever an instruction is appended, and left alone when a chunk merges
        # into the straight before it, so a merged command keeps its FIRST move as its source.
        # Only a pivot's is ever read - its cells are the centre's own path through the shuffle,
        # which nothing else in this method can reconstruct - so what a merged straight points
        # at does not matter, only that the list stays aligned.
        sources: list[Turn | Pivot | Move] = []
        # Cells accumulated into the MoveInstruction at the end of `instructions`, so a run of
        # merged chunks is converted to centimetres once. Converting each chunk and adding the
        # rounded results would drift by a centimetre per merge on a diagonal.
        run = 0

        def centimetres(direction, cells: int) -> int:
            """What the STM is told to drive. A diagonal cell is sqrt(2) cm of ground, so a
            25-cell diagonal run is a 35 cm command, not a 25 cm one."""
            return round(cost.straight_cells(direction, cells) * world.cell_size)

        for vector, move in parts:
            match move:
                case Turn():
                    instructions.append(move.turn)
                    after.append(vector)
                    sources.append(move)
                    vectors.extend(move.vectors)
                    moves.append(move)

                # Beside the turn rather than beside the straight, and never merged into
                # anything: a pivot ends whatever run of chunks it interrupts, because the car
                # stops, shuffles round and sets off again on a different heading. It ends that
                # run by being appended to `instructions` - the merge guard below asks what the
                # last instruction is, finds a pivot rather than a MoveInstruction, and the
                # straight after the pivot therefore opens a new command with a fresh `run`.
                case Pivot():
                    instructions.append(move.pivot)
                    after.append(vector)
                    sources.append(move)
                    vectors.extend(move.vectors)
                    moves.append(move)

                case Move() if instructions and isinstance(instructions[-1], MoveInstruction) and instructions[-1].move == move.move:
                    run += len(move.vectors)
                    instructions[-1].amount = centimetres(move.vectors[0].direction, run)
                    after[-1] = vector
                    vectors.extend(move.vectors)
                    moves.append(move)

                case Move():
                    run = len(move.vectors)
                    instructions.append(MoveInstruction(move=move.move,
                                                        amount=centimetres(move.vectors[0].direction, run)))
                    after.append(vector)
                    sources.append(move)
                    vectors.extend(move.vectors)
                    moves.append(move)


        # Applied here rather than inside the merge above, so that the merge keeps converting a
        # whole run of chunks to centimetres exactly once and the cm-rounding it guards against
        # stays guarded against. The cap reads config on every call, like TurnInstruction.radius:
        # it is the STM owner's number and nothing may freeze it at import.
        limit = config.MAX_STRAIGHT_CM
        cell_size = world.cell_size
        split: list[TurnInstruction | PivotInstruction | MoveInstruction | MiscInstruction] = []
        poses: list[Vector] = []
        # Built in the same pass as `poses`, and from the same `reached` values, so that every
        # pose is literally a point of the path by construction rather than by a tolerance: the
        # RPi's "the car is on the route" check is then a lookup. Integers, like every other
        # coordinate on the wire. Straights contribute only their ends and their split pieces'
        # ends - the line between two points of a straight IS the straight - while turns and
        # pivots contribute their curve, because a chord across an arc is not where the car went.
        centre_path: list[Point] = [Point(start.x, start.y)]

        def visit(point: Point) -> None:
            """Append a centre point, dropping an exact repeat of the last one."""
            if centre_path[-1] != point:
                centre_path.append(point)

        previous = start
        # strict: the three lists grow in lockstep above; a mismatch must raise, not drop instructions.
        for instruction, reached, source in zip(instructions, after, sources, strict=True):
            if isinstance(instruction, MoveInstruction):
                pieces = split_straight(instruction.amount, limit)
                # The pieces' poses interpolate the straight from where it began to where it
                # ended, by the share of the distance each piece has covered. Exact for a
                # cardinal heading (a cm is a cell); rounded on a diagonal, where the last
                # piece is pinned to the real end so no rounding can survive it.
                covered = 0
                for index, amount in enumerate(pieces):
                    covered += amount
                    if index == len(pieces) - 1:
                        pose = reached
                    else:
                        share = covered / instruction.amount
                        pose = Vector(reached.direction,
                                      round(previous.x + (reached.x - previous.x) * share),
                                      round(previous.y + (reached.y - previous.y) * share))
                    split.append(MoveInstruction(move=instruction.move, amount=amount))
                    poses.append(pose)
                    visit(Point(pose.x, pose.y))
            else:
                if isinstance(instruction, TurnInstruction):
                    # The centre's own arc, sampled finely; its last point IS the end pose the
                    # search recorded, up to the rounding both sides apply, so the exact
                    # `reached` is appended after it and the rounded duplicate dropped.
                    # `previous` is where this turn began: the pose after the instruction
                    # before it, or the segment's start.
                    for x, y in centre_arc(previous, instruction, cell_size)[:-1]:
                        visit(Point(round(x), round(y)))
                elif isinstance(instruction, PivotInstruction):
                    # A pivot's cells are already the CENTRE's path through the shuffle (see
                    # pivot._Shuffle.cells), about a cell apart, so they go in as they are.
                    # The last of them is the end pose, which `reached` supplies below.
                    # A pivot is never merged, so its instruction's source is its own Pivot move.
                    assert isinstance(source, Pivot), source
                    for vector in source.vectors[:-1]:
                        visit(Point(vector.x, vector.y))
                split.append(instruction)
                poses.append(reached)
                visit(Point(reached.x, reached.y))
            previous = reached
        instructions = split

        instructions.append(MiscInstruction.CAPTURE_IMAGE)
        poses.append(previous)

        # Not named `cost`: that would make the module-level `cost` import a local of this
        # method and turn the two reads above into an UnboundLocalError.
        distance = round(sum(cost.move_cost(m, cost.DISTANCE_CELLS, world.cell_size) for m in moves))

        return cls(obstacle.image_id, distance, instructions, vectors, moves, cost.seconds(moves, world.cell_size), poses,
                   centre_path)
