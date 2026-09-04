from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
import time

from pathfinding.world.world import World
from pathfinding.world.objective import generate_objectives
from pathfinding.search.search import search


@dataclass(frozen=True)
class Route:
    segments: list
    unreachable: list
    source_name: str
    plan_ms: float


class RouteSource(Protocol):
    name: str

    def plan(self, world: World) -> Route: ...


class GreedyRouteSource:
    name = "Greedy (nearest-first)"

    def plan(self, world: World) -> Route:
        start = time.time()
        gen = generate_objectives(world)
        result = search(world, gen)
        plan_ms = (time.time() - start) * 1000.0
        return Route(result.segments, result.unreachable, self.name, plan_ms)


ROUTE_SOURCES = [GreedyRouteSource()]
