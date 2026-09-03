"""
Where a route comes from. One protocol, two implementations: the greedy planner and the
shortest-time optimiser (checklist B.3). The window lists whatever is in SOURCES, so adding a
third would not touch app.py.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Protocol

from pathfinding.report import UnreachableObstacle
from pathfinding.search.search import Segment, SearchResult, search
from pathfinding.search.tour import plan_optimal
from pathfinding.world.objective import ObjectiveGeneration, generate_objectives
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

    @property
    def seconds(self) -> float:
        """Estimated driving time of the whole route, excluding the capture dwells. The same
        number the optimiser minimises, so the panel's estimate and its objective agree."""
        return sum((s.seconds for s in self.segments), 0.0)


class RouteSource(Protocol):
    name: str

    def plan(self, world: World) -> Route: ...


def _timed(name: str, planner: Callable[[World, ObjectiveGeneration], SearchResult],
           world: World) -> Route:
    """Run a planner and wrap its result as a Route. Both sources go through here so they are
    measured the same way - goal-pose generation included, since pressing the button pays for
    it - and so the Route's fields are wired in one place rather than two."""
    started = time.perf_counter()
    result = planner(world, generate_objectives(world))
    elapsed_ms = (time.perf_counter() - started) * 1000
    return Route(result.segments, result.unreachable, name, elapsed_ms, world.robot, world.cell_size)


class GreedyRouteSource:
    """The planner as it is: goal poses, then one greedy nearest-first search. Nothing altered."""

    name = "Greedy, nearest first"

    def plan(self, world: World) -> Route:
        return _timed(self.name, search, world)


class OptimalRouteSource:
    """Shortest estimated time: the same goal poses, ordered by the branch-and-bound optimiser.

    Never photographs fewer obstacles than greedy and, at the same count, never takes longer -
    guaranteed by `plan_optimal`, which scores greedy's own route among the candidates. Costs
    a leg matrix plus several re-planned routes, so it is much the slower of the two to press.
    """

    name = "Shortest time"

    def plan(self, world: World) -> Route:
        return _timed(self.name, plan_optimal, world)


# Registry order is panel order: greedy first because it is the fast one to press.
SOURCES: tuple[RouteSource, ...] = (GreedyRouteSource(), OptimalRouteSource())
