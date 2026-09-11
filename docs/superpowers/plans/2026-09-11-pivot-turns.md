# Pivot turns — implementation plan

Spec: `docs/superpowers/specs/2026-09-11-pivot-turns-design.md` (read it; it is the authority).
Branch: `kejun-experimental-algo`, in place. Repo root has `algorithm/` as the package root.

Run tests as: `cd algorithm && ./.venv/bin/python -m pytest tests -q`

## Global Constraints

- **Baseline is `137 passed, 1 skipped`.** It may only go up. With `PIVOT_TURNS=False` no
  existing test may change its result, in either `DIAGONAL_HEADINGS` mode.
- **`config.py` imports nothing from the project.** Consumers read `config.X` inside function
  bodies at call time, never `from config import X` at module level. This is the rule that makes
  the constants hot-swappable when STM returns measurements; it is stated at the top of
  `config.py` and is load-bearing.
- Every new config constant carries a provenance line:
  `# SOURCE: <team> | measured|assumed|placeholder | <note>`.
- **Do not touch `docs/algorithms-todo.md`** — it is modified and uncommitted in the working
  tree and belongs to the user.
- Match the surrounding code's style: these modules carry long explanatory docstrings that say
  WHY, not what. New code is expected to do the same.
- **Never run `git commit`, `git push`, or anything that triggers GPG signing.** The user's
  commits are signed and they commit by hand. Leave your work in the working tree; the
  controller snapshots it for review. Staging with `git add` is fine. This is not negotiable
  and applies to every task.

## Task 1 — Config constants and the pivot instruction type

Files: `algorithm/config.py`, `algorithm/pathfinding/search/instructions.py`,
`algorithm/tests/conftest.py`, new `algorithm/tests/test_pivot.py`.

1. Add to the "Motion primitives" section of `config.py`, each with a provenance line marked
   `placeholder` and a note pointing at the STM owner:
   - `PIVOT_TURNS = False` — whether the search may rotate on the spot. Independent of
     `DIAGONAL_HEADINGS`; document that the two compose.
   - `PIVOT_TIME_S = 2.0` — seconds for one 45 degree pivot. Note it is NOT measured; the STM
     owner supplied 2.0 as a working figure on 2026-09-11.
   - `PIVOT_STROKES_PER_45 = 2` — strokes per 45 degrees, one forward and one back. Must be
     even. Note that 2 minimises drift at the current radii (3.5 cm) and that more strokes
     shrink the swept box but increase drift, because drift is driven by the
     forward/backward radius asymmetry.
2. Add to `instructions.py`, as a SEPARATE enum — do NOT add members to `TurnInstruction`; the
   spec explains why that would silently change the four-heading planner:

   ```python
   class PivotInstruction(str, Enum):
       PIVOT_LEFT_45  = 'PIVOT_LEFT_45'
       PIVOT_RIGHT_45 = 'PIVOT_RIGHT_45'
       PIVOT_LEFT_90  = 'PIVOT_LEFT_90'
       PIVOT_RIGHT_90 = 'PIVOT_RIGHT_90'
   ```
   with `degrees` (45 or 90, derived from the suffix), `clockwise` (RIGHT is clockwise), and
   `strokes()` returning `config.PIVOT_STROKES_PER_45 * degrees // 45`, read at call time.
   Add `@dataclass class Pivot: pivot: PivotInstruction; vectors: list[Vector]` alongside
   the existing `Turn` and `Move`.
3. In `conftest.py`, register a `pivots` marker beside the existing `diagonals` one and extend
   the autouse fixture so `config.PIVOT_TURNS` is monkeypatched to `"pivots" in
   request.keywords`. Follow the existing fixture's docstring style — say why.
4. Create `tests/test_pivot.py` with `pytestmark = pytest.mark.pivots` and tests for the enum:
   degrees and clockwise for all four members, and that `strokes()` reads config at call time
   (monkeypatch `PIVOT_STROKES_PER_45` and assert the result changes).

TDD: write each test, watch it fail, then implement. Do not write production code first.

## Task 2 — Pivot geometry

File: new `algorithm/pathfinding/search/pivot.py`. Tests into `algorithm/tests/test_pivot.py`.

Implement `pivot(world, start, instruction) -> list[Vector] | None` mirroring
`pathfinding/search/turn.py`'s structure: a module-level cache of shapes-as-offsets, a bounding
box rejection, one `world.contains_all` call, then translation to `start`.

Read the spec's "Geometry" section for the exact per-stroke derivation — implement it verbatim.
Key points the spec explains and you must honour:

- A right (clockwise) pivot alternates locks `FORWARD_RIGHT`, `BACKWARD_LEFT`; a left pivot
  alternates `FORWARD_LEFT`, `BACKWARD_RIGHT`. Both locks in a pair swing the nose the same way
  — that is the whole trick, and `turn.py`'s `_ANTICLOCKWISE` tuple is where it is already
  written down.
- Intermediate headings are NOT `Direction` members (22.5 degrees at the default stroke count),
  so the derivation works in continuous compass degrees and only resolves to a `Direction` at
  the start and end.
- `lead` and `radius` are computed exactly as `turn.__geometry` computes them, from
  `config.TURN_PIVOT_OFFSET_CM` and `config.TURN_RADIUS_CM`, at call time.
- Cache key must include everything the shape depends on — start direction, instruction, both
  radii, the pivot offset, the stroke count, and the robot's four extents — so a runtime config
  change lands on a fresh key rather than reusing a stale shape.
- Drop consecutive duplicate cells so the result is a path, not a set. Append the end pose; do
  NOT collision-check it (matching `turn()`).

Tests (spec's test plan items 1-3):
1. A pivot swings the heading by its own size, from every `Direction`, for all four
   instructions.
2. A pivot barely moves the robot: assert the centre displacement is under 15 cells for every
   heading and instruction. State in the docstring that a 90 degree `FORWARD_RIGHT` arc moves
   the centre (52, 28) cm, so this is the property that distinguishes a pivot from a turn.
3. Two 45 degree pivots land where one 90 degree pivot does, same handedness, one cell of
   rasterisation slack. Model the docstring on `test_diagonals.py`'s
   `test_two_45_degree_turns_land_where_one_90_does` — say what would fail if the geometry
   traced the wrong radius or stopped at the wrong point.

## Task 3 — Cost model

File: `algorithm/pathfinding/cost.py`. Tests into `algorithm/tests/test_pivot.py`.

- Add `pivot(self, instruction, cell_size=1) -> float` to the `Weights` protocol and both
  implementations.
- `_Time.pivot` returns `config.PIVOT_TIME_S * instruction.degrees / 45`, read at call time.
  Document the economics in the docstring, as `_Time.turn` already does for the 45 degree turn:
  a pivot is dearer than the equivalent arc (2.0 s vs 1.5 s at 45 degrees) and gains zero
  ground, so the search only reaches for it where the arc's displacement is unwanted.
- `_Distance.pivot` returns the ground the wheels cover: the sum of the stroke arc lengths,
  `(strokes / 2) * radians(theta) * (R_forward_lock + R_backward_lock)` in cells, where
  `theta = degrees / strokes`. Use the same lock names the geometry uses.
- Add a `Pivot` branch to `move_cost`.

Tests (spec's test plan item 4): a 45 degree pivot costs `PIVOT_TIME_S`; a 90 costs twice a 45;
both assert against a monkeypatched `PIVOT_TIME_S`, not the literal 2.0, so the test proves the
call-time read rather than the default value.

## Task 4 — Search integration and rotation clearance

Files: `algorithm/pathfinding/search/segment.py`, `algorithm/pathfinding/search/search.py`.
Tests into `algorithm/tests/test_pivot.py`.

This is the task the additive guarantee rests on. Read the spec's "Clearance" and "Search
integration" sections in full before starting.

1. In `_tables`, build ONE eroded copy of `free_cells` per search, for pivot legality only:
   `delta = ceil(half_extent * (sqrt(2) - 1))` where `half_extent = world.robot.north_length`.
   Erode by an L2 disc of radius `delta`. The spec explains why eroding the already-inflated
   grid by a disc is exactly the right condition, and why dilating each pivot path instead
   would be an order of magnitude more expensive. Ordinary turns and straights keep reading
   `free_cells` unchanged.
2. Gate pivot moves on `config.PIVOT_TURNS`, read at call time. Emit a pivot only when its END
   heading is in `ranks` — this is what makes 45 degree pivots appear exactly when
   `DIAGONAL_HEADINGS` is on, with no extra configuration.
3. **Append pivot move codes AFTER the straight chunks**, leaving every existing code value
   untouched. `_Search.__move` decodes `code <= len(_TURNS)` as a turn,
   `<= len(_TURNS) + len(chunks)` as a straight, else a pivot. Preserving the order preserves
   every existing tie-break, per the `_tables` docstring.
4. Fold pivot path and end offsets into the `pad`/`span` computation, and ensure
   `span >= delta` so the eroded array's reads stay in bounds.
5. `search.Segment.compress` gains a `Pivot` case in its match: append the instruction, extend
   the vectors, append the move. Note its `instructions` type annotation widens.

Tests (spec's test plan items 5-7):
5. **The additive guarantee.** With `PIVOT_TURNS=False`, plan a testdata world with
   `DIAGONAL_HEADINGS` both False and True and assert the resulting segments are identical to
   planning the same world with the pivot code path fully disabled — the instruction lists and
   the per-segment costs, not just the segment count.
6. A pivot is refused where the extra rotation clearance is not available but a straight move
   at the same cell is legal. Construct the world deliberately; assert `pivot(...) is None`
   there and not-None in open space at the same heading.
7. The payoff: a world where an obstacle has no route without pivots and gains one with them.
   If no such arrangement can be built from the existing testdata, build a small one in the
   test itself and say in the docstring what it demonstrates.

Run the FULL suite. `137 passed, 1 skipped` plus your new tests, nothing changed.

## Task 5 — Wire contract

Files: `algorithm/pathfinding_controller.py`, `docs/protocols/openapi.json`,
`docs/protocols/algorithm-service.md`. Tests into `algorithm/tests/test_service.py`.

- Widen `Segment.instructions` and `PathfindingResponseSegment.instructions` to include
  `PivotInstruction`. Additive only — a new member of an existing union, exactly as
  `FORWARD_LEFT_45` was. **Requests are unaffected**: `CardinalDirection` does not change.
- Regenerate `docs/protocols/openapi.json` by whatever mechanism the repo already uses (look
  for it; `app.py` and the existing deviations list are the place to start).
- Add a deviation note to `docs/protocols/algorithm-service.md` in the style of the existing
  numbered deviations, recording that a response instruction may read `PIVOT_LEFT_45` etc. when
  `PIVOT_TURNS` is on, and that the token strings are placeholders pending the RPi and STM
  owners.
- A test that a planned route containing a pivot serialises and round-trips through the
  response model.

## Task 6 — Simulator playback

Files: `algorithm/simulator/playback.py` (and `painters.py` only if it is genuinely needed).
Tests into `algorithm/tests/test_pivot.py`.

`playback.py` already sweeps the heading across a turn's arc because arc cells all carry the
POST-turn heading (its module docstring explains this). Give `Pivot` the same treatment: sweep
the heading evenly across the pivot's vectors. The heading through a shuffle turn is monotonic —
every stroke swings the nose the same way — so an even sweep is faithful; say so in a comment.

Test (spec's test plan item 8): plan a world that produces a pivot with the flags on, build a
`Playback`, and assert frames exist at headings strictly between the pivot's start and end
heading. Model it on `test_diagonals.py::test_playback_rotates_through_a_45_degree_turn`,
including its lesson: assert something that could actually fail.
