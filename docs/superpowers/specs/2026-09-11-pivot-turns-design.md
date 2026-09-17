# Pivot turns (turn on the spot) — design

Date: 2026-09-11. Branch: `kejun-experimental-algo`.

## The manoeuvre

The car is Ackermann-steered (AGENTS.md §2) and has no zero-radius solution. What it can do is
a **shuffle turn**: full lock forward, full lock backward the other way, repeated. Both strokes
swing the nose the SAME way — `turn.py` already states this:

```python
_ANTICLOCKWISE = ('FORWARD_LEFT', 'BACKWARD_RIGHT')
```

`FORWARD_RIGHT` and `BACKWARD_LEFT` are both absent from that tuple, so both rotate clockwise;
their translations point opposite ways and largely cancel. The residual is a few centimetres.

- A **right (clockwise)** pivot alternates `FORWARD_RIGHT`, `BACKWARD_LEFT`.
- A **left (anticlockwise)** pivot alternates `FORWARD_LEFT`, `BACKWARD_RIGHT`.

Measured against the current placeholder radii (40/37 cm, lead 12 cm), for a 45 degree pivot:

| strokes | deg/stroke | net drift | swept box |
|---|---|---|---|
| **2** | **22.5** | **3.5 cm** | **51 x 58 cm** |
| 4 | 11.25 | 6.4 cm | 53 x 53 cm |
| 6 | 7.5 | 7.3 cm | 53 x 51 cm |

Two strokes is the default: least drift, and the swept box is no worse in the dimension that
matters.

**Where the drift comes from — corrected 2026-09-11.** An earlier draft of this spec said the
drift "is dominated by `R_forward != R_backward`". That is wrong, and Task 2's implementer
caught it: the LEFT pivot uses `FORWARD_LEFT` 39 and `BACKWARD_RIGHT` 39 — equal radii — and
still drifts 3.2 cm. Re-derived:

| case | drift per 45 degrees |
|---|---|
| 40/37 unequal, lead 12 (the right pivot) | 3.52 cm |
| 40/40 matched, lead 12 | 3.09 cm |
| 40/40 matched, lead 0 | 6.09 cm |
| 50/20 extreme gap, lead 0 | 12.66 cm |

The drift is **inherent to the manoeuvre**: each forward/backward pair turns about two
different circle centres, so the pair does not close. Matching the forward and backward radii
buys about 12% at our numbers; only a large radius gap makes asymmetry the dominant term.

What survives from the original claim, and is the part that matters: the drift is
**systematic, not noise**, so the planner can model it exactly. Do NOT tell the STM owner that
better-matched radii will make it go away.

## Goals

1. A pivot primitive the search may use, priced in seconds, behind its own config flag.
2. **Additive.** With the flag off, the planner is byte-for-byte what it is today, in both the
   four-heading and eight-heading modes.
3. **Hot-swappable.** When the STM owner returns real measurements, the only file that changes
   is `config.py`. Geometry, clearance and cost are all derived from those constants at call
   time, never hand-written.

## Non-goals

- Changing `DIAGONAL_HEADINGS` or anything it controls.
- Fixing the pre-existing diagonal-pose clearance gap (see "Known gap" below).
- Deciding the final STM wire token. A placeholder is used and is one enum edit to change.

## Config constants

All new, all in the "Motion primitives" section of `config.py`, all `placeholder`-tagged in the
existing provenance format, all read at CALL TIME (never bound at import).

| Constant | Default | Meaning |
|---|---|---|
| `PIVOT_TURNS` | `False` | Whether the search may pivot. Independent of `DIAGONAL_HEADINGS`. |
| `PIVOT_TIME_S` | `2.0` | Seconds for one 45 degree pivot. A 90 costs twice this. |
| `PIVOT_STROKES_PER_45` | `2` | Strokes per 45 degrees. Must be even (one forward, one back). |

`PIVOT_TURNS` composes with `DIAGONAL_HEADINGS` rather than replacing it:

| `DIAGONAL_HEADINGS` | `PIVOT_TURNS` | Result |
|---|---|---|
| False | False | today's planner, unchanged |
| True | False | the eight-heading experiment, unchanged |
| False | True | 4 headings, 90 degree pivots only |
| True | True | 8 headings, 45 and 90 degree pivots |

A 45 degree pivot from NORTH ends NORTHEAST, which only exists as a search state when the
diagonals are on. The available pivots therefore fall out of `segment._ranks()` on their own:
emit a pivot only when its END heading is in the rank set. No extra configuration.

Pivot strokes reuse `config.TURN_RADIUS_CM` and `config.TURN_PIVOT_OFFSET_CM` — the constants
STM is already measuring. Correcting those corrects the pivot geometry for free.

## Geometry

New module `pathfinding/search/pivot.py`, mirroring `turn.py`'s shape:

```python
def pivot(world: World, start: Vector, instruction: PivotInstruction) -> list[Vector] | None
```

Same contract as `turn()`: returns the cells of the manoeuvre in driving order with the end pose
appended, or `None` if it does not fit. Shape is cached as offsets from the origin and
translated to `start`, keyed on everything it depends on, so a runtime config change lands on a
fresh key.

**Intermediate headings are not `Direction` members.** At 2 strokes per 45 degrees the car
passes through 22.5 degrees. The derivation must therefore work in continuous compass degrees
(floats) and only resolve to a `Direction` at the start and the end.

Per stroke, the same statement of the manoeuvre `turn.__geometry` makes:

```
ux, uy   = sin(radians(heading)), cos(radians(heading))
rear     = (cx - lead*ux, cy - lead*uy)
side     = (-uy, ux) if lock in _LEFT_LOCK else (uy, -ux)
centre   = rear + radius*side
a0       = degrees(atan2(rear.y - centre.y, rear.x - centre.x))
turned   = -theta if lock in _ANTICLOCKWISE else +theta
steps    = max(1, ceil(radians(abs(theta)) * radius))
for i in 1..steps:
    a    = radians(a0 - turned*i/steps)
    r    = centre + radius*(cos a, sin a)
    h    = heading + turned*i/steps
    cell = round(r + lead*(sin(radians(h)), cos(radians(h))))
heading += turned
```

with `lead = robot.south_length - config.TURN_PIVOT_OFFSET_CM // cell_size` and
`radius = config.TURN_RADIUS_CM[lock] // cell_size`, exactly as `turn.py` computes them.

`strokes = PIVOT_STROKES_PER_45 * degrees // 45`, `theta = degrees / strokes`. Consecutive
duplicate cells are dropped, so the result is a path, not a set.

End pose: `Direction.of_degrees(start.direction.degrees + total_turned)` at the rounded final
centre. Like `turn()`, the end pose is NOT collision-checked.

## Clearance — the part that is easy to get wrong

`World.grid` marks cells where the robot's CENTRE may sit, inflating obstacles by the robot's
half-extent (15 cells). That is only valid for an axis-aligned square sliding along its heading.
A rotating 31 cm square sweeps a circle of radius `half_extent * sqrt(2)` ~ 21.2 cells, so a
pivot needs about 6 more cells of clearance on every side than a straight move at the same cell.

Checking a pivot against the ordinary grid would produce plans that look correct and clip the
obstacle — a silent failure.

**The fix, and why it is exactly right.** Obstacle inflation is L-infinity (an axis-aligned box
grown by `half_extent`). A rotating square needs the obstacle box grown by its circumscribed
radius with ROUNDED corners — the Minkowski sum with a disc. Eroding the already-inflated grid
by an L2 disc of radius

```
delta = ceil(half_extent * (sqrt(2) - 1))     # 7 cells for a 31 cm robot
```

grows the box by `half_extent + delta` with rounded corners. That is precisely the condition.

**Where it lives.** `segment._tables` builds one eroded copy of `free_cells` per search and
pivot legality masks read from it; ordinary turns and straights keep reading `free_cells`
untouched. Erosion is ~150 shifted ANDs done ONCE, then ~30 per pivot mask — cheap. Do NOT
dilate each pivot path by the disc instead: that is ~900 operations per mask per direction.

**Erode obstacle blockage, NOT the arena boundary — corrected 2026-09-11.** `free_cells` encodes
both, and an earlier draft said simply "erode `free_cells`". That is wrong.
`config.BOUNDARY_CLEARANCE_ADJUST_CM` is NEGATIVE on purpose: the arena boundary is virtual and
costs nothing to clip. Eroding it demands the robot centre sit 21 cells from the edge where a
straight needs 14, which makes the planner treat the virtual boundary as HARDER than a real
obstacle for this one primitive and SOFTER for every other. That inconsistency is the defect.

Measured legal start cells for a 90 degree pivot, NORTH table:

| world | eroding everything | eroding obstacles only |
|---|---|---|
| empty arena | 19,599 | 23,715 (+21%) |
| `02-four-obstacles` | 2,585 | 4,099 (+59%) |
| `04-five-obstacles` | 2,052 | 3,278 (+60%) |

This does NOT let the robot swing over the boundary: `eroded` stays a subset of `free_cells`, so
every cell of the pivot's centre-path excursion is still required to be inside the band. It only
stops charging a further 7 cells of standoff against a line that costs nothing to clip.

A correction to the motivation, so nobody repeats it: these cells are NOT what makes an obstacle
facing a wall reachable. Such goal poses are already refused by `objective.py` against the
UN-eroded 14-cell band, before the pivot's extra 7 is in play. What the cells buy is the general
case — turning round in tight space, some of which happens near a wall.

**Nothing in the suite pins this either way.** Whichever behaviour is chosen needs its own test,
or the next person flips it by accident.

Every cell of the pivot's centre path must be delta-clear, since the car is rotated off-axis
throughout.

### Known gap (pre-existing, out of scope)

The same reasoning says a robot at a DIAGONAL heading also needs ~21.9 cm of axis clearance, not
15, so the existing eight-heading experiment can already place the robot in poses that clip an
obstacle. This spec does not fix that — it would change the measured eight-heading results — but
the new code is correct on its own terms. Flag it to the algo owner separately.

## Instructions and cost

`pathfinding/search/instructions.py` gains a SEPARATE enum, not new `TurnInstruction` members.
`TurnInstruction` members flow into `turn.radius()`, `_LEFT_LOCK`, `_ANTICLOCKWISE` and
`segment._TURNS`, where `tuple(t for t in _TURNS if t.degrees == 90)` would silently pick up a
90 degree pivot and change the four-heading planner. Keeping them separate is what makes this
additive.

```python
class PivotInstruction(str, Enum):
    PIVOT_LEFT_45  = 'PIVOT_LEFT_45'
    PIVOT_RIGHT_45 = 'PIVOT_RIGHT_45'
    PIVOT_LEFT_90  = 'PIVOT_LEFT_90'
    PIVOT_RIGHT_90 = 'PIVOT_RIGHT_90'

    @property
    def degrees(self) -> int: ...      # 45 or 90, from the suffix
    @property
    def clockwise(self) -> bool: ...   # RIGHT is clockwise
    def strokes(self) -> int: ...      # PIVOT_STROKES_PER_45 * degrees // 45, read at call time

@dataclass
class Pivot:
    pivot: PivotInstruction
    vectors: list[Vector]
```

`cost.Weights` gains `pivot(instruction, cell_size)`:

- `_Time`: `config.PIVOT_TIME_S * instruction.degrees / 45`.
- `_Distance`: the ground the wheels actually cover — the sum of the stroke arc lengths,
  `(strokes/2) * radians(theta) * (R_forward_lock + R_backward_lock)` in cells.

`cost.move_cost` gains a `Pivot` branch. `search.Segment.compress` gains a `Pivot` case that
appends the instruction, extends the vectors and appends the move.

**The economics — corrected 2026-09-11.** A 45 degree pivot costs 2.0 s against 1.5 s for a 45
degree arc, and a 90 costs 4.0 s against 3.0 s. An earlier draft concluded from that: "it should
not appear on open-space routes." **That was wrong, and Task 4's review disproved it under the
time model the argument was made on.**

The error was comparing a pivot against *the single turn it replaces*. The search does not
substitute one for one — a pivot replaces a SEQUENCE. Measured on `04-five-obstacles`, obstacle
13's leg trades

    BACKWARD_RIGHT, BACK 35, BACKWARD_RIGHT, FWD 35, FORWARD_LEFT,
    BACKWARD_LEFT, FWD 10, BACKWARD_RIGHT, FWD 5          (23.17 s)

for

    BACK 15, PIVOT_RIGHT_90                               (18.67 s)

At 30 cm/s, undoing a quarter turn's unwanted (52, 28) cm costs 2-3 s; the pivot's 1 s premium
buys that back. Both cost models are honest and the primitive is behaving as designed.

The defensible claim, which is what this spec now asserts: **a pivot is dearer than the single
turn it replaces, and the search takes one only where it saves more corrective travel than the
premium costs.** In the measured routes every pivot sits immediately before `CAPTURE_IMAGE` or
between 5-15 cm straights — the three categories the primitive exists for. None decorates a
long straight.

**Route structure depends on `PIVOT_TIME_S`, and that number is a guess.** Sensitivity on 04,
time-weighted: 2.0 s gives 5 pivots (51.67 s), 2.5 gives 3 (55.17 s), 3.0-5.0 gives 1, and 6.0
gives none (62.33 s). It degrades gracefully rather than on a knife edge — but if the real
shuffle costs 6 s or more per 90 degrees, the whole benefit evaporates. This belongs in the STM
questions, not in a code change.

> Those sensitivity figures were measured on the PRE-boundary-fix build. After the fix the
> route structure changes — 04 time-weighted gives 2 pivots across 2 of 5 segments at 52.00 s,
> and greedy/distance gives 6 across 4 of 5 at 59.33 s. The shape of the conclusion (graceful
> decay, nothing left at 6 s) is unaffected; the exact counts are not worth re-deriving until
> `PIVOT_TIME_S` is a measurement rather than a guess.
>
> One honest wrinkle: post-fix, `plan_optimal` on 04 returns 52.00 s and logs "not a proven
> optimum" — the larger legal-cell set makes the branch and bound hit `MAX_REPLANS` sooner, so
> it is 0.33 s behind the 51.67 s the more constrained build happened to find. More reachable
> states, less of the space proved. Worth knowing before anyone reads 52.00 as a regression.

## Search integration

In `segment._tables`, gated on `config.PIVOT_TURNS`:

- **Move codes are APPENDED after the straight chunks.** Existing codes keep their values, and
  the docstring's rule that "two moves may reach one state at the same cost, and the first one
  recorded keeps it" then guarantees every existing tie-break is unchanged. This is what makes
  the additive guarantee testable rather than hoped for.
  `_Search.__move` decodes: `code <= len(_TURNS)` turn, `<= len(_TURNS)+len(chunks)` straight,
  else pivot.
- Pivot path offsets and end offsets must be folded into the `pad`/`span` computation, and
  `span >= delta` so the eroded array's reads stay in bounds.
- Emit a pivot only when its end heading is in `ranks`.

## Wire contract

`Segment.instructions` and `PathfindingResponseSegment.instructions` widen to include
`PivotInstruction`. Additive: a new member of an existing union, exactly like the diagonal
work's `FORWARD_LEFT_45`. Regenerate `docs/protocols/openapi.json` and add a deviation note to
`docs/protocols/algorithm-service.md`.

Requests are unaffected — `CardinalDirection` stays as it is.

The token strings are placeholders pending the RPi/STM owners. Renaming them is one edit to the
enum values.

## Simulator

`simulator/playback.py` animates a `Pivot` by sweeping the heading evenly across its vectors,
the same treatment it already gives a turn arc. The heading through a shuffle is monotonic —
every stroke turns the same way — so an even sweep is faithful.

## Test plan

New `tests/test_pivot.py`, marked `@pytest.mark.pivots`. `conftest.py` gains a `pivots` marker
and extends the autouse fixture to pin `config.PIVOT_TURNS` off unless a test asks for it,
exactly as it already does for `diagonals`.

Required tests:

1. A pivot swings the heading by its own size, from every heading, for every instruction.
2. A pivot leaves the robot within a small radius of where it started — the defining property.
   A 90 degree arc displaces the centre by (52, 28) cm; a pivot must be an order below that.
3. Two 45 degree pivots land where one 90 degree pivot does (one cell of rasterisation slack),
   the same oracle `test_diagonals.py` uses for the 45 degree turns.
4. A 45 degree pivot costs `PIVOT_TIME_S`; a 90 costs twice it; both read config at call time
   (assert against a monkeypatched value, not the literal 2.0).
5. **The additive guarantee**: with `PIVOT_TURNS=False`, routes are identical with the
   diagonals both on and off. Compare planned segments against the same world planned before
   the flag existed.
6. A pivot is REFUSED where a straight move at the same cell is legal but the extra rotation
   clearance is not — the clearance model's own test.
7. The payoff: a world where an obstacle is unreachable without pivots and reachable with them.
8. Playback produces frames at intermediate headings through a pivot.

## Global constraints

- `137 passed, 1 skipped` is the floor. With both flags off, no existing test may change.
- `config.py` imports nothing from the project, and consumers read constants at call time.
- Every new constant carries a `# SOURCE: <team> | placeholder | <note>` line.
- `docs/algorithms-todo.md` is MODIFIED AND UNCOMMITTED in the working tree. Do not touch it.
