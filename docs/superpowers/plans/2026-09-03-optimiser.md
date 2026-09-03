# Optimiser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A shortest-time visiting order and time-costed legs (checklist B.3), served by default over HTTP and selectable in the simulator.

**Architecture:** A cost model (`pathfinding/cost.py`) shared by the search, the tour and the simulator clock; a multi-source `reach()` in the existing search; a new `tour.py` that builds the leg matrix, orders by exhaustive branch-and-bound, and re-plans legs from real poses. Greedy stays as it is.

**Tech Stack:** Python 3.11, numpy, pydantic, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-03-optimiser-design.md`

## Global Constraints

- Work from `algorithm/` with `./.venv/bin/python`. Tests `./.venv/bin/python -m pytest tests -q` (60 pass today); smoke `./.venv/bin/python smoke.py` stays 4/4 (plus the new run).
- **No `git add` or `git commit`.** The owner commits.
- Tuneable numbers in `config.py` with a `# SOURCE:` comment, read at call time; never `from config import X`.
- `search()` (greedy) behaviour and `smoke.py` baselines (segment counts, unreachable sets) are unchanged. `Segment.cost` stays integer centimetres on the wire.
- `segments` and `unreachable` partition the obstacles in every result.
- No emoji. Short docstrings.

---

### Task 1: cost model, `Segment.seconds`, weighted search

**Files:**
- Create: `algorithm/pathfinding/cost.py`
- Modify: `algorithm/config.py` (add `TURN_TIME_S`), `algorithm/pathfinding/search/segment.py`, `algorithm/pathfinding/search/search.py`
- Test: `algorithm/tests/test_cost.py`

**Interfaces:**
- Produces: `cost.Weights` Protocol; `cost.DISTANCE_CELLS`, `cost.TIME_SECONDS`; `cost.seconds(moves, cell_size) -> float`; `segment(world, initial, objectives, weights=cost.DISTANCE_CELLS)` where `initial: Vector | Iterable[Vector]`; `Segment.seconds: float`; `Segment.cost` computed from moves.

- [ ] **Step 1: failing tests**

`algorithm/tests/test_cost.py`:
```python
import os

import pytest

import config
from pathfinding import cost
from pathfinding.search.instructions import Move, Straight, Turn, TurnInstruction
from pathfinding.search.search import search
from pathfinding.search.segment import segment
from pathfinding.world.objective import generate_objectives
from pathfinding.world.primitives import Direction, Vector
from simulator.arena import load

TESTDATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testdata")


def cells(n):
    return [Vector(Direction.NORTH, 0, i) for i in range(n)]


def test_time_weights_read_config_at_call_time(monkeypatch):
    monkeypatch.setattr(config, "ROBOT_SPEED_CM_S", 50)
    monkeypatch.setattr(config, "TURN_TIME_S", 4.0)
    assert cost.TIME_SECONDS.straight(25, 1) == pytest.approx(0.5)
    assert cost.TIME_SECONDS.turn(TurnInstruction.FORWARD_LEFT) == 4.0
    assert cost.DISTANCE_CELLS.straight(25, 1) == 25
    assert cost.DISTANCE_CELLS.turn(TurnInstruction.FORWARD_LEFT) == TurnInstruction.FORWARD_LEFT.arc_length(1)


def test_seconds_sums_moves():
    moves = [Move(Straight.FORWARD, cells(30)), Turn(TurnInstruction.FORWARD_RIGHT, cells(5)), Move(Straight.BACKWARD, cells(10))]
    expected = 40 / config.ROBOT_SPEED_CM_S + config.TURN_TIME_S
    assert cost.seconds(moves, 1) == pytest.approx(expected)


def test_segment_cost_is_still_centimetres_and_seconds_matches_model():
    world = load(os.path.join(TESTDATA, "02-four-obstacles.json")).world()
    result = search(world, generate_objectives(world))
    assert [s.cost for s in result.segments] == [88, 91, 280, 460]
    for s in result.segments:
        assert s.seconds == pytest.approx(cost.seconds(s.moves, world.cell_size))
        assert s.seconds > 0


def test_time_weighted_leg_is_no_slower_than_distance_weighted():
    world = load(os.path.join(TESTDATA, "02-four-obstacles.json")).world()
    generated = generate_objectives(world)
    start = world.robot.vector
    by_distance = segment(world, start, generated.objectives)
    by_time = segment(world, start, generated.objectives, weights=cost.TIME_SECONDS)
    assert by_distance is not None and by_time is not None
    _, d_cost, d_parts = by_distance
    _, t_cost, t_parts = by_time
    assert isinstance(t_cost, float)
    assert t_cost <= cost.seconds([m for _, m in d_parts if m is not None], world.cell_size) + 1e-9


def test_segment_accepts_a_set_of_sources():
    world = load(os.path.join(TESTDATA, "01-single-obstacle.json")).world()
    generated = generate_objectives(world)
    start = world.robot.vector
    single = segment(world, start, generated.objectives)
    multi = segment(world, {start, Vector(Direction.NORTH, 100, 100)}, generated.objectives)
    assert single is not None and multi is not None
    assert multi[1] <= single[1]
```

- [ ] **Step 2: run, expect ImportError on `pathfinding.cost`**

- [ ] **Step 3: config**

Append to the **Motion primitives** section of `config.py`:
```python
# Seconds the robot takes for one 90 degree turn at competition speed, arc included. The time
# model charges this per turn and cells/ROBOT_SPEED_CM_S per straight cell; the optimiser and the
# simulator clock both use it.
# SOURCE: STM | placeholder | NOT MEASURED. 3.0 is a guess: a 40 cm radius arc is 63 cm, about
#   2 s at 30 cm/s, plus steering. Measure together with TURN_RADIUS_CM and ROBOT_SPEED_CM_S.
TURN_TIME_S = 3.0
```

- [ ] **Step 4: `pathfinding/cost.py`**

```python
"""
What a move costs. Two models: DISTANCE_CELLS is the search's original objective (grid cells,
arc_length cells per turn); TIME_SECONDS is the estimate the optimiser minimises and the
simulator clock shows. Both read config at call time.
"""
from __future__ import annotations

from typing import Protocol

import config
from pathfinding.search.instructions import Move, Turn, TurnInstruction


class Weights(Protocol):
    def turn(self, turn: TurnInstruction, cell_size: int = 1) -> float: ...
    def straight(self, cells: int, cell_size: int = 1) -> float: ...


class _Distance:
    def turn(self, turn: TurnInstruction, cell_size: int = 1) -> float:
        return turn.arc_length(cell_size)

    def straight(self, cells: int, cell_size: int = 1) -> float:
        return cells


class _Time:
    def turn(self, turn: TurnInstruction, cell_size: int = 1) -> float:
        return config.TURN_TIME_S

    def straight(self, cells: int, cell_size: int = 1) -> float:
        return cells * cell_size / config.ROBOT_SPEED_CM_S


DISTANCE_CELLS: Weights = _Distance()
TIME_SECONDS: Weights = _Time()


def move_cost(move: Turn | Move, weights: Weights, cell_size: int) -> float:
    if isinstance(move, Turn):
        return weights.turn(move.turn, cell_size)
    return weights.straight(len(move.vectors), cell_size)


def seconds(moves, cell_size: int) -> float:
    """Estimated driving time of a sequence of moves under the time model."""
    return sum(move_cost(m, TIME_SECONDS, cell_size) for m in moves)
```
Note `cost.py` imports `instructions.py`, which imports `config` only; no cycle with `segment.py`.

- [ ] **Step 5: `segment.py`**

- Signature: `def segment(world, initial: Vector | Iterable[Vector], objectives, weights: Weights = cost.DISTANCE_CELLS)`.
- Seed the frontier with every source pose at cost 0 (`source[v] = None`, `moves[v] = None`).
- Replace the two `new_cost +=` lines with `new_cost = costs[current] + cost.move_cost(move, weights, world.cell_size)`.
- Costs become `float`; the priority queue tuple stays `(cost, vector)` (Vector is orderable).
- `__trace` returns `costs[objective]` as before (now a float for time, int-valued for distance).
Import `from pathfinding import cost` at the top (module name `cost`; keep the local variable names `new_cost` etc. to avoid shadowing).

- [ ] **Step 6: `search.py`**

- `Segment` gains `seconds: float` after `moves`.
- `Segment.compress` computes `cost` from the parts instead of taking the search cost: `cost = round(sum(cost.move_cost(m, cost.DISTANCE_CELLS, world.cell_size) for m in moves))` and `seconds = cost.seconds(moves, world.cell_size)`. Rename the incoming tuple's cost to `_search_cost` and ignore it. (For distance-weighted searches the two are identical; the test above pins 88/91/280/460.)
- Nothing else changes; `search()` still calls `segment(world, current, remaining)` with default weights.

- [ ] **Step 7: run, expect green; smoke 4/4**

---

### Task 2: `reach()` and `tour.py`

**Files:**
- Modify: `algorithm/pathfinding/search/segment.py` (add `reach`)
- Create: `algorithm/pathfinding/search/tour.py`
- Test: `algorithm/tests/test_tour.py`

**Interfaces:**
- Produces: `segment.reach(world, sources, targets: dict[Obstacle, set[Vector]], weights) -> dict[Obstacle, float]` (only obstacles reached appear); `tour.leg_matrix(world, generated, weights=cost.TIME_SECONDS) -> tuple[list[Obstacle], list[list[float]]]` (node 0 is the start; `matrix[i][j]` is the cost from node i's pose set to node j's, `inf` if unreachable, `0` on the diagonal, column 0 unused); `tour.best_order(matrix, *, exhaustive_up_to=9) -> list[int] | None` (node indices 1..N in visit order, or None if no complete tour); `tour.plan_optimal(world, generated) -> SearchResult`; `tour.MAX_EXHAUSTIVE = 9`.

- [ ] **Step 1: failing tests**

`algorithm/tests/test_tour.py`:
```python
import math
import os

import pytest

from pathfinding import cost
from pathfinding.report import UnreachableReason
from pathfinding.search import tour
from pathfinding.search.search import search
from pathfinding.search.segment import reach, segment
from pathfinding.world.objective import generate_objectives
from simulator.arena import load

TESTDATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testdata")
INF = math.inf


def test_best_order_finds_the_known_optimum():
    #      0    1    2    3
    m = [[0,   1,  10,  10],
         [0,   0,   1,  10],
         [0,  10,   0,   1],
         [0,   1,  10,   0]]
    assert tour.best_order(m) == [1, 2, 3]


def test_best_order_prefers_a_longer_first_leg_when_the_total_is_smaller():
    m = [[0,   1,   5],
         [0,   0,  10],
         [0,   1,   0]]
    assert tour.best_order(m) == [2, 1]          # 5 + 1 = 6 beats 1 + 10 = 11


def test_best_order_returns_none_without_a_complete_tour():
    m = [[0, 1, INF],
         [0, 0, INF],
         [0, 1, 0]]
    assert tour.best_order(m) is None


def test_best_order_falls_back_to_greedy_above_the_cap():
    n = tour.MAX_EXHAUSTIVE + 1
    m = [[abs(i - j) for j in range(n + 1)] for i in range(n + 1)]
    order = tour.best_order(m)
    assert sorted(order) == list(range(1, n + 1))
    assert order[0] == 1                          # greedy from node 0 picks the nearest


def test_reach_matches_single_goal_costs_from_the_start():
    world = load(os.path.join(TESTDATA, "02-four-obstacles.json")).world()
    generated = generate_objectives(world)
    start = world.robot.vector
    reached = reach(world, {start}, generated.objectives, cost.TIME_SECONDS)
    assert set(reached) == set(generated.objectives)
    for obstacle, poses in generated.objectives.items():
        single = segment(world, start, {obstacle: poses}, weights=cost.TIME_SECONDS)
        assert single is not None
        assert reached[obstacle] == pytest.approx(single[1])


def test_leg_matrix_shape_and_diagonal():
    world = load(os.path.join(TESTDATA, "02-four-obstacles.json")).world()
    nodes, m = tour.leg_matrix(world, generate_objectives(world))
    assert len(nodes) == 4 and len(m) == 5 and all(len(row) == 5 for row in m)
    assert all(m[i][i] == 0 for i in range(5))
    assert all(m[0][j] < INF for j in range(1, 5))


def test_plan_optimal_is_no_slower_than_greedy_and_partitions():
    world = load(os.path.join(TESTDATA, "02-four-obstacles.json")).world()
    generated = generate_objectives(world)
    greedy = search(world, generated)
    optimal = tour.plan_optimal(world, generated)
    assert sorted(s.image_id for s in optimal.segments) == [11, 12, 13, 14]
    assert optimal.unreachable == []
    assert sum(s.seconds for s in optimal.segments) <= sum(s.seconds for s in greedy.segments) + 1e-9
    assert all(s.instructions[-1].value == "CAPTURE_IMAGE" for s in optimal.segments)


def test_plan_optimal_keeps_no_objectives_and_reports_no_path():
    world = load(os.path.join(TESTDATA, "03-unreachable.json")).world()
    result = tour.plan_optimal(world, generate_objectives(world))
    assert [s.image_id for s in result.segments] == [11]
    assert {(u.image_id, u.reason) for u in result.unreachable} == {(13, UnreachableReason.NO_OBJECTIVES)}
```

- [ ] **Step 2: run, expect ImportError**

- [ ] **Step 3: `reach()` in `segment.py`**

Same expansion as `segment()`, but it does not stop at the first goal: when a popped state lies in a target set whose obstacle has not been recorded yet, record `costs[current]` for that obstacle; stop when every target has been recorded or the frontier is empty. Factor the neighbour expansion so `segment()` and `reach()` share it (a private `__relax(world, current, frontier, source, moves, costs, weights)` helper is enough). Return `dict[Obstacle, float]` of the obstacles reached.

- [ ] **Step 4: `tour.py`**

```python
"""
Shortest-time visiting order. A leg-cost matrix over goal-pose sets, exhaustive branch-and-bound
over the order (the algorithms deck: at this size "we can afford the cost of the exhaustive
search"), then each leg re-planned from the robot's real end pose.
"""
from __future__ import annotations

import logging
import math

from pathfinding import cost
from pathfinding.report import UnreachableObstacle, UnreachableReason
from pathfinding.search.search import Segment, SearchResult
from pathfinding.search.segment import reach, segment
from pathfinding.world.objective import ObjectiveGeneration
from pathfinding.world.world import Obstacle, World

logger = logging.getLogger(__name__)

# Above this many obstacles the permutation search is replaced by greedy on the matrix.
MAX_EXHAUSTIVE = 9


def leg_matrix(world: World, generated: ObjectiveGeneration, weights: cost.Weights = cost.TIME_SECONDS):
    nodes = list(generated.objectives)
    sets = [{world.robot.vector}] + [generated.objectives[o][1] for o in nodes]
    n = len(nodes)
    matrix = [[math.inf] * (n + 1) for _ in range(n + 1)]
    for i, sources in enumerate(sets):
        matrix[i][i] = 0.0
        targets = {o: generated.objectives[o][1] for k, o in enumerate(nodes) if k + 1 != i}
        for o, c in reach(world, sources, targets, weights).items():
            matrix[i][nodes.index(o) + 1] = c
    return nodes, matrix


def best_order(matrix, *, exhaustive_up_to: int = MAX_EXHAUSTIVE) -> list[int] | None:
    n = len(matrix) - 1
    if n == 0:
        return []
    if n > exhaustive_up_to:
        return _greedy(matrix)
    best: list[int] | None = None
    best_cost = math.inf

    def extend(node: int, visited: int, so_far: float, order: list[int]) -> None:
        nonlocal best, best_cost
        if so_far >= best_cost:
            return                                   # bound
        if len(order) == n:
            best, best_cost = list(order), so_far
            return
        for j in range(1, n + 1):
            if visited & (1 << j):
                continue
            step = matrix[node][j]
            if step == math.inf:
                continue
            order.append(j)
            extend(j, visited | (1 << j), so_far + step, order)
            order.pop()

    extend(0, 0, 0.0, [])
    return best


def _greedy(matrix) -> list[int] | None:
    n = len(matrix) - 1
    order, node, left = [], 0, set(range(1, n + 1))
    while left:
        j = min(left, key=lambda k: matrix[node][k])
        if matrix[node][j] == math.inf:
            return None
        order.append(j)
        left.remove(j)
        node = j
    return order


def plan_optimal(world: World, generated: ObjectiveGeneration) -> SearchResult:
    unreachable = list(generated.unreachable)
    nodes, matrix = leg_matrix(world, generated)
    # Largest feasible subset: drop, one at a time, the obstacle with the fewest finite entries.
    active = list(range(1, len(nodes) + 1))
    while True:
        sub = [[matrix[i][j] for j in [0] + active] for i in [0] + active]
        order = best_order(sub)
        if order is not None or not active:
            break
        worst = min(active, key=lambda j: sum(1 for i in [0] + active if matrix[i][j] < math.inf))
        active.remove(worst)
        unreachable.append(UnreachableObstacle(nodes[worst - 1].image_id, UnreachableReason.NO_PATH))
        logger.warning("No tour includes image_id %s; dropping it.", nodes[worst - 1].image_id)
    visit = [nodes[active[k] - 1] for k in (order or [])]

    segments: list[Segment] = []
    current = world.robot.vector
    for obstacle in visit:
        leg = segment(world, current, {obstacle: generated.objectives[obstacle]}, weights=cost.TIME_SECONDS)
        if leg is None:
            unreachable.append(UnreachableObstacle(obstacle.image_id, UnreachableReason.NO_PATH))
            logger.warning("Leg to image_id %s failed from %s; skipping it.", obstacle.image_id, current)
            continue
        seg = Segment.compress(world, leg)
        segments.append(seg)
        current, _ = leg[2][-1]
    return SearchResult(segments, unreachable)
```
Careful with the sub-matrix indexing in `plan_optimal`: `best_order(sub)` returns indices into `sub`'s node list `[0] + active`, i.e. `k` in 1..len(active); map back with `active[k - 1]`. Write it that way (the sketch above has `active[k] - 1`, which is wrong; fix it) and cover it with the 03 test plus a test where the first obstacle is dropped.

- [ ] **Step 5: run, expect green; smoke 4/4**

---

### Task 3: HTTP `strategy` and `seconds`; smoke run; docs

**Files:**
- Modify: `algorithm/pathfinding_controller.py`, `algorithm/smoke.py`, `docs/protocols/algorithm-service.md`, `docs/protocols/openapi.json` (regenerate), `algorithm/README.md` (limitation 4 and 6), `algorithm/PROVENANCE.md` (gap 4 and 6)
- Test: `algorithm/tests/test_service.py`

- [ ] **Step 1: failing test**

`algorithm/tests/test_service.py`:
```python
import json
import os

from app import create_app

TESTDATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testdata")


def body(name, **extra):
    with open(os.path.join(TESTDATA, name)) as f:
        data = json.load(f)
    data.update(extra)
    return data


def test_default_strategy_is_optimal_and_greedy_is_selectable():
    client = create_app().test_client()
    greedy = client.post("/pathfinding/", json=body("02-four-obstacles.json", strategy="greedy", verbose=True)).json
    optimal = client.post("/pathfinding/", json=body("02-four-obstacles.json", verbose=True)).json
    assert [s["image_id"] for s in greedy["segments"]] == [12, 11, 14, 13]
    assert sorted(s["image_id"] for s in optimal["segments"]) == [11, 12, 13, 14]
    assert sum(s["seconds"] for s in optimal["segments"]) <= sum(s["seconds"] for s in greedy["segments"]) + 1e-9
    assert all(isinstance(s["cost"], int) for s in optimal["segments"])


def test_seconds_is_zero_when_not_verbose_and_bad_strategy_is_422():
    client = create_app().test_client()
    quiet = client.post("/pathfinding/", json=body("01-single-obstacle.json")).json
    assert quiet["segments"][0]["seconds"] == 0
    assert client.post("/pathfinding/", json=body("01-single-obstacle.json", strategy="fastest")).status_code == 422
```

- [ ] **Step 2: controller**

- `class Strategy(str, Enum): GREEDY = "greedy"; OPTIMAL = "optimal"` in the controller.
- `PathfindingRequest.strategy: Strategy = Field(default=Strategy.OPTIMAL, description="Visiting order: 'optimal' (shortest estimated time, default) or 'greedy' (nearest first).")`.
- `PathfindingResponseSegment.seconds: float = Field(default=0.0, description="Estimated driving time of this segment in seconds under the time model, only if verbose is true.")`; `from_segment` sets `round(segment.seconds, 2) if verbose else 0.0`.
- The route: `result = search(world, objectives) if body.strategy is Strategy.GREEDY else plan_optimal(world, objectives)`. Stub mode: unchanged (seconds 0).
- Log line includes the strategy.

- [ ] **Step 3: smoke**

Add a fifth run in `smoke.py`: the 4-obstacle nominal arena through `plan_optimal`, expecting 4 segments and no unreachable, and printing total seconds for both strategies; assert optimal's total seconds <= greedy's. Keep the existing four runs unchanged.

- [ ] **Step 4: docs**

Protocol doc: `strategy` under Request (default optimal, additive), `seconds` under Instructions/Response, deviation table row 6. Regenerate `docs/protocols/openapi.json` (indent 4, sorted keys, trailing newline: `json.dump(new, f, indent=4, sort_keys=True); f.write("\n")` from the test client). README limitation 4 "No visiting-order optimisation" becomes "Done: optimal by default; time constants are placeholders"; limitation 6 (B.3) becomes demonstrable via the simulator source switch. PROVENANCE gaps 4 and 6 likewise, plus a Design decision: "time model with placeholder constants; exhaustive branch-and-bound to 9 obstacles".

- [ ] **Step 5: run tests, smoke (5/5 now), and a curl of testdata 02 with and without `"strategy": "greedy"`**

---

### Task 4: simulator source, clock, panel

**Files:**
- Modify: `algorithm/simulator/routes.py`, `algorithm/simulator/playback.py`, `algorithm/simulator/app.py`, `algorithm/simulator/SPEC.md`, `algorithm/README.md` (Simulator section: B.3 line)
- Test: `algorithm/tests/test_routes.py`, `algorithm/tests/test_playback.py`

- [ ] **Step 1: failing tests**

Append to `tests/test_routes.py`:
```python
def test_optimal_source_is_registered_second_and_is_no_slower():
    from simulator.routes import OptimalRouteSource
    world = load(os.path.join(TESTDATA, "02-four-obstacles.json")).world()
    assert [s.name for s in SOURCES] == ["Greedy, nearest first", "Shortest time"]
    greedy = GreedyRouteSource().plan(world)
    optimal = OptimalRouteSource().plan(world)
    assert sorted(s.image_id for s in optimal.segments) == sorted(s.image_id for s in greedy.segments)
    assert optimal.seconds <= greedy.seconds + 1e-9
    assert greedy.seconds == pytest.approx(sum(s.seconds for s in greedy.segments))
```
(add `import pytest` at the top). In `tests/test_playback.py`, change the clock assertions: `estimated_seconds` at the last frame equals `route.seconds + len(route.segments) * config.CAPTURE_DWELL_S` (approx), and the dwell check stays.

- [ ] **Step 2: routes**

`Route.seconds` property = `sum(s.seconds for s in segments)`. `OptimalRouteSource` with `name = "Shortest time"` calling `tour.plan_optimal(world, generate_objectives(world))`, timed like greedy. `SOURCES = (GreedyRouteSource(), OptimalRouteSource())`.

- [ ] **Step 3: playback clock uses the time model**

In `Playback.__init__`, accumulate `seconds` per frame alongside `distance_cm`: a straight cell adds `cost.TIME_SECONDS.straight(1, cell_size)`, a turn adds `cost.TIME_SECONDS.turn(move.turn, cell_size) / (m + 1)` per frame. Add `Frame.seconds: float` (cumulative, dwell repeats). `seconds_at(i)` becomes `frames[i].seconds + captures_upto(i) * CAPTURE_DWELL_S`. Distance stays for the length readout.

- [ ] **Step 4: panel**

Route section: add a row "Estimated time" showing `clock(route.seconds)` under "Total length". The transport clock already reads `estimated_seconds`. Selftest: after the first plan/play sequence, set `app.source_var` to "Shortest time", call `app.on_source()` then `app.on_plan()`, assert `app.route.source_name == "Shortest time"`, play briefly.

- [ ] **Step 5: docs**

SPEC "Why": B.3 is now covered; "Scope" and the Route panel paragraph mention both sources; the plan's Task 9 note that B.3 needs the optimiser is stale. README Simulator section first line: B.1, B.2 and B.3.

- [ ] **Step 6: verify**

Tests green; smoke 5/5; `--selftest` exit 0 (sandbox off); `--snapshot` of testdata 02 with the optimal source renders (add `--source` to `__main__`? No: keep the CLI as is; `snapshot.render` already takes `source_name`, so a one-off `python -c` render with `source_name="Shortest time"` is enough for the visual check).

---

### Task 5: make the search fast enough for the matrix

Added 2026-09-03 after Task 2 measured `leg_matrix` at 16 s for four obstacles (about 3.3 s per
`reach()`), all inside `turn.__curve`, which recomputes a midpoint circle and checks each cell
with a Python call on every expansion.

**Files:**
- Modify: `algorithm/pathfinding/search/turn.py`, `algorithm/pathfinding/world/world.py`
- Test: `algorithm/tests/test_turn_cache.py`

**Interfaces:** unchanged. `turn(world, start, instruction)` returns exactly the same list of
vectors as before for every input (the arc cells and end pose), or `None`.

- [ ] **Step 1: capture a baseline before touching anything**

Plan testdata 01, 02, 03 with `search()` and dump `[(s.image_id, s.cost, [(v.direction.value, v.x, v.y) for v in s.vectors], [str(i) for i in s.instructions]) for s in result.segments]` plus the unreachable list to `$TMPDIR/baseline-turn.json`. Also time `search()` on 02 and `reach()` from the start pose on 02 (three runs, take the median) and record the numbers.

- [ ] **Step 2: failing tests**

`tests/test_turn_cache.py`: (a) for every one of the 16 `(direction, instruction)` cases, `turn()` on an empty-arena world from a pose in the middle returns a non-None path whose first cell and end pose match the values obtained by calling the ORIGINAL algorithm (keep a private reference copy of the old `__curve` in the test file for this comparison, named `reference_curve`, copied verbatim from today's `turn.py`); (b) a turn that clips an obstacle returns `None`, same as the reference; (c) the cache does not leak across worlds with different robot sizes (build two worlds with 31 cm and 21 cm robots and check the arcs differ). Plus a test that re-plans testdata 01-03 and compares against `$TMPDIR/baseline-turn.json` written in step 1 (skip if the file is missing).

- [ ] **Step 3: implement**

In `turn.py`: compute each of the 16 cases' arc as OFFSETS relative to `start` once per
`(direction, instruction, turning_radius, offset, robot north/east/south/west lengths)` and cache
them in a module-level dict; `turn()` then translates the offsets by `start` and validates all
cells in one numpy operation. In `world.py`, add
`World.contains_all(xs: np.ndarray, ys: np.ndarray) -> bool` that bounds-checks and indexes
`self.grid[xs, ys].all()`. Keep `__curve`'s output order (a, b interleaving and the appended end)
identical so `_ordered_arc` and every downstream consumer see the same list.

- [ ] **Step 4: verify**

Tests green; smoke 4/4 byte-identical output; the baseline comparison test passes; report the
before/after timings for `search()` on 02 and `reach()` on 02. Target: `reach()` under 1 s and
`search()` under 0.6 s on 02. If the target is missed, report the profile rather than widening it.

---

### Task 6: integer-state search core

Added 2026-09-04 after Task 5 measured `reach()` at 2.8 s and `search()` at 1.6 s with 65% of the
time in `segment.py`'s expansion machinery (dict lookups, tuple heaps, a `Vector` per state).

**Files:**
- Modify: `algorithm/pathfinding/search/segment.py` (internals only)
- Test: `algorithm/tests/test_segment_fast.py`

**Interfaces:** unchanged. `segment(world, initial, objectives, weights)` and
`reach(world, sources, targets, weights)` return exactly what they return today, including
tie-breaking, so every existing test and `smoke.py` output stays byte-identical.

- [ ] **Step 1: baseline**

Before editing, dump for testdata 01, 02, 03, 04: greedy `search()` segments (image_id, cost,
seconds, vectors as tuples, instructions as strings), and `reach()` from the start pose under
`cost.TIME_SECONDS` (obstacle image_id -> cost), to `$TMPDIR/baseline-search.json`. Time
`search()` on 02 and `reach()` on 02 (median of 3).

- [ ] **Step 2: failing test**

`tests/test_segment_fast.py`: loads the baseline file (skip if missing) and asserts equality after
the rewrite; plus a timing sanity test that `reach()` on 02 completes under 1.5 s (skip on CI-like
slowness only if an env var `MDP_SKIP_TIMING=1` is set).

- [ ] **Step 3: implement**

State index `idx = (rank(direction) * size + x) * size + y` with `rank` following the current
`Vector` ordering (Direction is a `str` enum, so alphabetical: EAST 0, NORTH 1, SOUTH 2, WEST 3),
so `(cost, idx)` heap tuples break ties exactly as `(cost, Vector)` did. Arrays: `costs`
(float64, inf), `parent` (int32, -1), `parent_move` (small int code + a side table of the actual
`Turn`/`Move` objects created lazily only when a state is first improved, or reconstruct moves at
trace time from the (state, code) pair). Goal membership: one `int8` array over states mapping to
the target obstacle's ordinal, built once per call from the goal sets. Neighbour generation keeps
the exact order (four turns in `TurnInstruction` order, then FORWARD then BACKWARD for each chunk
length) and the exact legality checks (turn arcs via the Task 5 cache; straights via
`World.contains_all` over the chunk). Build `Vector` objects only in `__trace` and for the
returned path. Keep `segment()` returning `(obstacle, cost, [(Vector, move|None), ...])` and
`reach()` returning `{obstacle: cost}`.

- [ ] **Step 4: verify**

Baseline test green; full suite green; smoke 4/4 byte-identical stdout except plan times; report
before/after timings. Target: `reach()` under 1.0 s, `search()` under 0.6 s on 02. If a target is
missed, report the profile.
