# Derived from Pante/SC2079 (AY2023 S2, Group 14). See algorithm/PROVENANCE.md
from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

import numpy as np

import config
from pathfinding.world.primitives import Direction, Point, Vector


class World:
    """
    A world. Clearance computation is optimized for rectangular/square obstacles.

    The grid is a boolean occupancy map indexed ``grid[x, y]``: ``True`` means the robot's
    CENTRE may occupy that cell. Obstacles and the arena boundary are pre-inflated by the
    robot's half-extent, so the search downstream can treat the robot as a single point.
    """

    def __init__(self, size: int, robot: Robot, obstacles: list[Obstacle]):
        self.size = size
        self.grid = np.full((size, size), True)
        self.obstacles = obstacles
        self.robot = robot

        assert all(map(lambda obstacle: self.__inside(obstacle), self.obstacles))
        self.__annotate_grid()

        assert self.__inside(robot)

    def __inside(self, entity: Entity) -> bool:
        return (0 <= entity.south_west.x < self.size and
                0 <= entity.south_west.y < self.size and
                0 <= entity.north_east.x < self.size and
                0 <= entity.north_east.y < self.size)

    def __annotate_grid(self: World) -> None:
        # Call-time config rule: config is read here, in the function body, so that a caller may vary the
        # clearance constants at runtime (the coverage tool does exactly this). Never hoist
        # these to module level.
        edge_error = round(config.BOUNDARY_CLEARANCE_ADJUST_CM // self.cell_size)
        obstacle_error = round(config.OBSTACLE_CLEARANCE_CM // self.cell_size)

        self.grid[0:(self.robot.north_length + edge_error), :] = False
        self.grid[:, -(self.robot.east_length + edge_error):] = False
        self.grid[-(self.robot.south_length + edge_error):, :] = False
        self.grid[:, 0:(self.robot.west_length + edge_error)] = False

        for obstacle in self.obstacles:
            west_x = max(obstacle.south_west.x - self.robot.west_length - obstacle_error, 0)
            east_x = min(obstacle.north_east.x + self.robot.east_length + 1 + obstacle_error, self.size)
            south_y = max(obstacle.south_west.y - self.robot.south_length - obstacle_error, 0)
            north_y = min(obstacle.north_east.y + self.robot.north_length + 1 + obstacle_error, self.size)

            self.grid[west_x:east_x, south_y:north_y] = False

    def contains(self, centre: Point | Vector) -> bool:
        return (0 <= centre.x < self.size and 0 <= centre.y < self.size) and self.grid[centre.x, centre.y]

    @property
    def cell_size(self) -> int:
        """
        The width of one grid cell in centimetres.

        Call-time config rule: ``config.ARENA_SIZE_CM`` is read on every access rather than bound to a
        class attribute at import, so a caller may vary the arena size at runtime.
        """
        return config.ARENA_SIZE_CM // self.size


@dataclass
class Entity(ABC):
    direction: Direction
    south_west: Point
    north_east: Point

    def __post_init__(self):
        assert 0 <= self.south_west.x <= self.north_east.x
        assert 0 <= self.south_west.y <= self.north_east.y
        assert (self.north_east.y - self.south_west.y) == (self.north_east.x - self.south_west.x)
        # Fix 2: the reference computed a half-EXTENT here and called it a centre, omitting the
        # south_west offset. That made south_length/west_length negative for any entity not
        # anchored at the origin, silently corrupting grid inflation, objective generation and
        # every turn. Only a robot starting at (0, 0) hid the defect.
        self.centre = Point(
            self.south_west.x + (self.north_east.x - self.south_west.x) // 2,
            self.south_west.y + (self.north_east.y - self.south_west.y) // 2,
        )
        self.north_length = self.north_east.y - self.centre.y
        self.east_length = self.north_east.x - self.centre.x
        self.south_length = self.centre.y - self.south_west.y
        self.west_length = self.centre.x - self.south_west.x

    @property
    def clearance(self):
        # Assumes that height & width are the same
        return self.north_east.y - self.south_west.y + 1

    @property
    def vector(self) -> Vector:
        return Vector(self.direction, self.centre.x, self.centre.y)


@dataclass(unsafe_hash=True)
class Obstacle(Entity):
    image_id: int

    def __post_init__(self):
        super().__post_init__()
        # Fix 4: the reference asserted 1 <= image_id < 36, which rejects the arrow and stop
        # markers (IDs 36-40) that the competition actually uses. Bounds are read from config at
        # call time and the failure is a ValueError naming the offending id, not a bare assert
        # that vanishes under python -O.
        if not (config.IMAGE_ID_MIN <= self.image_id <= config.IMAGE_ID_MAX):
            raise ValueError(
                f"image_id {self.image_id} is outside the valid range "
                f"{config.IMAGE_ID_MIN}-{config.IMAGE_ID_MAX} (inclusive)."
            )


@dataclass
class Robot(Entity):
    def __post_init__(self):
        super().__post_init__()
