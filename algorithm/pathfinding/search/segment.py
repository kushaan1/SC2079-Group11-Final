# Derived from Pante/SC2079 (AY2023 S2, Group 14). See algorithm/PROVENANCE.md
"""
Dijkstra over robot poses, on integer state indices.

A state is a pose ``(direction, x, y)`` and the search is a plain uniform-cost Dijkstra. No
heuristic: :func:`segment` searches against many goal poses at once and :func:`reach` has no
single goal at all, and the reference's Euclidean estimate cost more than it saved.

The representation is what this module is about. A pose is one int::

    index = (rank * stride + x + pad) * stride + y + pad

with ``rank`` the position of the heading in ``sorted(Direction)`` - the order :class:`~path
finding.world.primitives.Vector`'s dataclass ordering puts poses in, ``Direction`` being a
``str`` enum. So
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

A pivot (:func:`~pathfinding.search.pivot.pivot`) is the third kind of move and is tabulated
the same way, with one difference that is the whole of its correctness: its mask is read from
an ERODED copy of the grid rather than from the grid itself, because the grid marks where an
axis-aligned robot may stand and a rotating one needs its circumscribed radius. See
:func:`_tables`. Pivot move codes are APPENDED after the straight chunks, so every code a
turn or a straight already had keeps its value and, with the codes, its place in the
tie-break the table's order decides.
"""
from __future__ import annotations

from heapq import heappop, heappush
from itertools import chain
from math import ceil, inf, sqrt
from typing import Iterable, Iterator

import numpy as np

import config
from pathfinding import cost
from pathfinding.search.instructions import (
    Move, Pivot, PivotInstruction, Straight, Turn, TurnInstruction,
)
from pathfinding.search.pivot import pivot
from pathfinding.search.straight import straight
from pathfinding.search.turn import turn
from pathfinding.world.primitives import Direction, Vector
from pathfinding.world.world import Obstacle, World

# Sorted, not written out, because this must agree with how `Vector` orders poses and that is
# str comparison on a str enum - EAST, NORTH, SOUTH, WEST. Deriving it means a renamed
# direction cannot silently desynchronise the heap's tie-breaking from the reference's.
_RANKS: tuple[Direction, ...] = tuple(sorted(Direction))
_CARDINAL_RANKS: tuple[Direction, ...] = tuple(d for d in _RANKS if not d.diagonal)


def _ranks() -> tuple[Direction, ...]:
    """
    The headings a search may occupy, in the order that ranks them.

    Call-time config rule: only a 45 degree turn enters a diagonal heading, so with the
    diagonals off the four diagonal ranks are unreachable - and carrying them doubles the index
    space, the four parallel state arrays over it, and the per-rank move tables, all to hold
    states nothing can ever reach. Dropping them is what keeps the four-heading planner as fast
    as it was before the diagonals existed.

    The relative order of the cardinals is the same in both sets, and an index is monotone in
    (rank, x, y), so every tie the frontier breaks between two cardinal states breaks the same
    way either way. That is what makes this a speed change and not a behaviour change.
    """
    return _RANKS if config.DIAGONAL_HEADINGS else _CARDINAL_RANKS

# One cell forward, per direction. Mirrors straight(), which is the only other place a
# straight move's shape is written down.
# Derived from straight() itself, so the two cannot drift apart.
_STEP: dict[Direction, tuple[int, int]] = {
    d: ((v := straight(Vector(d, 0, 0), 1, 1)[0]).x, v.y) for d in Direction
}

# Move codes stored per state, so a traced path can rebuild the move that reached it. 0 is
# reserved for "arrived by nothing", i.e. a seed.
_TURNS: tuple[TurnInstruction, ...] = tuple(TurnInstruction)

# The pivot codes, APPENDED after the turns and the straight chunks, so that every existing
# code keeps its value. This is the full enum and never a filtered subset: a code is a position
# in this tuple, and :func:`_tables` skips the pivots it cannot offer rather than compacting
# them, exactly as it skips a turn whose arc came back None. Filtering instead would renumber
# the survivors - with the diagonals off the offered pivots are the two 90s, which are this
# tuple's LAST two entries and not a prefix of it, so a filtered tuple would decode a traced
# 90 as a 45.
_PIVOTS: tuple[PivotInstruction, ...] = tuple(PivotInstruction)


def segment(
    world: World,
    initial: Vector | Iterable[Vector],
    objectives: dict[Obstacle, tuple[Vector, set[Vector]]],
    weights: cost.Weights = cost.DISTANCE_CELLS,
) -> None | tuple[Obstacle, float, list[tuple[Vector, Turn | Pivot | Move | None]]]:
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
        self.ranks = _ranks()
        self.rank = {direction: rank for rank, direction in enumerate(self.ranks)}
        self.pad, self.stride, self.tables, self.chunks = _tables(world, weights, chain(sources, poses), self.ranks)
        self.cells = self.stride * self.stride
        states = len(self.ranks) * self.cells

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
        return (self.rank[vector.direction] * self.stride + vector.x + self.pad) * self.stride + vector.y + self.pad

    def vector(self, index: int) -> Vector:
        rank, cell = divmod(index, self.cells)
        x, y = divmod(cell, self.stride)
        return Vector(self.ranks[rank], x - self.pad, y - self.pad)

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

    def trace(self, world: World, index: int) -> list[tuple[Vector, Turn | Pivot | Move | None]]:
        """The path to a state, as the poses along it and the move that reached each."""
        path: list[tuple[Vector, Turn | Pivot | Move | None]] = []

        while index != -1:
            previous = self.parents[index]
            move = None if previous == -1 else self.__move(world, self.vector(previous), self.codes[index])
            path.append((self.vector(index), move))
            index = previous

        path.reverse()
        return path

    def __move(self, world: World, start: Vector, code: int) -> Turn | Pivot | Move:
        """
        Rebuilds one move from the code stored against the state it reached.

        All three primitives are pure functions of the pose they start from, so recomputing the
        handful on a traced path is cheaper than keeping an object per improved state - which
        is the allocation this rewrite exists to remove.

        The three ranges of the code space, in the order :func:`_tables` lays them out: a turn,
        then a straight chunk, then a pivot. The straight boundary is ``len(self.chunks)``
        rather than a constant because the chunk lengths are config read at search time.

        ``pivot()`` is re-run against the world's ORDINARY grid here, not against the eroded
        copy the table's mask was built from. That is sound in the one direction it needs to
        be: erosion only ever clears cells, so a pivot the table offered is legal under the
        grid as well, and the assertion below holds for the same reason the turn's does.
        """
        if code <= len(_TURNS):
            instruction = _TURNS[code - 1]
            vectors = turn(world, start, instruction)
            assert vectors is not None, f"traced an illegal {instruction} from {start}"
            return Turn(instruction, vectors)

        straights = len(self.chunks)
        if code <= len(_TURNS) + straights:
            move, length = self.chunks[code - len(_TURNS) - 1]
            modifier = 1 if move == Straight.FORWARD else -1
            return Move(move, straight(start, modifier, length))

        shuffle = _PIVOTS[code - len(_TURNS) - straights - 1]
        vectors = pivot(world, start, shuffle)
        assert vectors is not None, f"traced an illegal {shuffle} from {start}"
        return Pivot(shuffle, vectors)


def _eroded(free_cells: np.ndarray, radius: int) -> np.ndarray:
    """
    ``free_cells`` with every cell within ``radius`` of a blocked one blocked as well.

    The rotation clearance model. ``World.grid`` marks where the robot's CENTRE may sit,
    inflating each obstacle by the robot's half-extent - an L-INFINITY box. That is the right
    condition for an axis-aligned square sliding along its heading, and the wrong one for a
    square that is rotating: a rotating 31 cm robot sweeps a circle of radius
    ``half_extent * sqrt(2)``, about 21 cells against the 15 the grid was grown by.

    What a rotating robot needs is the obstacle box grown to that circumscribed radius with
    ROUNDED corners - the Minkowski sum with a disc, because the corner of the sweep is a
    circle's corner and not a square's. Eroding the already-inflated grid by an L2 disc of
    radius ``ceil(half_extent * (sqrt(2) - 1))`` produces exactly that, which is why the model
    is this one operation and not a second inflation pass over the obstacles.

    Eroding the GRID once is also the affordable way round. The equivalent statement - dilate
    each pivot's ~30-cell centre path by the disc and check the result - is the same condition
    and about 900 shifted reads per mask per direction; this is ~150 shifted reads once per
    search, and then the pivot masks are the ordinary ~30 ANDs against the result.

    Reads off the edge of ``free_cells`` answer "blocked", so a caller that wants a region
    treated as clear must hand over a grid in which it IS clear - see :func:`_tables`, which
    passes a grid holding only the obstacles and intersects the result back afterwards.

    :param free_cells: The padded free-cell grid. Never modified.
    :param radius: The disc's radius in cells.
    :return: A new array of the same shape - except at ``radius <= 0``, where there is nothing
        to erode and the caller's own array is handed straight back.
    """
    if radius <= 0:
        return free_cells

    height, width = free_cells.shape
    # A shifted read off the edge must answer "blocked". Slicing into a copy that is already
    # `radius` cells of False wider on every side is what guarantees that: numpy would read a
    # negative index as an offset from the far edge, which is the same wrap-around
    # `World.contains_all` bounds-tests against, and it would make the arena's own boundary
    # band erode against the opposite wall.
    padded = np.zeros((height + 2 * radius, width + 2 * radius), dtype=bool)
    padded[radius:radius + height, radius:radius + width] = free_cells

    eroded = np.ones_like(free_cells)
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            if dx * dx + dy * dy <= radius * radius:
                eroded &= padded[radius + dx:radius + dx + height,
                                 radius + dy:radius + dy + width]
    return eroded


def _tables(
    world: World,
    weights: cost.Weights,
    poses: Iterable[Vector],
    ranks: tuple[Direction, ...],
) -> tuple[int, int, tuple[tuple[tuple[bytes, int, float, int], ...], ...], list[tuple[Straight, int]]]:
    """
    Everything :meth:`_Search.run` reads, built once per search.

    Per direction, the moves in the reference's order - the four turns in
    :class:`~pathfinding.search.instructions.TurnInstruction` order, then FORWARD and BACKWARD
    for each chunk length - each as ``(legality byte per cell, index delta, cost, move code)``.
    Order matters: two moves may reach one state at the same cost, and the first one recorded
    keeps it.

    The pivots come LAST, after the straight chunks, when ``config.PIVOT_TURNS`` is on. That
    placement is the additive guarantee: every code above keeps its value and its position, so
    the rule in the paragraph above resolves every pre-existing tie exactly as it did. Their
    legality is read from an eroded copy of the grid (:func:`_eroded`) rather than from the
    grid, and only pivots whose END HEADING is one of ``ranks`` are offered - which is what
    makes the 45 degree pivots appear exactly when ``config.DIAGONAL_HEADINGS`` does, with no
    second flag to keep in step.

    :param world: The world.
    :param weights: What a move costs.
    :param poses: Every pose the caller will index, so the padding can cover them.
    :param ranks: The headings in play, in rank order - see :func:`_ranks`.
    :return: The padding, the index stride, the per-direction move tables, and the straight
        chunks in code order.
    """
    # Call-time config rule: read here so the chunk set can be re-tuned at runtime.
    # Call-time config rule: the diagonal headings are only reachable through a 45 degree
    # turn, so dropping those turns is enough to leave the four-heading planner behind.
    turns = _TURNS if config.DIAGONAL_HEADINGS else tuple(t for t in _TURNS if t.degrees == 90)
    chunks = [(move, length) for move in Straight for length in config.STRAIGHT_CHUNK_CELLS]
    # Call-time config rule: with the flag off this is empty and every loop below that reads it
    # does nothing, so the tables are the tables as they were - same moves, same codes, same
    # order, and therefore the same tie-breaks. That is the additive guarantee, and it is
    # structural here rather than a property of the numbers that happen to come out.
    pivots = _PIVOTS if config.PIVOT_TURNS else ()
    cell_size = world.cell_size
    size = world.size

    free = _FreeWorld(world)
    arcs: dict[tuple[Direction, TurnInstruction], tuple[list[tuple[int, int]], tuple[int, int], Direction]] = {}
    rank_of = {direction: rank for rank, direction in enumerate(ranks)}
    for direction in ranks:
        for instruction in turns:
            path = turn(free, Vector(direction, 0, 0), instruction)
            if path is not None:
                arcs[direction, instruction] = ([(v.x, v.y) for v in path[:-1]],
                                                (path[-1].x, path[-1].y), path[-1].direction)

    # The pivots, in the same shape, read off the same free world. Two differences from the
    # arcs above, and both are load-bearing:
    #
    # * the END CELL stays in the checked offsets. A turn's end pose is deliberately not
    #   collision-checked, which is what `pad` below exists for; a pivot's is the cell the car
    #   comes to rest on, and it is checked here for the same reason `pivot()` checks it - it
    #   is a cell the robot occupies, so it is a cell the manoeuvre has to fit through.
    # * the START cell is ADDED. `pivot()`'s sampling loop begins at step 1, so the path it
    #   returns never includes the cell the manoeuvre starts from - and that is the cell the car
    #   is standing on when it begins to rotate. Without this the one cell a pivot is guaranteed
    #   to occupy would be the one cell no pivot mask ever looked at.
    #
    # Neither end actually needs the full disc: a square of half-extent h rotated by phi has an
    # axis half-extent of h*(|cos phi| + |sin phi|), so the EXTRA room a rotation wants runs
    # 0 at 0 degrees, 6.21 cells at 45, and back to 0 at 90 - and both ends of a pivot sit on a
    # `Direction`, square to their own heading. `clearance` is a uniform upper bound over the
    # whole path rather than a per-cell figure, and these two cells are simply where the bound
    # is loosest. Holding them to it costs 12 legal start cells out of 2052 on
    # `04-five-obstacles`, against having two cells the model does not describe.
    #
    # A pivot whose end heading is not a rank is dropped here rather than in the table loop, so
    # that it also contributes nothing to `pad`/`span`: it is a move this search cannot make.
    shuffles: dict[tuple[Direction, PivotInstruction],
                   tuple[list[tuple[int, int]], tuple[int, int], Direction]] = {}
    for direction in ranks:
        for instruction in pivots:
            path = pivot(free, Vector(direction, 0, 0), instruction)
            if path is None or path[-1].direction not in rank_of:
                continue
            shuffles[direction, instruction] = ([(0, 0)] + [(v.x, v.y) for v in path],
                                                (path[-1].x, path[-1].y), path[-1].direction)

    # `pad`: how far outside the arena a turn's end pose can sit. The arc is what gets
    # collision-checked, so a legal turn puts every arc cell in the arena and the end pose
    # wherever the geometry says - which is the robot's half-extent off the arc's own box.
    # `span`: how far from a state a mask has to read, which sizes the padded grid below.
    #
    # The pivots go through the same fold, and today they contribute nothing to `pad`: a pivot
    # checks its own end cell, so its end pose is inside the arena whenever the pivot was legal
    # and can never sit outside the index space. That is a fact about `pivot()`'s sampling loop
    # - the end offset and the last emitted cell are the same rounded centre - and not about
    # what a pivot IS. The fold is kept rather than replaced by that observation, because the
    # day the loop stops emitting centre cells is the day a silently unpadded state starts
    # wrapping onto a real one, and nothing here would say so.
    pad = 0
    span = max(length for _, length in chunks)
    for offsets, (end_x, end_y), _ in chain(arcs.values(), shuffles.values()):
        xs = [x for x, _ in offsets]
        ys = [y for _, y in offsets]
        pad = max(pad, min(xs) - end_x, end_x - max(xs), min(ys) - end_y, end_y - max(ys))
        span = max(span, max(map(abs, xs)), max(map(abs, ys)))

    # The rotation clearance: the spec's `delta`, and the whole of what separates a pivot's
    # legality from a straight's. Called `clearance` here only because `delta` is already this
    # function's name for the constant a move changes the state index by.
    #
    # `span` is how far outside the arena the grid below carries its band of blocked cells, and
    # the erosion reads that far out too, so it has to be at least as wide as the disc. It
    # always is - the smallest `span` a quarter turn's arc produces is tens of cells against
    # this seven - but the two numbers are independent, and an arena whose only moves were short
    # straight chunks would silently erode against the edge of the array instead of against the
    # arena's boundary.
    clearance = ceil(world.robot.north_length * (sqrt(2) - 1)) if shuffles else 0
    span = max(span, clearance)

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

    # ONE eroded copy per search, and only when there is a pivot to check against it. Turns
    # and straights keep reading `free_cells` untouched, which is both correct - they do not
    # rotate - and the reason switching pivots on cannot narrow an existing move.
    #
    # What is eroded is the OBSTACLES, not the arena's edge. The edge is a line on the floor:
    # `config.BOUNDARY_CLEARANCE_ADJUST_CM` is negative on purpose, because clipping a virtual
    # boundary costs nothing, so the keep-out band is already a centimetre SOFTER than the
    # robot's half-extent. Eroding that band by the rotation disc would invert its own intent
    # and make the same line seven cells HARDER than a real obstacle for a pivot while staying
    # a centimetre softer for every other primitive, out of one grid in one search. It is not
    # a rounding either: on `04-five-obstacles` it costs about 17% of the arena's free cells.
    #
    # So the disc is run over a grid in which only the obstacles are blocked, and the result is
    # intersected back with `free_cells`. The intersection is what keeps the two conditions
    # separate and both enforced: rotation clearance is measured from the obstacles alone,
    # while the centre path itself must still be somewhere the robot's centre may legally be -
    # inside the band, inside the arena - exactly as a turn's cells must. It is also what makes
    # `eroded` a subset of `free_cells`, which `_Search.__move` depends on when it rebuilds a
    # traced pivot against the ordinary grid and asserts the answer is not None.
    #
    # The band is read off an obstacle-free `World` rather than restated here, for the reason
    # `_STEP` is derived from `straight()`: `World.__annotate_grid` is where that rule lives,
    # it reads four config values at call time, and a second copy of it here could disagree
    # with the grid this is being subtracted from and nothing would catch it.
    #
    # An obstacle that reaches into the band keeps its clearance regardless, and the reason is
    # not a size argument about the band being thinner than an inflated obstacle - it holds for
    # any band. The cells this frees are exactly `box & band` for each obstacle's inflated box.
    # A legal centre is outside the band by definition, the box is convex and axis-aligned, so
    # the straight line from that centre to any freed cell leaves the band while still inside
    # the box - at a cell that is therefore still blocked in `unbounded`, and strictly nearer.
    # The nearest blockage to a legal centre is never one of the freed cells, so no erosion
    # that mattered is lost. Confirmed empirically too: an obstacle placed hard against the
    # south band still costs 742 start cells of rotation clearance.
    if shuffles:
        unbounded = np.ones_like(free_cells)
        unbounded[edge:edge + size, edge:edge + size] = (
            world.grid | ~World(size, world.robot, []).grid)
        eroded = _eroded(unbounded, clearance) & free_cells
    else:
        eroded = free_cells

    def legality(offsets: Iterable[tuple[int, int]], grid: np.ndarray = free_cells) -> bytes:
        """
        One byte per cell: may a move whose shape is ``offsets`` start there?

        ``grid`` is which free-cell array to ask. It defaults to the arena's own and the only
        caller that passes anything else is the pivot, which asks `eroded` because every cell
        of its centre path is driven rotated off the axis the grid was inflated for.
        """
        legal = np.ones((stride, stride), dtype=bool)
        for x, y in dict.fromkeys(offsets):
            legal &= grid[span + x:span + x + stride, span + y:span + y + stride]
        return legal.tobytes()

    tables = []
    for rank, direction in enumerate(ranks):
        moves: list[tuple[bytes, int, float, int]] = []

        for code, instruction in enumerate(turns, start=1):
            arc = arcs.get((direction, instruction))
            if arc is None:
                continue
            offsets, (end_x, end_y), facing = arc
            delta = (rank_of[facing] - rank) * cells + end_x * stride + end_y
            moves.append((legality(offsets), delta, weights.turn(instruction, cell_size), code))

        step_x, step_y = _STEP[direction]
        for code, (move, length) in enumerate(chunks, start=len(_TURNS) + 1):
            modifier = 1 if move == Straight.FORWARD else -1
            offsets = [(step_x * modifier * i, step_y * modifier * i) for i in range(1, length + 1)]
            delta = modifier * length * (step_x * stride + step_y)
            # Priced as the ground it covers, not as its cell count: a diagonal cell is
            # sqrt(2). Same helper the report and the driving instruction use.
            moves.append((legality(offsets), delta,
                          weights.straight(cost.straight_cells(direction, length), cell_size), code))

        # Appended AFTER the straights, which is what leaves every code above untouched. The
        # enumeration runs over the whole `_PIVOTS` tuple and skips what this search cannot
        # offer, so a code stays the instruction's position in that tuple whichever subset is
        # in play - see `_PIVOTS`.
        for code, instruction in enumerate(pivots, start=len(_TURNS) + len(chunks) + 1):
            shuffle = shuffles.get((direction, instruction))
            if shuffle is None:
                continue
            offsets, (end_x, end_y), facing = shuffle
            delta = (rank_of[facing] - rank) * cells + end_x * stride + end_y
            moves.append((legality(offsets, eroded), delta,
                          weights.pivot(instruction, cell_size), code))

        tables.append(tuple(moves))

    return pad, stride, tuple(tables), chunks
