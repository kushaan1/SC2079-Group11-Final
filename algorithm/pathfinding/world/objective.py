# Derived from Pante/SC2079 (AY2023 S2, Group 14). See algorithm/PROVENANCE.md
from __future__ import annotations

import logging
from dataclasses import dataclass

import config
from pathfinding.report import UnreachableObstacle, UnreachableReason
from pathfinding.world.primitives import Direction, Vector
from pathfinding.world.world import Obstacle, World, Robot

logger = logging.getLogger(__name__)


@dataclass
class ObjectiveGeneration:
    """
    The outcome of goal-pose generation for one world.

    Two halves that must travel together: the obstacles that got goal poses, and the ones
    that did not. The reference returned only the first half and ``print()``-ed the second,
    which is how an obstacle disappears from a plan with no trace in the response.

    :param objectives: The obstacles that have at least one valid goal pose, mapped to
        ``(representative pose, all valid poses)``. Insertion order follows
        ``world.obstacles``.
    :param unreachable: The obstacles that produced no goal pose at all, each recorded with
        :attr:`~pathfinding.report.UnreachableReason.NO_OBJECTIVES`. Order follows
        ``world.obstacles``. Empty when every obstacle is plannable.

    Together the two account for every obstacle in ``world.obstacles``, exactly once each.
    :func:`~pathfinding.search.search.search` checks that when it is handed one of these, and
    raises if it does not hold — which is what lets :class:`SearchResult` promise the same
    partition of its own two lists. Neither field has a default: a half-built generation is
    never something a caller means.
    """

    objectives: dict[Obstacle, tuple[Vector, set[Vector]]]
    unreachable: list[UnreachableObstacle]


def generate_objectives(world: World) -> ObjectiveGeneration:
    """
    Compute the goal poses for every obstacle in the world.

    :param world: The world.
    :return: An :class:`ObjectiveGeneration` carrying both the goal poses and the obstacles
        that have none. Callers must not drop the second half: an obstacle missing from
        ``objectives`` is an obstacle the robot will never photograph.
    """
    objectives: dict[Obstacle, tuple[Vector, set[Vector]]] = dict()
    unreachable: list[UnreachableObstacle] = []

    for obstacle in world.obstacles:
        generated = __generate_objectives(world, obstacle)
        if not generated:
            # NO_OBJECTIVES, not NO_PATH: no pose satisfying the standoff band survives
            # World.contains(), so the search is never even offered a target for this
            # obstacle. The two reasons are distinguished HERE, at the only place that can
            # tell them apart. The log line is for a human watching a terminal; the entry
            # appended to `unreachable` is the contract.
            unreachable.append(UnreachableObstacle(obstacle.image_id, UnreachableReason.NO_OBJECTIVES))
            # The message deliberately does NOT say "too close to a wall". World.contains()
            # rejects a pose for either of two reasons - off the arena's free band, or inside
            # another obstacle's inflated keep-out - and the two are indistinguishable from
            # here. Naming only the first would be a guess: in the audit's pathological arena
            # obstacle 14 has 180 perfectly good poses on its own and loses all of them to
            # obstacle 13's keep-out, nowhere near a wall.
            logger.warning(
                "No goal pose for image_id %s (%s face, %s-%s): every pose in the standoff "
                "band %s-%s cm is outside the arena's free area or inside a keep-out zone. Skipping.",
                obstacle.image_id,
                obstacle.direction.value,
                obstacle.south_west,
                obstacle.north_east,
                config.STANDOFF_MIN_CM,
                config.STANDOFF_MAX_CM,
            )
            continue

        objectives[obstacle] = next(iter(generated)), generated

    return ObjectiveGeneration(objectives, unreachable)


def __generate_objectives(world: World, obstacle: Obstacle) -> set[Vector]:
    """
    Compute all possible objective locations for an obstacle.

    A goal pose is not a single point. It is a band of standoff distances crossed with a
    lateral tolerance, which turns a brittle exact-arrival problem into a robust one.

    :param world: The world.
    :param obstacle: The obstacle.
    :return: The valid objectives.
    """
    # Call-time config rule: every config value is read HERE, inside the function body, on every call.
    # A coverage tool sweeps the standoff band by assigning to config at runtime and
    # re-invoking this function. Binding these at module import would silently freeze the sweep
    # at the first value it saw. Do not hoist them.
    cell_size = world.cell_size

    """
    The minimum distance (in grid cells) between the obstacle and centre of objective, inclusive. (Total cm / cm per cell).
    """
    minimum_gap = config.STANDOFF_MIN_CM // cell_size
    """
    The maximum distance (in grid cells) between the obstacle and centre of objective, INCLUSIVE. (Total cm / cm per cell).
    """
    maximum_gap = config.STANDOFF_MAX_CM // cell_size

    """
    The offset to the sides (in grid cells) between the obstacle and objective, inclusive.
    (Total cm / cm per cell). This should be increased as the difference in sizes between obstacles & the robot increases.
    """
    offset = config.LATERAL_TOLERANCE_CM // cell_size

    # Fix 3: the reference performed this boundary test, and its `offset += 2`, INSIDE the gap
    # loop. For a boundary obstacle the lateral tolerance therefore compounded on every
    # iteration (+2, +4, +6, ...) instead of applying once. Hoisted so it applies exactly once
    # per obstacle.
    touches_boundary = (
        obstacle.south_west.x == 0
        or obstacle.south_west.y == 0
        or obstacle.north_east.x == world.size - 1
        or obstacle.north_east.y == world.size - 1
    )
    if touches_boundary:
        offset += config.BOUNDARY_LATERAL_BONUS_CELLS

    objectives = set()
    # Inclusive standoff band: it means literally what config names it - the CLOSED interval
    # [STANDOFF_MIN_CM, STANDOFF_MAX_CM]. The reference iterated a half-open range and then passed
    # `gap + 1`, so a config reading 25-30 actually produced 26-30 cm. Standoff is the number a
    # four-team integration meeting negotiates and a coverage table publishes; it must not
    # misreport itself by a centimetre. `maximum_gap + 1` makes the upper bound inclusive and the
    # gap is now passed through unmodified.
    for gap in range(minimum_gap, maximum_gap + 1):
        for alignment in range(-offset, obstacle.clearance + offset):
            objective = __suggest_objective(world.robot, obstacle, gap, alignment)
            if world.contains(objective):
                objectives.add(objective)

    return objectives


def __suggest_objective(robot: Robot, obstacle: Obstacle, gap: int, alignment: int) -> Vector:
    """
    Creates an objective from this obstacle.

    This function assumes that obstacles are always smaller than the robot. It does not check whether the objective
    collides with other obstacles.

    :param obstacle: The obstacle.
    :param gap: The distance (in grid cells) between the obstacle and objective.
    :param alignment: An offset (in grid cells) to adjust the suggested objective's placement by.
    :return: An objective.
    """

    clearance = obstacle.clearance - 1
    match obstacle.direction:
        case Direction.NORTH:
            return Vector(
                Direction.SOUTH,
                obstacle.north_east.x - clearance + alignment,
                obstacle.north_east.y + robot.south_length + gap,
            )

        case Direction.EAST:
            return Vector(
                Direction.WEST,
                obstacle.north_east.x + robot.west_length + gap,
                obstacle.north_east.y - clearance + alignment
            )

        case Direction.SOUTH:
            return Vector(
                Direction.NORTH,
                obstacle.south_west.x + clearance - alignment,
                obstacle.south_west.y - robot.north_length - gap
            )

        case Direction.WEST:
            return Vector(
                Direction.EAST,
                obstacle.south_west.x - robot.east_length - gap,
                obstacle.south_west.y + clearance - alignment,
                )
