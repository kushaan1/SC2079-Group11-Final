# Derived from Pante/SC2079 (AY2023 S2, Group 14). See algorithm/PROVENANCE.md
"""
End-to-end smoke test for the working planner.

Builds a World, generates goal poses and runs the search, printing the resulting segments
and every obstacle the plan could not reach.

This is the check that the reference's blocking defect (Fix 1) is actually gone: the
reference raises TypeError on the very first turn() call and never reaches a segment.

Run it with a Python 3.11+ interpreter that has numpy and pydantic::

    python algorithm/smoke.py

Running the file directly puts ``algorithm`` on sys.path, which is what the
absolute ``import config`` / ``from pathfinding...`` imports need.
"""

from __future__ import annotations

import logging
import sys
import time

import config
from pathfinding.report import UnreachableReason
from pathfinding.search.instructions import MiscInstruction, MoveInstruction, TurnInstruction
from pathfinding.search.search import SearchResult, search
from pathfinding.world.objective import generate_objectives
from pathfinding.world.primitives import Direction, Point
from pathfinding.world.world import Obstacle, Robot, World


def make_robot(direction: Direction, south_west: tuple[int, int], north_east: tuple[int, int]) -> Robot:
    """
    Build a Robot, applying the same off-centre workaround the reference controller applies.

    The turning maths assumes the robot's centre cell is genuinely central, which only holds
    when both extents are even. A robot spanning 0..29 is therefore planned as 0..30. This is
    the corner-wise form of config.planned_footprint_cm(); config states the rule, this
    reproduces the controller's exact expression of it so the smoke test exercises the geometry
    the service does. pathfinding_controller.PathfindingRequestRobot.to_robot is the third copy.

    config.START_POSE is already odd-sized, so for the default pose this is a no-op.
    """
    sw = Point(*south_west)
    ne = Point(*north_east)
    if (ne.x - sw.x) % 2 != 0 and (ne.y - sw.y) % 2 != 0:
        ne = Point(ne.x + 1, ne.y + 1)
    return Robot(direction, sw, ne)


def default_robot() -> Robot:
    """The configured start pose."""
    return make_robot(
        Direction(config.START_POSE["direction"]),
        config.START_POSE["south_west"],
        config.START_POSE["north_east"],
    )


def describe_instruction(instruction) -> str:
    match instruction:
        case MoveInstruction():
            return f"{instruction.move.value}({instruction.amount}cm)"
        case TurnInstruction() | MiscInstruction():
            return instruction.value
        case _:
            return repr(instruction)


def report(result: SearchResult, robot: Robot, obstacles: list[Obstacle], elapsed: float) -> None:
    dropped = ", ".join(f"{entry.image_id}:{entry.reason.value}" for entry in result.unreachable)

    print(f"  robot      : {robot.direction.value} sw={robot.south_west} ne={robot.north_east} "
          f"centre={robot.centre}")
    print(f"  obstacles  : {len(obstacles)}   planned: {len(result.segments)}   "
          f"unreachable: {dropped or 'none'}")
    print(f"  plan time  : {elapsed * 1000:.0f} ms")

    if not result.segments:
        print("  segments   : NONE")
        return

    for index, segment in enumerate(result.segments, start=1):
        instructions = " -> ".join(describe_instruction(i) for i in segment.instructions)
        print(f"  segment {index}  : image_id={segment.image_id} cost={segment.cost} "
              f"vectors={len(segment.vectors)}")
        print(f"               end={segment.vectors[-1] if segment.vectors else None}")
        print(f"               {instructions}")


def run(
    name: str,
    robot: Robot,
    obstacles: list[Obstacle],
    expected_segments: int | None = None,
    expected_unreachable: dict[int, UnreachableReason] | None = None,
) -> bool:
    """
    Plan one arena and print it. Returns False only when a stated expectation was violated.

    A check that cannot fail is not a check: main() turns a False here into a non-zero exit
    status, so a regression breaks CI rather than printing MISMATCH into a passing log.

    :param expected_segments: The baseline segment count, or None to only print.
    :param expected_unreachable: The baseline ``{image_id: reason}`` the planner must report,
        or None to only print. ``{}`` is a real expectation - it asserts that nothing was
        dropped - and is not the same as None.
    """
    print(f"\n=== {name} ===")
    world = World(config.GRID_SIZE, robot, obstacles)
    print(f"  grid       : {world.size}x{world.size} cells @ {world.cell_size} cm/cell "
          f"({config.ARENA_SIZE_CM} cm arena), {int(world.grid.sum())} free cells")

    started = time.perf_counter()
    objectives = generate_objectives(world)
    result = search(world, objectives)
    elapsed = time.perf_counter() - started

    report(result, robot, obstacles, elapsed)

    checks: list[bool] = []

    # Invariant, checked on every arena whether or not a baseline was stated: the plan must
    # account for every obstacle exactly once. This is the property the structured
    # `unreachable` list exists to provide, so a bug that drops an obstacle from BOTH lists -
    # exactly the silent failure the structured report exists to remove - fails here rather
    # than being invisible.
    planned = [segment.image_id for segment in result.segments]
    reported = [entry.image_id for entry in result.unreachable]
    accounted = sorted(planned + reported)
    expected_ids = sorted(obstacle.image_id for obstacle in obstacles)
    partitioned = accounted == expected_ids
    checks.append(partitioned)
    print(f"  accounting : planned {sorted(planned)} + unreachable {sorted(reported)} "
          f"vs obstacles {expected_ids} -> {'OK' if partitioned else 'MISMATCH'}")

    if expected_segments is not None:
        passed = len(result.segments) == expected_segments
        checks.append(passed)
        print(f"  expected   : {expected_segments} segments, got {len(result.segments)} -> "
              f"{'OK' if passed else 'MISMATCH'}")

    if expected_unreachable is not None:
        actual = {entry.image_id: entry.reason for entry in result.unreachable}
        passed = actual == expected_unreachable
        checks.append(passed)
        expected_text = {i: r.value for i, r in expected_unreachable.items()} or "none"
        actual_text = {i: r.value for i, r in actual.items()} or "none"
        print(f"  unreachable: expected {expected_text}, got {actual_text} -> "
              f"{'OK' if passed else 'MISMATCH'}")

    return all(checks)


def main() -> None:
    # The planner reports dropped obstacles through `logging`, not `print`. Route it to
    # stdout so the warnings interleave with this script's own output in the order they
    # actually happened; on stderr they would arrive shuffled under any redirection.
    logging.basicConfig(level=logging.WARNING, stream=sys.stdout, format="  [%(levelname)s] %(message)s")

    print(f"config: standoff {config.STANDOFF_MIN_CM}-{config.STANDOFF_MAX_CM} cm, "
          f"lateral +/-{config.LATERAL_TOLERANCE_CM} cm, footprint {config.ROBOT_FOOTPRINT_CM} cm, "
          f"turn radii {config.TURN_RADIUS_CM}")

    # Regression baseline. The 2 below is NOT an independent oracle and is NOT a reference-planner
    # result: the reference planner cannot produce a segment count at all, because the very first
    # turn() call raises `TypeError: __curve() takes 5 positional arguments but 6 were given`
    # (defect 1). This number was captured from THIS working planner on 2026-08-25, after Ruling
    # R6 made the standoff band inclusive, and is recorded so that a future change altering it
    # becomes visible instead of silent. The arena itself is the one algorithm/PROVENANCE.md 4
    # uses to illustrate the Fix-2 centre defect; the segment count is ours.
    results = []
    results.append(run(
        "regression baseline: 2 obstacles",
        default_robot(),
        [
            Obstacle(Direction.SOUTH, Point(50, 90), Point(59, 99), 11),
            Obstacle(Direction.WEST, Point(120, 60), Point(129, 69), 12),
        ],
        expected_segments=2,
        expected_unreachable={},
    ))

    # Four obstacles, all clear of the walls. Obstacles adjacent to the wall they face have no
    # legal goal pose at a 25-30 cm standoff; that is a real property of the standoff band, not a
    # defect, and A coverage tool would quantify it.
    results.append(run(
        "nominal arena: 4 obstacles",
        default_robot(),
        [
            Obstacle(Direction.SOUTH, Point(50, 90), Point(59, 99), 11),
            Obstacle(Direction.WEST, Point(120, 60), Point(129, 69), 12),
            Obstacle(Direction.WEST, Point(150, 150), Point(159, 159), 13),
            Obstacle(Direction.EAST, Point(60, 150), Point(69, 159), 14),
        ],
        # Same provenance as the baseline above: captured from this planner on 2026-08-25, not
        # an independent oracle. All four obstacles are clear of the walls they face, so all four
        # are expected to plan.
        expected_segments=4,
        expected_unreachable={},
    ))

    # The pathological arena from the audit (algorithm/PROVENANCE.md 4). Zero segments is
    # CORRECT here, and the point of the arena is that the planner must now SAY SO - with
    # NO_OBJECTIVES, the reason that names the actual cause (goal-pose geometry), not NO_PATH
    # (which would blame the search). Previously the only evidence was two lines on stdout.
    #
    # The two obstacles fail for DIFFERENT underlying reasons, which is worth knowing before
    # anyone tries to "fix" the arena by widening the standoff band:
    #   - 13 faces NORTH at y<=159, so its poses land at y = 159 + 15 + (25..30) = 199..204,
    #     past the 14..185 free band world.py leaves after the boundary keep-out. It fails
    #     alone, and a wider band only pushes it further out.
    #   - 14 faces EAST and is nowhere near a wall. Planned on its own it has 180 valid poses;
    #     all of them sit inside obstacle 13's inflated keep-out (x 69..120, y 129..180), so it
    #     fails only because of its neighbour.
    # Both were checked by planning each obstacle alone on 2026-08-25. A test fixture should
    # capture this arena
    # and a coverage tool would measure the first failure mode across the arena.
    results.append(run(
        "pathological arena: 2 obstacles, neither plannable",
        default_robot(),
        [
            Obstacle(Direction.NORTH, Point(90, 150), Point(99, 159), 13),
            Obstacle(Direction.EAST, Point(30, 140), Point(39, 149), 14),
        ],
        expected_segments=0,
        expected_unreachable={
            13: UnreachableReason.NO_OBJECTIVES,
            14: UnreachableReason.NO_OBJECTIVES,
        },
    ))

    # The arena that proves the two reasons are actually told apart rather than both meaning
    # "we gave up". Without a case like this, NO_PATH is a code path nothing in the repo ever
    # executes. Obstacles 11 and 12 wall the start pose into a 5x5 cm pocket at x 14..18,
    # y 14..18 - the robot cannot take a single 5 cm chunk, let alone a 39 cm turn - yet both
    # have 48 perfectly valid goal poses each, so they are NO_PATH. Obstacle 13 is the
    # wall-facing one from the arena above and has none at all, so it is NO_OBJECTIVES. Same
    # run, same list, different reasons. Captured from this planner on 2026-08-25.
    results.append(run(
        "boxed-in arena: both unreachable reasons at once",
        default_robot(),
        [
            Obstacle(Direction.EAST, Point(40, 0), Point(49, 9), 11),
            Obstacle(Direction.NORTH, Point(0, 40), Point(9, 49), 12),
            Obstacle(Direction.NORTH, Point(90, 150), Point(99, 159), 13),
        ],
        expected_segments=0,
        expected_unreachable={
            11: UnreachableReason.NO_PATH,
            12: UnreachableReason.NO_PATH,
            13: UnreachableReason.NO_OBJECTIVES,
        },
    ))

    failures = results.count(False)
    print(f"\n=== {len(results) - failures}/{len(results)} arenas met their stated baseline ===")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
