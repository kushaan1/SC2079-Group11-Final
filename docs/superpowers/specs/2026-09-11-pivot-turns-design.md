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
matters. The drift is dominated by `R_forward != R_backward` (40 vs 37) — it is systematic,
not noise, which is why the planner can model it exactly.

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

**The economics this produces, which is the intended behaviour:** a 45 degree pivot costs 2.0 s
against 1.5 s for a 45 degree arc, and a 90 costs 4.0 s against 3.0 s. The pivot is always
dearer in time and gains zero ground, so the search reaches for it only where the arc's
displacement is unwanted or illegal — tight corners, U-turns, final approach alignment. It
should not appear on open-space routes.

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
