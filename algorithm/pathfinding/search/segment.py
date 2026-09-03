# Derived from Pante/SC2079 (AY2023 S2, Group 14). See algorithm/PROVENANCE.md
"""
Dijkstra over robot poses, on integer state indices.

A state is a pose ``(direction, x, y)`` and the search is a plain uniform-cost Dijkstra. No
heuristic: :func:`segment` searches against many goal poses at once and :func:`reach` has no
single goal at all, and the reference's Euclidean estimate cost more than it saved.

The representation is what this module is about. A pose is one int::

    index = (rank * stride + x + pad) * stride + y + pad

with ``rank`` EAST 0, NORTH 1, SOUTH 2, WEST 3 - the order :class:`~pathfinding.world.
primitives.Vector`'s dataclass ordering puts poses in, ``Direction`` being a ``str`` enum. So
``(cost, index)`` heap entries break ties EXACTLY as the ``(cost, Vector)`` entries they
replaced, and this is a speed change only: same paths, same costs, same tie-breaks, pinned by
``tests/test_segment_fast.py`` against a dump of the previous implementation.

``pad`` is there because a turn's END pose is not collision-checked and may land outside the
arena, up to the robot's half-extent beyond the arc that was checked. The reference put such
poses in its dicts and expanded them like any other; padding the index space keeps them
distinct states instead of wrapping them onto real ones.

Expansion is then table-driven. A turn's arc is the same set of offsets wherever it starts
(see :func:`~pathfinding.search.turn.turn`), so its legality is "these ~50 cells are free",
and a straight chunk's is "these 5 are". Both are precomputed once per search into one byte
per cell per (direction, move), alongside the constant the index changes by and what the move
costs. An expansion is then six byte lookups and at most six additions, and no ``Vector``,
``Turn`` or ``Move`` object is built until a path is traced.
"""
from __future__ import annotations

from heapq import heappop, heappush
from itertools import chain
from math import inf
from typing import Iterable, Iterator

import numpy as np

import config
from pathfinding import cost
from pathfinding.search.instructions import Move, Straight, Turn, TurnInstruction
from pathfinding.search.straight import straight
from pathfinding.search.turn import turn
from pathfinding.world.primitives import Direction, Vector
from pathfinding.world.world import Obstacle, World

# Sorted, not written out, because this must agree with how `Vector` orders poses and that is
# str comparison on a str enum - EAST, NORTH, SOUTH, WEST. Deriving it means a renamed
# direction cannot silently desynchronise the heap's tie-breaking from the reference's.
_RANKS: tuple[Direction, ...] = tuple(sorted(Direction))
_RANK: dict[Direction, int] = {direction: rank for rank, direction in enumerate(_RANKS)}

# One cell forward, per direction. Mirrors straight(), which is the only other place a
# straight move's shape is written down.
# Derived from straight() itself, so the two cannot drift apart.
_STEP: dict[Direction, tuple[int, int]] = {
    d: ((v := straight(Vector(d, 0, 0), 1, 1)[0]).x, v.y) for d in Direction
}

# Move codes stored per state, so a traced path can rebuild the move that reached it. 0 is
# reserved for "arrived by nothing", i.e. a seed.
_TURNS: tuple[TurnInstruction, ...] = tuple(TurnInstruction)


def segment(
    world: World,
    initial: Vector | Iterable[Vector],
    objectives: dict[Obstacle, tuple[Vector, set[Vector]]],
    weights: cost.Weights = cost.DISTANCE_CELLS,
) -> None | tuple[Obstacle, float, list[tuple[Vector, Turn | Move | None]]]:
    """
    Finds the shortest path of a segment of the overall path.

    Dijkstra from ``initial`` over poses, stopping at the first pose popped that belongs to
    any objective's goal-pose set. Poses that share x & y but face differently are different
    states, and the moves between them are the four quarter-turns plus forward and backward
    straight chunks of ``config.STRAIGHT_CHUNK_CELLS`` cells.

    When one popped pose belongs to several objectives the first in ``objectives``' order
    wins, which is the order goal poses were generated in.

    :param world: The world.
    :param initial: The initial vector, or an iterable of them. Always the south-west corner of the
        robot. Several sources are seeded at cost 0 together, so one search answers "cheapest from
        anywhere in this set" rather than needing one search per source.
    :param objectives: The possible objective vectors. Always the south-west corner of objectives.
    :param weights: What a move costs. The default reproduces the original grid-cell objective;
        :data:`~pathfinding.cost.TIME_SECONDS` minimises estimated driving time instead.
    :return:
        The obstacle reached, None if the frontier was exhausted without reaching any.
        The cost of the segment, in the unit ``weights`` counts in.
        The vectors and corresponding instructions from the initial vector to the objective vector. Vectors that form
        a curve when turning are embedded inside the instruction
    """
    sources = [initial] if isinstance(initial, Vector) else list(initial)
    poses = [pose for _, goal in objectives.values() for pose in goal]
    search = _Search(world, weights, sources, poses)

    goals: dict[int, Obstacle] = {}
    for obstacle, (_, goal) in objectives.items():
        for pose in goal:
            goals.setdefault(search.index(pose), obstacle)

    for index in search.run():
        obstacle = goals.get(index)
        if obstacle is not None:
            return obstacle, search.costs[index], search.trace(world, index)

    return None


def reach(
    world: World,
    sources: Vector | Iterable[Vector],
    targets: dict[Obstacle, set[Vector] | tuple[Vector, set[Vector]]],
    weights: cost.Weights = cost.DISTANCE_CELLS,
) -> dict[Obstacle, float]:
    """
    Finds the cheapest cost from anywhere in ``sources`` into every target's goal-pose set.

    One multi-source, all-targets Dijkstra where :func:`segment` is a multi-source,
    first-target one: it does not stop at the first goal, so N obstacles cost ONE search
    instead of N. That is what makes a leg-cost matrix over pose sets affordable
    (:mod:`~pathfinding.search.tour` needs N+1 of these, not N*(N+1)).

    The cost recorded for an obstacle is the cost of the state at which it was first popped.
    No move costs less than zero, so that pop is the obstacle's optimal cost by the usual
    Dijkstra argument - the same value :func:`segment` would return for that obstacle alone.
    A popped goal state is still expanded: a pose set is a waypoint, not a wall.

    :param world: The world.
    :param sources: The starting vector, or an iterable of them, all seeded at cost 0.
    :param targets: The obstacles to measure, each mapped either to its goal-pose set or to
        the ``(representative, poses)`` pair
        :class:`~pathfinding.world.objective.ObjectiveGeneration` stores, so either shape can
        be passed straight through.
    :param weights: What a move costs. See :func:`segment`.
    :return: The cost into each obstacle's pose set, in the unit ``weights`` counts in. Only
        obstacles actually reached appear - a missing key means the frontier was exhausted
        without touching one of its poses, i.e. NO_PATH from these sources.
    """
    starts = [sources] if isinstance(sources, Vector) else list(sources)
    goals = {obstacle: (poses[1] if isinstance(poses, tuple) else poses)
             for obstacle, poses in targets.items()}
    search = _Search(world, weights, starts, chain.from_iterable(goals.values()))

    # One dict lookup per pop instead of one set membership test per target per pop. At 200x200x4
    # states the difference is the whole cost of the target check.
    owners: dict[int, list[Obstacle]] = {}
    for obstacle, poses in goals.items():
        for pose in poses:
            owners.setdefault(search.index(pose), []).append(obstacle)

    reached: dict[Obstacle, float] = {}
    costs = search.costs

    # Stop as soon as every target is priced; only an unreachable target exhausts the frontier.
    for index in search.run():
        for obstacle in owners.get(index, ()):
            if obstacle not in reached:
                reached[obstacle] = costs[index]

        if len(reached) >= len(goals):
            break

    return reached


class _FreeWorld:
    """
    A stand-in world that refuses nothing, used to read a turn's shape.

    :func:`~pathfinding.search.turn.turn` builds an arc from ``(direction, instruction,
    radius, pivot offset, robot extents)`` and translates it to the start pose, so the path it
    returns from the origin of a world with nothing in it IS that arc as offsets. This is the
    only thing this class is for; every legality question is asked of the real world's grid.
    """

    def __init__(self, world: World):
        self.robot = world.robot
        # An attribute here, a property on World. turn() only reads it.
        self.cell_size = world.cell_size

    def contains_all(self, xs, ys, box, x: int = 0, y: int = 0) -> bool:
        return True


class _Search:
    """
    One Dijkstra: the index space, the move tables, and the frontier over them.

    Held as parallel Python lists rather than numpy arrays because every access is a scalar
    one - a list returns the float it stores, where a numpy array boxes a fresh ``np.float64``
    that is both slower and a different type on the way out.
    """

    def __init__(
        self,
        world: World,
        weights: cost.Weights,
        sources: list[Vector],
        poses: Iterable[Vector],
    ):
        """
        :param world: The world.
        :param weights: What a move costs.
        :param sources: The poses to seed at cost 0.
        :param poses: Every other pose the caller will pass to :meth:`index` - the goals. They
            size the index space along with the sources, so no caller's pose falls outside it.
        """
        self.pad, self.stride, self.tables, self.chunks = _tables(world, weights, chain(sources, poses))
        self.cells = self.stride * self.stride
        states = 4 * self.cells

        self.costs: list[float] = [inf] * states
        self.parents: list[int] = [-1] * states
        self.codes = bytearray(states)
        self.settled = bytearray(states)
        self.frontier: list[tuple[float, int]] = []

        for source in sources:
            index = self.index(source)
            heappush(self.frontier, (0.0, index))
            self.costs[index] = 0.0

    def index(self, vector: Vector) -> int:
        return (_RANK[vector.direction] * self.stride + vector.x + self.pad) * self.stride + vector.y + self.pad

    def vector(self, index: int) -> Vector:
        rank, cell = divmod(index, self.cells)
        x, y = divmod(cell, self.stride)
        return Vector(_RANKS[rank], x - self.pad, y - self.pad)

    def run(self) -> Iterator[int]:
        """
        Pops states cheapest-first, yielding each BEFORE expanding it.

        Yielding first is what lets a caller answer its goal question at exactly the moment
        the reference did, and stop the search by leaving the loop.

        Lazy deletion: an improved cost is pushed as a new entry rather than decreasing the
        old one, so a state may be popped once per improvement. ``costs`` already holds the
        best known by the time the first of those entries is popped - no move costs less than
        zero, so that pop is final - which makes every later pop a re-expansion with identical
        numbers. ``settled`` skips those; :func:`reach` settles most of a 200x200x4 grid, so
        that is a constant factor, not a nicety.
        """
        costs = self.costs
        parents = self.parents
        codes = self.codes
        settled = self.settled
        frontier = self.frontier
        tables = self.tables
        cells = self.cells

        while frontier:
            index = heappop(frontier)[1]
            yield index

            if settled[index]:
                continue
            settled[index] = 1

            current = costs[index]
            rank, cell = divmod(index, cells)
            for legal, delta, price, code in tables[rank]:
                if legal[cell]:
                    following = index + delta
                    value = current + price
                    if value < costs[following]:
                        costs[following] = value
                        parents[following] = index
                        codes[following] = code
                        heappush(frontier, (value, following))

    def trace(self, world: World, index: int) -> list[tuple[Vector, Turn | Move | None]]:
        """The path to a state, as the poses along it and the move that reached each."""
        path: list[tuple[Vector, Turn | Move | None]] = []

        while index != -1:
            previous = self.parents[index]
            move = None if previous == -1 else self.__move(world, self.vector(previous), self.codes[index])
            path.append((self.vector(index), move))
            index = previous

        path.reverse()
        return path

    def __move(self, world: World, start: Vector, code: int) -> Turn | Move:
        """
        Rebuilds one move from the code stored against the state it reached.

        Both primitives are pure functions of the pose they start from, so recomputing the
        handful on a traced path is cheaper than keeping an object per improved state - which
        is the allocation this rewrite exists to remove.
        """
        if code <= len(_TURNS):
            instruction = _TURNS[code - 1]
            vectors = turn(world, start, instruction)
            assert vectors is not None, f"traced an illegal {instruction} from {start}"
            return Turn(instruction, vectors)

        move, length = self.chunks[code - len(_TURNS) - 1]
        modifier = 1 if move == Straight.FORWARD else -1
        return Move(move, straight(start, modifier, length))


def _tables(
    world: World,
    weights: cost.Weights,
    poses: Iterable[Vector],
) -> tuple[int, int, tuple[tuple[tuple[bytes, int, float, int], ...], ...], list[tuple[Straight, int]]]:
    """
    Everything :meth:`_Search.run` reads, built once per search.

    Per direction, the moves in the reference's order - the four turns in
    :class:`~pathfinding.search.instructions.TurnInstruction` order, then FORWARD and BACKWARD
    for each chunk length - each as ``(legality byte per cell, index delta, cost, move code)``.
    Order matters: two moves may reach one state at the same cost, and the first one recorded
    keeps it.

    :param world: The world.
    :param weights: What a move costs.
    :param poses: Every pose the caller will index, so the padding can cover them.
    :return: The padding, the index stride, the per-direction move tables, and the straight
        chunks in code order.
    """
    # Call-time config rule: read here so the chunk set can be re-tuned at runtime.
    chunks = [(move, length) for move in Straight for length in config.STRAIGHT_CHUNK_CELLS]
    cell_size = world.cell_size
    size = world.size

    free = _FreeWorld(world)
    arcs: dict[tuple[Direction, TurnInstruction], tuple[list[tuple[int, int]], tuple[int, int], Direction]] = {}
    for direction in _RANKS:
        for instruction in _TURNS:
            path = turn(free, Vector(direction, 0, 0), instruction)
            if path is not None:
                arcs[direction, instruction] = ([(v.x, v.y) for v in path[:-1]],
                                                (path[-1].x, path[-1].y), path[-1].direction)

    # `pad`: how far outside the arena a turn's end pose can sit. The arc is what gets
    # collision-checked, so a legal turn puts every arc cell in the arena and the end pose
    # wherever the geometry says - which is the robot's half-extent off the arc's own box.
    # `span`: how far from a state a mask has to read, which sizes the padded grid below.
    pad = 0
    span = max(length for _, length in chunks)
    for offsets, (end_x, end_y), _ in arcs.values():
        xs = [x for x, _ in offsets]
        ys = [y for _, y in offsets]
        pad = max(pad, min(xs) - end_x, end_x - max(xs), min(ys) - end_y, end_y - max(ys))
        span = max(span, max(map(abs, xs)), max(map(abs, ys)))

    for pose in poses:
        pad = max(pad, -pose.x, pose.x - size + 1, -pose.y, pose.y - size + 1)

    stride = size + 2 * pad
    cells = stride * stride

    # The arena's free cells inside a border of blocked ones, so that "outside the arena" and
    # "occupied" answer alike and no shifted read needs a bounds test. `span` cells of it are
    # margin for the reads themselves, `pad` cells are index space a state may legally occupy.
    edge = span + pad
    free_cells = np.zeros((stride + 2 * span, stride + 2 * span), dtype=bool)
    free_cells[edge:edge + size, edge:edge + size] = world.grid

    def legality(offsets: Iterable[tuple[int, int]]) -> bytes:
        """One byte per cell: may a move whose shape is ``offsets`` start there?"""
        legal = np.ones((stride, stride), dtype=bool)
        for x, y in dict.fromkeys(offsets):
            legal &= free_cells[span + x:span + x + stride, span + y:span + y + stride]
        return legal.tobytes()

    tables = []
    for rank, direction in enumerate(_RANKS):
        moves: list[tuple[bytes, int, float, int]] = []

        for code, instruction in enumerate(_TURNS, start=1):
            arc = arcs.get((direction, instruction))
            if arc is None:
                continue
            offsets, (end_x, end_y), facing = arc
            delta = (_RANK[facing] - rank) * cells + end_x * stride + end_y
            moves.append((legality(offsets), delta, weights.turn(instruction, cell_size), code))

        step_x, step_y = _STEP[direction]
        for code, (move, length) in enumerate(chunks, start=len(_TURNS) + 1):
            modifier = 1 if move == Straight.FORWARD else -1
            offsets = [(step_x * modifier * i, step_y * modifier * i) for i in range(1, length + 1)]
            delta = modifier * length * (step_x * stride + step_y)
            moves.append((legality(offsets), delta, weights.straight(length, cell_size), code))

        tables.append(tuple(moves))

    return pad, stride, tuple(tables), chunks
