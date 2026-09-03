"""
Where a route comes from. One protocol, so the shortest-time optimiser (checklist B.3) plugs in
as a second RouteSource and the window lists both without changing.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from pathfinding.report import UnreachableObstacle
from pathfinding.search.search import Segment, search
from pathfinding.world.objective import generate_objectives
from pathfinding.world.world import Robot, World


@dataclass(frozen=True)
class Route:
    segments: list[Segment]
    unreachable: list[UnreachableObstacle]
    source_name: str
    plan_ms: float
    robot: Robot | None = None      # the planned robot, for its half-extent
    cell_size: int = 1              # world.cell_size, cm per cell

    @property
    def total_cost(self) -> int:
        return sum(s.cost for s in self.segments)


class RouteSource(Protocol):
    name: str

    def plan(self, world: World) -> Route: ...


class GreedyRouteSource:
    """The planner as it is: goal poses, then one greedy nearest-first search. Nothing altered."""

    name = "Greedy, nearest first"

    def plan(self, world: World) -> Route:
        started = time.perf_counter()
        result = search(world, generate_objectives(world))
        elapsed_ms = (time.perf_counter() - started) * 1000
        return Route(result.segments, result.unreachable, self.name, elapsed_ms,
                     world.robot, world.cell_size)


SOURCES: tuple[RouteSource, ...] = (GreedyRouteSource(),)
