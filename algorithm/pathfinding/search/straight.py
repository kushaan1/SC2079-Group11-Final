# Derived from Pante/SC2079 (AY2023 S2, Group 14). See algorithm/PROVENANCE.md
from pathfinding.world.primitives import Vector


def straight(start: Vector, modifier: int, length: int) -> list[Vector]:
    """
    The cells a straight move passes through, excluding the starting cell.

    One rule for every heading: step by the heading's own cell step. A diagonal step covers
    both axes, so it is 1.41 cm of ground rather than 1; `cost.move_cost` charges for that.
    """
    dx, dy = start.direction.step
    return [
        Vector(start.direction, start.x + dx * i * modifier, start.y + dy * i * modifier)
        for i in range(1, length + 1)
    ]
