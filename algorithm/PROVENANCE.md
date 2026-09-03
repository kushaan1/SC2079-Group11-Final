# Provenance and design decisions — `algorithm/`

Every module in this directory carries the header:

```python
# Derived from Pante/SC2079 (AY2023 S2, Group 14). See algorithm/PROVENANCE.md
```

This file is what that points at. It records where the code came from, what was wrong with the
original, and the decisions taken since — so that a number or a design choice can be questioned
later without anyone having to reconstruct the reasoning from scratch.

## Where it came from

The planner is a **rewrite** of the pathfinding service from `Pante/SC2079` (AY2023 Semester 2,
Group 14), a prior-year MDP team. Their code was read, their good ideas were kept, and their
defects were fixed; **none of their code is vendored into this repository** — `AGENTS.md` §9.1 puts
our own work in `algorithm/` and keeps theirs outside the tree entirely.

> **"The reference", throughout the code comments, means that prior-year implementation** — not
> anything in this repository. It is not checked in here and does not need to be; where a comment
> says the reference did something wrong, this file records what and why.

What was worth taking, and is now here:

- **Goal-pose *sets* per obstacle** — a standoff band crossed with a lateral tolerance, rather
  than one exact target pose. This is the single highest-value idea in their design: it turns a
  brittle exact-arrival problem into a robust one.
- **Multi-goal single search**, so "nearest unvisited obstacle" falls out of the search frontier
  measured in true path cost, not Euclidean distance.
- **Obstacle inflation precomputed into the grid** at world construction, so the search can treat
  the robot as a single point.
- **Per-direction turning radii** — the asymmetry between forward-left, forward-right,
  backward-left and backward-right is real and large.
- **Instruction compression** into `{move, amount_cm}` plus bare turn tokens.
- **Request replay capture** and an **ASCII grid dump** for debugging.
- The **OpenAPI contract shape** for the RPi boundary — see `docs/protocols/algorithm-service.md`.

## The six defects fixed in the rewrite

These were found by auditing their code and are listed because each one is a trap worth not
re-introducing.

**Fix 1 — their code does not run at all.** In `search/turn.py`, `__curve` was declared with 5
parameters while all 16 call sites passed 6, and the body referenced an undefined name `end`. The
first `turn()` call raises `TypeError`, so their planner never produces a single segment. The
missing `end: Vector` parameter is restored here.

**Fix 2 — `Entity.centre` was a half-extent, not a centre.** It omitted the `south_west` offset,
which made `south_length` and `west_length` negative for any entity not anchored at the origin,
silently corrupting grid inflation, goal-pose generation and every turn. Only a robot starting at
`(0, 0)` hid the bug. Blast radius is `Robot` only — no obstacle's `.centre` or `*_length` is read
anywhere — so it changes behaviour exactly when the robot does not start at the origin.

**Fix 3 — compounding lateral tolerance.** In `world/objective.py`, `offset += 2` sat *inside* the
gap loop, so for an obstacle touching the arena boundary the tolerance accumulated (+2, +4, +6, …)
across iterations instead of applying once. Hoisted out of the loop.

**Fix 4 — `image_id` range rejected legal images.** They asserted `1 <= image_id < 36`, which
rejects IDs 36–40: the four arrows and the stop marker, all of which the competition uses. Bounds
now come from `config.IMAGE_ID_MIN`/`IMAGE_ID_MAX` and a violation raises a `ValueError` naming
the offending ID rather than a bare `assert` that vanishes under `python -O`. The accepted range is
now **1–40**, not 11–40 — see "`image_id` is an obstacle id" below.

**Fix 5 — every hardcoded physical number moved into `config.py`.** Arena size, standoff band,
lateral tolerance, obstacle clearance, boundary adjustment, the four turning radii and the straight
chunk length were all inline literals. `AGENTS.md` §9.2 rule 1 requires them in one place.

**Fix 6 — one turn branch built its arc 12 cm off.** In `search/turn.py`, the
`(EAST, BACKWARD_RIGHT)` case passed the robot-extent term to `__curve`'s circle centre instead of
to the end pose; the other 15 branches do the opposite, and its mirror `(EAST, BACKWARD_LEFT)`
shows the intended form. The arc was therefore collision-checked in the wrong place and left the
robot 12 cm from where the planner recorded it, which the search then had to drive back out of:
correcting it makes the rear-point model exact for all 16 branches and shortens the testdata
routes by 15% (testdata 02 total cost 1083 to 919).

Two defects of theirs were deliberately **not** reproduced and are worth knowing about: their
`segment.py` defines a `__heuristic` that is never called (so the search is really Dijkstra, not
A\*), and their `RPi/Communication/stm.py` hardcoded an absolute path containing their own
username. Neither exists here; the dead heuristic was deleted on 2026-09-04 when the search core
moved to integer state indices, which made it unnecessary.

## Design decisions

Recorded because each was a real fork in the road, not an obvious default.

**Config is read at call time, never bound at import.** Planner modules do `import config` and read
`config.X` *inside* function bodies. Never `from config import X` at module level. This is what lets
a tool or a test vary the standoff band at runtime and re-invoke the real placement code, instead of
reimplementing the geometry. Breaking this rule silently freezes any sweep at the first value it
saw.

**The standoff band is inclusive on both ends.** It means literally what `config` names it — the
closed interval `[STANDOFF_MIN_CM, STANDOFF_MAX_CM]`. The original iterated a half-open range and
then passed `gap + 1`, so a config reading 25–30 actually produced 26–30 cm. Standoff is the number
a four-team meeting negotiates; it must not misreport itself by a centimetre.

**`ROBOT_FOOTPRINT_CM` is 31, not 30.** 30 cannot be planned: the turning geometry needs the robot's
centre cell to be genuinely central, which holds only when the footprint in cells is odd, so an even
footprint is silently bumped by one. A robot declared as 30 cm has always been planned as 31. 31 is
that honest, and changes nothing.

**Unplannable obstacles are structured data, not a `print()`.** `SearchResult.unreachable` and the
`unreachable` response field exist because an obstacle that silently vanishes from a plan is lost
points with no diagnostic. `segments` and `unreachable` partition the obstacles: every obstacle
appears in exactly one, and no `image_id` appears in both. That is enforced, not merely intended.

**`NO_OBJECTIVES` and `NO_PATH` are not interchangeable, and neither is `NO_OBJECTIVES` a single
cause.** Measured, because the two remedies are *opposite*:

- *Wall clearance* — the obstacle faces a wall it sits too close to, so its poses land outside the
  arena. Widening the standoff band **never** rescues this (tried 25–45, 25–60, 25–90; all failed).
  Only **lowering** `STANDOFF_MIN_CM` does.
- *Neighbour crowding* — a nearby obstacle's inflated keep-out swallows every pose. This inverts:
  it is rescued by **raising** `LATERAL_TOLERANCE_CM`, or by a band wide enough to clear the
  neighbour.

`World.contains()` cannot report which of the two fired, so the code says so plainly rather than
guessing. To tell them apart, plan the obstacle **on its own**: still no pose means the wall; poses
alone but none in company means a neighbour. So "just tune the standoff" is wrong advice for half of
these cases.

**Duplicate `image_id`s are rejected with 422 at the HTTP boundary.** Without this the partition
guarantee above is falsifiable while its own check still passes — image 11 could appear in both
lists and a caller could not tell whether it was being visited. Two value-identical obstacles also
collapse into a single dictionary key and one is lost outright. No legitimate arena is refused,
since two obstacles cannot carry the same image.

**A domain `ValueError` maps to 422, not 500.** The published request schema allows `image_id`
`minimum: 1` with no upper bound while the domain allows 1–40, so an ID above 40 satisfies one and
violates the other. The
schema was deliberately **not** tightened — it is the contract the RPi generated a client from — so
the narrower rule is enforced a layer down and mapped to a clean 422. Same for `AssertionError`
raised while building the world: the planner states its input preconditions as bare asserts, so on
that path they are request validation and a 500 would blame the RPi for their own request. The
`ValueError` that `search()` raises for a non-accounting objective set is *our* bug and stays a 500.
**Consequence: never run the service under `python -O`**, which strips asserts.

**`image_id` is an obstacle id, so the accepted range starts at 1.** In Task 1 the image on an
obstacle is unknown until CV reads it, so the field cannot be an image ID on the way in — the
tablet numbers the obstacles 1–8 and sends that number, and the planner only echoes it back.
Rejecting 1–10 therefore rejected every real run, so `config.IMAGE_ID_MIN` is 1 and the range
1–40 accepts both obstacle numbers and the real image IDs a hand-written arena may use.

**Error bodies use pydantic's key names** — `type`, `loc`, `msg` — so every 422 has one shape
whether it came from schema validation or from our own checks. See
`docs/protocols/algorithm-service.md`.

**The route is optimised against a time model with placeholder constants, by exhaustive
branch-and-bound up to 9 obstacles.** Three choices, taken together on 2026-09-03:

- *Time, not distance.* `cost` stays centimetres, but the optimiser minimises
  `straight_cm / ROBOT_SPEED_CM_S + turns × TURN_TIME_S` (`pathfinding/cost.py`). At the current
  30 cm/s and 3 s per quarter-turn a turn is worth 90 cm of straight, so the shortest route and
  the quickest route are genuinely different routes. **Both constants are guesses until STM
  measures them**, which is a real limitation and not a rounding error: change them and the
  chosen order can change. It is still the right objective — the competition scores time — and it
  is the same model the simulator's clock uses, so the panel and the planner cannot disagree.
- *Exhaustive branch-and-bound, not Held–Karp.* Held–Karp was the plan; the algorithms deck's
  own line, "we can afford the cost of the exhaustive search", is right at this size and the
  exhaustive version is far easier to keep correct. Task 1 fields at most 8 obstacles, and
  `tour.MAX_EXHAUSTIVE = 9` is headroom rather than a compromise — above it the order falls back
  to greedy on the matrix. What is enumerated is orders by ascending *matrix* bound; what is
  compared is the **real re-planned route**, because a matrix leg is priced from anywhere in an
  obstacle's goal-pose set while the robot drives it from the one pose it arrived at. Trusting
  the matrix directly was measured 7.2% *slower* than plain greedy on
  `testdata/04-five-obstacles.json`, which is what forced the re-planning. `tour.MAX_REPLANS = 8`
  caps how many candidates are re-planned; hitting it is logged, and means the answer is the best
  order tried rather than a proven optimum.
- *Optimal is the HTTP default, behind an additive `strategy` field.* Greedy's real route is one
  of the candidates, so optimal never photographs fewer obstacles and, at equal count, is never
  slower; a caller loses nothing by not knowing the field exists — which matters, because the
  RPi's client was generated before it did. Greedy stays selectable because reproducing an old
  plan needs the old planner.

## Known gaps

Carried here so they are not rediscovered as surprises. The user-facing version is in
[`README.md`](README.md) under "Known limitations".

1. **The planner cannot solve arenas at the competition's legal minimum obstacle spacing.** It
   reserves `footprint/2 + clearance` = 21 cm per side, so **42 cm of combined keep-out**, while the
   rules guarantee only **30 cm**. Measured: gaps of 30/35/40/41/42 cm give a zero-width corridor;
   45 cm gives 3 cells. The real chassis is ~18.6–18.8 cm wide and physically fits a 30 cm gap with
   ~11 cm to spare — it is the conservative *planning* footprint that does not. Target for the fix:
   `ROBOT_FOOTPRINT_CM + 2 × OBSTACLE_CLEARANCE_CM ≤ 28`.
2. **The turning radii are not ours.** 39/40/37/39 cm are the prior-year team's measurements on
   *their* car. Radius also grows with speed. These need re-measuring on our chassis at competition
   speed; every plan is only as true as they are.
3. **The standoff band is a placeholder.** 25–30 cm, inherited. The course documents state the
   camera optimum three mutually inconsistent ways. CV needs to pick one against the real lens.
4. **The time model's constants are guesses.** Visiting-order optimisation is done (2026-09-03,
   `pathfinding/search/tour.py`): `strategy: "optimal"` is the HTTP default and satisfies
   checklist item B.3. `ROBOT_SPEED_CM_S` (30) and `TURN_TIME_S` (3.0) are placeholders until STM
   measures them, and the chosen order depends on their ratio. Held–Karp was replaced by
   exhaustive branch-and-bound over real re-planned routes with the leg matrix as the lower bound
   (see "Design decisions"); the matrix still costs **9 searches at N=8, not 56**, because one
   multi-source multi-goal search yields a whole row. Caps: `MAX_EXHAUSTIVE = 9` obstacles, then
   greedy on the matrix; `MAX_REPLANS = 8` candidate orders re-planned, logged when it binds.
5. **No Dubins implementation.** Quiz-assessed.
6. **B.3 is demonstrable, under placeholder timings.** Since 2026-09-04 `simulator/routes.py`
   has `OptimalRouteSource` ("Shortest time") beside the greedy one and the Route panel shows
   "Driving time", so B.1, B.2 and B.3 are all shown from the one window. What it demonstrates
   is shortest under gap 4's guessed constants. Planning runs on the UI thread behind a
   "Planning..." button (gap 8), deliberately unthreaded.
7. **The planner's geometry has no unit tests.** Since 2026-09-03 `tests/` also covers the cost
   model, the leg matrix, the visiting-order search and the HTTP surface, but goal-pose
   generation, the turn primitives and the grid search are still pinned only by `smoke.py` — a
   regression anchor with baselines captured from this planner, not an independent oracle.
8. **The search is Dijkstra, knowingly.** Latency on a 4-obstacle arena at 1 cm cells is about
   0.07 s greedy and under 1 s optimal (2026-09-04, after the integer-state search core and the
   turn-arc cache), so a heuristic is not needed.

## Attribution

The planner rewrite, the HTTP service and this document are the algorithms subsystem's own work.
The upstream lineage is `Pante/SC2079` as described above; keep the per-module provenance header on
any file that traces back to it. `AGENTS.md` §9.2 rule 7 requires work to be attributable, and
§9.1 keeps the upstream tree outside this repository.
