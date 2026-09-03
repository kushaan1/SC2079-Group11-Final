# Shortest-time route optimiser

Status: approved 2026-09-03. Owner: algorithms. Satisfies checklist B.3 ("shortest-time
Hamiltonian path") and makes the real Task 1 run faster.

## What it does

Given the arena, choose the visiting order and the leg paths that minimise **estimated driving
time**, not greedy nearest-first. Time is modelled as

    seconds = straight_cells * cell_size / ROBOT_SPEED_CM_S  +  turns * TURN_TIME_S

with both constants in `config.py` (STM placeholders until measured). The same model drives the
simulator clock, so the panel's estimate and the optimiser agree.

## Method

1. **Time-costed search.** The existing grid search (`segment.py`) gains a pluggable cost model:
   distance (today's behaviour, kept for greedy) or time. A new `reach()` runs one Dijkstra from a
   *set* of source poses and returns the cheapest time into every target pose set.
2. **Leg-cost matrix over pose sets.** Nodes are the start pose and each obstacle's whole goal-pose
   set. One `reach()` per node gives row `i`: N+1 searches at N obstacles, about 5 to 9 s at 8.
3. **Ordering.** Exhaustive depth-first search over permutations with branch-and-bound on the
   matrix (the algorithms deck: "we can afford the cost of the exhaustive search"). Above 9
   obstacles fall back to greedy on the matrix. Obstacles with no finite entry are dropped as
   `NO_PATH` before the tour; if no complete tour exists, drop the obstacle with the fewest finite
   entries and retry (largest feasible subset).
4. **Real legs.** Re-plan each leg in order from the robot's actual end pose with the time-costed
   single-goal search. A leg that fails from the real pose is `NO_PATH`; the tour continues.
   `segments` and `unreachable` still partition the obstacles.

## Interfaces

- `pathfinding/cost.py`: `Weights` protocol (`turn(TurnInstruction) -> float`,
  `straight(cells: int) -> float`), `DISTANCE_CELLS` and `TIME_SECONDS` implementations,
  `seconds(moves, cell_size) -> float`.
- `pathfinding/search/segment.py`: `segment(world, initial, objectives, weights=DISTANCE_CELLS)`
  (initial may be one pose or an iterable of poses); `reach(world, sources, targets, weights)
  -> dict[Obstacle, float]`.
- `pathfinding/search/search.py`: `Segment.cost` stays centimetres (now computed from the moves,
  not the search weight) and gains `seconds: float`; `search()` stays greedy.
- `pathfinding/search/tour.py`: `plan_optimal(world, generated) -> SearchResult`; also exposes
  `leg_matrix()` and `best_order()` for tests.
- HTTP: request gains `strategy: "greedy" | "optimal"` (default optimal, additive); each segment
  gains `seconds` (verbose only). Protocol doc and `openapi.json` updated.
- Simulator: `OptimalRouteSource(name="Shortest time")` beside greedy; `Route.seconds`; Route panel
  shows "Estimated time"; the playback clock uses `cost.seconds`, so turns cost time.

## Not doing

2-opt on top of exhaustive (pointless at N <= 9); Dubins; parallel searches; caching between
requests; a centred-pose preference (wait for CV's off-centre tolerance).

## Verification

- `best_order` on a hand-built 4-node matrix returns the known optimum; with an infinite edge the
  obstacle is dropped; above the cap it falls back to greedy order.
- `reach()` from the start pose equals `segment()`'s single-goal cost for each obstacle on
  testdata 02.
- `plan_optimal` on testdata 02: same partition as greedy, total `seconds` <= greedy's; on
  testdata 03: obstacle 13 still `NO_OBJECTIVES`.
- HTTP: `strategy` omitted -> optimal; `"greedy"` -> the old order `[12, 11, 14, 13]`; both 200.
- smoke.py gains an optimal run of the 4-obstacle arena.
- Simulator selftest switches source to "Shortest time", plans, plays.
