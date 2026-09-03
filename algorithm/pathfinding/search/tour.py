"""
Shortest-time visiting order.

A leg-cost matrix over goal-pose sets, exhaustive branch-and-bound over the order (the
algorithms deck: at this size "we can afford the cost of the exhaustive search"), then each
leg re-planned from the robot's real end pose.

The matrix prices a leg from ANYWHERE in an obstacle's goal-pose set, while the robot drives
it from the one pose it arrived at, so a matrix cost is a LOWER BOUND on the real leg and the
cheapest order under the matrix is not always the cheapest order in reality - measured at
7.2% the wrong way on ``testdata/04-five-obstacles.json``. So the matrix is not used to pick
the order. It is used to ENUMERATE orders cheapest-bound-first, and the bound then bounds a
search over real, re-planned routes: once the next candidate's bound exceeds the best real
route found so far, no remaining candidate can beat it and the search stops.

The stages are separately testable on purpose, because they fail differently:
:func:`leg_matrix` is the expensive one (N+1 searches), :func:`candidate_orders` is the one
with the combinatorics, :func:`largest_feasible_subset` decides what to give up on, and only
:func:`plan_optimal` needs a World.
"""
from __future__ import annotations

import heapq
import logging
import math
from typing import Iterable, Sequence

from pathfinding import cost
from pathfinding.report import UnreachableObstacle, UnreachableReason
from pathfinding.search.search import Segment, SearchResult, require_accounting, search
from pathfinding.search.segment import reach, segment
from pathfinding.world.objective import ObjectiveGeneration
from pathfinding.world.world import Obstacle, World

logger = logging.getLogger(__name__)

# Above this many obstacles the permutation search is replaced by greedy on the matrix.
# 9! = 362880 orders, each pruned hard by the bound; 10! is 3.6 million and the request
# times out. Task 1 fields at most 8 obstacles, so the cap is headroom, not a compromise.
MAX_EXHAUSTIVE = 9

# How many candidate orders plan_optimal will re-plan for real before it settles for the best
# it has. Each one costs a full set of single-goal searches (about 0.4 s per leg), so this is
# the knob that trades planning time for route quality. Hitting it means the answer is the
# best of those tried rather than proven optimal, and that is logged.
MAX_REPLANS = 8

Matrix = Sequence[Sequence[float]]


def leg_matrix(
    world: World,
    generated: ObjectiveGeneration,
    weights: cost.Weights = cost.TIME_SECONDS,
) -> tuple[list[Obstacle], list[list[float]]]:
    """
    The cost of every leg between goal-pose sets.

    Node 0 is the robot's start pose; node ``k + 1`` is ``nodes[k]``'s whole goal-pose set,
    not one representative pose - the robot may photograph an obstacle from any of them, and
    pricing the set is what lets the order be chosen before the poses are.

    One :func:`~pathfinding.search.segment.reach` per node: N+1 searches for N obstacles,
    each well under a tenth of a second on a 200x200x4 grid. Row ``i`` is measured from anywhere in
    node ``i``'s set, so ``matrix[i][j]`` is a LOWER BOUND on the real leg - the robot will
    actually leave from the one pose it arrived at, which is why every leg is re-planned in
    :func:`plan_optimal` rather than trusted from here.

    :param world: The world.
    :param generated: The goal poses, from
        :func:`~pathfinding.world.objective.generate_objectives` for this same world.
    :param weights: What a move costs. Time by default: this module exists to minimise it.
    :return: The obstacles in node order, and the ``(N+1) x (N+1)`` cost matrix.
        ``matrix[i][i]`` is 0 and column 0 is unused - nothing returns to the start, since
        the run ends wherever the last photograph was taken.
    """
    nodes = list(generated.objectives)
    poses = [{world.robot.vector}] + [generated.objectives[obstacle][1] for obstacle in nodes]
    index = {obstacle: k + 1 for k, obstacle in enumerate(nodes)}
    matrix = [[math.inf] * len(poses) for _ in poses]

    for i, sources in enumerate(poses):
        matrix[i][i] = 0.0
        # Node i is excluded from its own targets: it is the source, so it would price at 0.
        targets = {obstacle: generated.objectives[obstacle][1] for obstacle in nodes if index[obstacle] != i}
        for obstacle, leg in reach(world, sources, targets, weights).items():
            matrix[i][index[obstacle]] = leg

    return nodes, matrix


def best_order(matrix: Matrix, *, exhaustive_up_to: int = MAX_EXHAUSTIVE) -> list[int] | None:
    """
    The cheapest order in which to visit nodes 1..N, starting from node 0.

    A Hamiltonian PATH, not a cycle: the robot does not drive home afterwards, so the return
    leg is not costed and node 0 is never re-entered.

    The matrix's own favourite, which is NOT the route :func:`plan_optimal` drives - see the
    module docstring on why the matrix is a lower bound and :func:`candidate_orders` is what
    the planner iterates. Kept because it is the honest answer to "what does the matrix
    think", and it is what :func:`largest_feasible_subset` needs to know whether every node
    fits at all. Implemented as :func:`_longest_order` plus a completeness check: "as many
    nodes as possible, cheapest among those" IS the cheapest complete order whenever a
    complete one exists, so there is no second search to keep in step with this one.

    :param matrix: The leg costs, as :func:`leg_matrix` returns them. ``math.inf`` means the
        leg does not exist.
    :param exhaustive_up_to: The largest N still searched exhaustively; above it the order
        is chosen greedily instead. Lowering it in a test is cheaper than building a matrix
        with ten nodes.
    :return: Node indices 1..N in visit order, ``[]`` when there are no nodes, or None when
        no complete order exists (some node is unreachable from every predecessor). Above
        the cap, None also means *greedy* found no complete order, which is weaker: a
        complete order may still exist.
    """
    n = len(matrix) - 1
    if n == 0:
        return []
    order = _longest_order(matrix, exhaustive_up_to=exhaustive_up_to)
    return order if len(order) == n else None


def candidate_orders(
    matrix: Matrix,
    *,
    over: Iterable[int] | None = None,
    limit: float = math.inf,
    keep: int | None = None,
    exhaustive_up_to: int = MAX_EXHAUSTIVE,
) -> list[tuple[float, list[int]]]:
    """
    Every complete order over the nodes, cheapest matrix bound first.

    :func:`best_order` answers "which order does the matrix like best"; this answers "which
    orders should we actually try", which is the question that matters once the matrix is
    known to be a lower bound rather than the truth. Ascending order is the whole point: a
    caller re-plans candidates for real until the next bound exceeds the best real route it
    has, at which point no remaining candidate can beat it.

    :param matrix: The leg costs, as :func:`leg_matrix` returns them.
    :param over: The node indices to visit, default all of them. Pass
        :func:`largest_feasible_subset`'s order to enumerate over just the obstacles that can
        be visited at all. Indices are the ORIGINAL matrix's throughout - there is no
        re-indexing to undo.
    :param limit: Skip candidates whose bound is at or above this. A caller that already has
        a real route costing ``limit`` can never be beaten by them, and pruning the
        enumeration is much cheaper than sorting it. Only sound when that real route already
        visits every node in ``over`` - otherwise a dearer candidate may visit MORE.
    :param keep: Return at most this many, the cheapest ones. **Pass it.** A caller only ever
        re-plans a handful, and without it the search builds every complete order before
        throwing nearly all of them away - 2.9 s and 83 MB at 9 nodes, against 0.2 s and under
        a megabyte for the ten cheapest. The k-th cheapest found so far tightens ``limit`` as
        the search runs, so this prunes rather than merely truncates.
    :param exhaustive_up_to: Above this many nodes the enumeration is replaced by the single
        greedy order, since the permutations no longer fit in a request.
    :return: ``(bound, order)`` pairs, ascending by bound then by order for determinism.
        Empty when no complete order exists (or none under ``limit``); empty, too, when there
        are no nodes at all - there is no route to try. A result of exactly ``keep`` entries
        means the search was cut off and cheaper-bound orders may remain unexamined, which is
        what :func:`plan_optimal` reads to decide whether its answer is proven.
    """
    nodes = sorted(range(1, len(matrix)) if over is None else over)
    n = len(nodes)
    if n == 0:
        return []
    if n > exhaustive_up_to:
        order = _greedy(matrix, over=nodes)
        if len(order) < n:
            return []
        bound = sum(matrix[i][j] for i, j in zip([0] + order, order))
        return [(bound, order)] if bound < limit else []

    # A heap of the best `keep` so far, ordered so that heappop removes the WORST of them:
    # both the cost and the order are negated, which makes heapq's min the maximum of
    # (bound, order) and so keeps the k cheapest deterministically even when bounds tie.
    kept: list[tuple[float, tuple[int, ...]]] = []
    cutoff = limit

    def extend(node: int, visited: int, so_far: float, order: list[int]) -> None:
        nonlocal cutoff
        if so_far >= cutoff:
            return                                   # bound
        if len(order) == n:
            heapq.heappush(kept, (-so_far, tuple(-j for j in order)))
            if keep is not None and len(kept) > keep:
                heapq.heappop(kept)
                cutoff = min(limit, -kept[0][0])     # the k-th cheapest now bounds the search
            return
        for j in nodes:
            if visited & (1 << j):
                continue
            step = matrix[node][j]
            if step == math.inf:
                continue
            order.append(j)
            extend(j, visited | (1 << j), so_far + step, order)
            order.pop()

    extend(0, 0, 0.0, [])
    return sorted((-bound, [-j for j in order]) for bound, order in kept)


def largest_feasible_subset(
    matrix: Matrix,
    *,
    exhaustive_up_to: int = MAX_EXHAUSTIVE,
) -> tuple[list[int], list[int]]:
    """
    The visit order over the largest subset of nodes that can be visited at all.

    An obstacle no order can include - boxed in, or reachable from nowhere the route passes -
    must not cost the other obstacles their route. When every node fits, this is exactly
    :func:`best_order`; when one does not, the answer is the order visiting the MOST nodes,
    cheapest among those, and the rest are dropped.

    DEVIATION from the design doc, which prescribed "drop the obstacle with the fewest finite
    entries and retry". That heuristic does not find the largest feasible subset, and its
    failures are severe rather than marginal - it drops whichever node is hardest to arrive
    at, which is often a node the route could perfectly well have ENDED at::

        m = [[0,   1, inf, inf],      # 0 -> 1 -> 2 visits two nodes
             [0,   0,   1,   1],      # but 2 and 3 have the fewest finite entries,
             [0, inf,   0, inf],      # so 1 is dropped first, then everything,
             [0, inf, inf,   0]]      # and the robot visits nothing

    On a crowded 8-obstacle arena that cost every obstacle in the plan while greedy
    :func:`~pathfinding.search.search.search` still photographed two. Searching for the
    longest path instead costs nothing when a complete order exists (the first dive finds
    one, and the cost bound is live from then on) and is bounded by the same N <= 9 when one
    does not.

    :param matrix: The leg costs, as :func:`leg_matrix` returns them.
    :param exhaustive_up_to: Passed through to :func:`best_order` and the fallback.
    :return: The visit order as node indices into ``matrix``, and the dropped node indices in
        node order. Both are indices into the ORIGINAL matrix, so a caller maps straight back
        to ``nodes[index - 1]`` with no re-indexing of its own.
    """
    order = _longest_order(matrix, exhaustive_up_to=exhaustive_up_to)
    visiting = set(order)
    return order, [j for j in range(1, len(matrix)) if j not in visiting]


def _longest_order(matrix: Matrix, *, exhaustive_up_to: int) -> list[int]:
    """
    The order visiting the most nodes, cheapest among the orders that visit that many.

    :func:`best_order` with the goal relaxed from "all the nodes" to "as many as possible",
    for when no complete order exists. The cost bound only applies once a complete order has
    been found - while a longer one is still possible, a dearer prefix cannot be abandoned -
    so this enumerates simple paths rather than permutations. That is affordable only because
    it needs no complete order to exist, which in turn means the matrix is sparse: a matrix
    dense enough to be expensive here has a complete order, and :func:`best_order` would have
    returned it instead of None.
    """
    n = len(matrix) - 1
    if n > exhaustive_up_to:
        return _greedy(matrix)

    best: list[int] = []
    best_cost = math.inf

    def extend(node: int, visited: int, so_far: float, order: list[int]) -> None:
        nonlocal best, best_cost
        if len(order) > len(best) or (len(order) == len(best) and so_far < best_cost):
            best, best_cost = list(order), so_far
        if len(best) == n and so_far >= best_cost:
            return                                   # bound, once nothing longer is possible
        for j in range(1, n + 1):
            if visited & (1 << j) or matrix[node][j] == math.inf:
                continue
            order.append(j)
            extend(j, visited | (1 << j), so_far + matrix[node][j], order)
            order.pop()

    extend(0, 0, 0.0, [])
    return best


def _greedy(matrix: Matrix, *, over: Iterable[int] | None = None) -> list[int]:
    """
    Nearest-next order on the matrix, for N above the exhaustive cap.

    Stops where no finite leg remains, so the order it returns may be partial - that is what
    makes it usable both as :func:`best_order`'s fallback (which rejects a partial order) and
    as :func:`_longest_order`'s (which keeps it).
    """
    order: list[int] = []
    node, left = 0, set(range(1, len(matrix)) if over is None else over)

    while left:
        j = min(left, key=lambda k: matrix[node][k])
        if matrix[node][j] == math.inf:
            break
        order.append(j)
        left.remove(j)
        node = j

    return order


def plan_optimal(world: World, generated: ObjectiveGeneration) -> SearchResult:
    """
    Plan a route visiting as many obstacles as it can, in the shortest estimated time.

    The optimising counterpart to :func:`~pathfinding.search.search.search`, which is greedy.
    Same inputs, same result type, same partition guarantee.

    Branch and bound over REAL routes, not over the matrix. Every candidate is re-planned
    from the pose each previous leg actually ended at and costed from those legs, so the
    number compared is the number the robot will experience; the matrix only supplies the
    admissible lower bound that says when to stop looking.

    Routes are compared by :func:`_score` - obstacles photographed FIRST, seconds second. An
    obstacle is points; a faster route that abandons one is not an improvement.

    **Never worse than greedy on that comparison**, and that is a property of the algorithm
    rather than of the arena: greedy's actual :class:`~pathfinding.search.search.SearchResult`
    is itself one of the routes scored, so the answer is that route or one that beats it. Its
    order is scored too, re-planned under the time weights, since the same order driven with
    time-costed legs is often cheaper than the distance-costed original - but the route greedy
    really produced is what guarantees the floor, because re-planning an order can lose a leg
    that greedy's own pose sequence happened to make.

    Costs at most :data:`MAX_REPLANS` re-planned candidates on top of the leg matrix. Hitting
    that cap is logged: the answer is then the best of the ones tried, not a proven optimum.

    :param world: The world.
    :param generated: The goal poses, from
        :func:`~pathfinding.world.objective.generate_objectives` for this same world.
    :return: A :class:`~pathfinding.search.search.SearchResult` holding the segments in visit
        order and every obstacle not visited.
    :raises ValueError: If ``generated`` does not account for exactly ``world.obstacles``.
    """
    require_accounting(world, generated)

    nodes, matrix = leg_matrix(world, generated)
    node_of = {obstacle.image_id: k + 1 for k, obstacle in enumerate(nodes)}
    visit, _ = largest_feasible_subset(matrix)

    # The floor. search() is a second full greedy plan (about 0.05 s against the matrix's 0.4),
    # and it earns that: without a seed there is nothing to bound the candidate search
    # against, and no guarantee the answer beats the planner this one replaces.
    #
    # Both readings of greedy are scored - the route it ACTUALLY produced, and its order
    # re-planned under the time weights, which is usually cheaper because the legs are then
    # costed in the unit being minimised. The real route is what makes the floor a guarantee:
    # re-planning an order can lose a leg that greedy's own pose sequence happened to allow,
    # and scoring only the re-planned version could then come back worse than greedy.
    greedy = search(world, generated)
    greedy_order = [node_of[seg.image_id] for seg in greedy.segments]
    best = min(_route(world, generated, nodes, greedy_order), greedy.segments, key=_score)
    best_score = _score(best)
    greedy_seconds = _score(greedy.segments)[1]

    # Greedy's order is frequently the matrix's favourite too, and re-planning a route twice
    # costs a full set of searches for an answer already known.
    evaluated = {tuple(greedy_order)}

    # Pruning the enumeration by cost is only sound while the route being compared against
    # already visits every obstacle any order could: otherwise a candidate the matrix prices
    # above it may still photograph MORE obstacles, which outranks any number of seconds.
    limit = best_score[1] if len(best) == len(visit) else math.inf

    # One more than can be re-planned, so the loop gets to SEE the bound that lets it stop.
    candidates = candidate_orders(matrix, over=visit, limit=limit, keep=MAX_REPLANS + 1)
    truncated = len(candidates) == MAX_REPLANS + 1   # cheaper orders may lie beyond these
    replans = 0
    proven = False
    capped = False

    for bound, order in candidates:
        if len(best) == len(visit) and bound >= best_score[1]:
            proven = True                            # no remaining candidate can win
            break
        if tuple(order) in evaluated:
            continue
        if replans >= MAX_REPLANS:
            capped = True
            break

        route = _route(world, generated, nodes, order)
        evaluated.add(tuple(order))
        replans += 1
        if _score(route) < best_score:
            best, best_score = route, _score(route)

    # Running out of candidates is only a proof when there were no more to run out of.
    # Above MAX_EXHAUSTIVE the candidates are greedy only, so nothing is proven there either.
    proven = (proven or not (capped or truncated)) and len(visit) <= MAX_EXHAUSTIVE
    if not proven:
        logger.warning(
            "Re-planned %s candidate order(s) without exhausting the alternatives; keeping the "
            "best of those (%.2f s over %s obstacle(s)). This route is the best one tried, not a "
            "proven optimum. Raise MAX_REPLANS to search harder.",
            replans, best_score[1], len(best),
        )

    logger.info(
        "Route: %s obstacle(s) in %.2f s, %s, from %s re-planned candidate(s) plus greedy's own "
        "route (%.2f s).",
        len(best), best_score[1], "optimal" if proven else "best of those tried", replans,
        greedy_seconds,
    )

    # The partition, built from the route that actually won rather than from the matrix's
    # opinion beforehand: every obstacle with goal poses that is not in the route is NO_PATH.
    # Derived, so segments and unreachable cannot disagree whichever candidate came out on top.
    photographed = {seg.image_id for seg in best}
    plannable = {nodes[node - 1].image_id for node in visit}
    unreachable: list[UnreachableObstacle] = list(generated.unreachable)

    for obstacle in generated.objectives:
        if obstacle.image_id in photographed:
            continue
        unreachable.append(UnreachableObstacle(obstacle.image_id, UnreachableReason.NO_PATH))

        # Both are NO_PATH, and they are not the same problem. The first is a matrix fact -
        # nothing reaches this obstacle from anywhere, so no order could ever have included
        # it. The second is a fact about the route that won: the matrix priced a leg from the
        # previous obstacle's whole pose set, and the robot arrived at the one pose in that
        # set the leg does not exist from. Only the second can be recovered by a different
        # route, so telling them apart is what says whether searching harder would help.
        if obstacle.image_id in plannable:
            logger.warning(
                "Dropped image_id %s (%s face, %s-%s) from the route: the leg matrix prices a leg "
                "into its %s goal pose(s), but none exists from the pose the chosen route actually "
                "arrives at. Skipping.",
                obstacle.image_id,
                obstacle.direction.value,
                obstacle.south_west,
                obstacle.north_east,
                len(generated.objectives[obstacle][1]),
            )
        else:
            logger.warning(
                "No visiting order includes image_id %s (%s face, %s-%s): it has %s goal pose(s), "
                "but no leg reaches them from the start or from any other obstacle's poses. "
                "Skipping.",
                obstacle.image_id,
                obstacle.direction.value,
                obstacle.south_west,
                obstacle.north_east,
                len(generated.objectives[obstacle][1]),
            )

    return SearchResult(best, unreachable)


def _route(
    world: World,
    generated: ObjectiveGeneration,
    nodes: list[Obstacle],
    order: list[int],
) -> list[Segment]:
    """
    Re-plan one visiting order for real, from the robot's start pose.

    Each leg starts at the pose the previous one ended at, which is what the leg matrix cannot
    know. A leg that fails from that real pose is skipped and the route carries on: it is the
    one obstacle lost, not the run. A finite matrix entry therefore does not guarantee a leg,
    and that is not a contradiction - the matrix priced it from ANY of the previous obstacle's
    poses and the robot stands on exactly one of them.
    """
    segments: list[Segment] = []
    current = world.robot.vector

    for node in order:
        obstacle = nodes[node - 1]
        leg = segment(world, current, {obstacle: generated.objectives[obstacle]}, weights=cost.TIME_SECONDS)
        if leg is None:
            continue
        segments.append(Segment.compress(world, leg))
        current, _ = leg[2][-1]

    return segments


def _score(segments: list[Segment]) -> tuple[int, float]:
    """
    How good a route is, lowest wins: obstacles photographed (negated) first, then seconds.

    Negating the count rather than maximising it keeps the whole comparison a single ``<``,
    and puts the two criteria in the order the rules put them - an obstacle is points.
    """
    return -len(segments), sum(seg.seconds for seg in segments)
