"""
The editable arena: the robot's start pose plus obstacles, with the placement rules, and the
JSON the RPi sends (`PathfindingRequest`) as its file format.

Immutable: every edit returns a new Arena, so the window can hold "the arena before this drag"
for free and a refused edit changes nothing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

import config
from pathfinding.world.primitives import Direction, Point
from pathfinding.world.world import Obstacle, Robot, World
from simulator.geometry import cell_to_corners

FACE_ORDER = (Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST)


class ArenaError(ValueError):
    """An edit the arena refuses. The message is shown to the user as-is."""


@dataclass(frozen=True)
class Arena:
    robot: Robot
    obstacles: tuple[Obstacle, ...]

    def find(self, image_id: int) -> Obstacle | None:
        return next((o for o in self.obstacles if o.image_id == image_id), None)

    def at(self, x_cm: float, y_cm: float) -> Obstacle | None:
        """The obstacle covering an arena point, if any."""
        for o in self.obstacles:
            # Half-open on the far side: the first centimetre of the next cell is not this obstacle.
            if o.south_west.x <= x_cm < o.north_east.x + 1 and o.south_west.y <= y_cm < o.north_east.y + 1:
                return o
        return None

    def next_id(self) -> int:
        used = {o.image_id for o in self.obstacles}
        for candidate in range(config.IMAGE_ID_MIN, config.IMAGE_ID_MAX + 1):
            if candidate not in used:
                return candidate
        raise ArenaError(f"no free obstacle id: all of {config.IMAGE_ID_MIN}-{config.IMAGE_ID_MAX} are used")

    def add(self, cx: int, cy: int, direction: Direction = Direction.SOUTH) -> Arena:
        image_id = self.next_id()
        south_west, north_east = cell_to_corners(cx, cy)
        self._check_placement(south_west, north_east, ignore_id=None)
        return replace(self, obstacles=self.obstacles + (Obstacle(direction, south_west, north_east, image_id),))

    def remove(self, image_id: int) -> Arena:
        return replace(self, obstacles=tuple(o for o in self.obstacles if o.image_id != image_id))

    def move(self, image_id: int, cx: int, cy: int) -> Arena:
        old = self._require(image_id)
        south_west, north_east = cell_to_corners(cx, cy)
        self._check_placement(south_west, north_east, ignore_id=image_id)
        moved = Obstacle(old.direction, south_west, north_east, image_id)
        return replace(self, obstacles=tuple(moved if o.image_id == image_id else o for o in self.obstacles))

    def cycle_face(self, image_id: int) -> Arena:
        old = self._require(image_id)
        face = FACE_ORDER[(FACE_ORDER.index(old.direction) + 1) % 4]
        turned = Obstacle(face, old.south_west, old.north_east, image_id)
        return replace(self, obstacles=tuple(turned if o.image_id == image_id else o for o in self.obstacles))

    def world(self) -> World:
        return World(config.GRID_SIZE, self.robot, list(self.obstacles))

    def _require(self, image_id: int) -> Obstacle:
        found = self.find(image_id)
        if found is None:
            raise ArenaError(f"no obstacle {image_id}")
        return found

    def _check_placement(self, south_west: Point, north_east: Point, ignore_id: int | None) -> None:
        limit = config.ARENA_SIZE_CM
        if not (0 <= south_west.x and north_east.x < limit and 0 <= south_west.y and north_east.y < limit):
            raise ArenaError("outside the arena")
        zone = config.START_ZONE_CM
        if south_west.x < zone and south_west.y < zone:
            raise ArenaError("overlaps the start zone")
        for o in self.obstacles:
            if o.image_id == ignore_id:
                continue
            if not (north_east.x < o.south_west.x or south_west.x > o.north_east.x
                    or north_east.y < o.south_west.y or south_west.y > o.north_east.y):
                raise ArenaError(f"overlaps obstacle {o.image_id}")


def empty() -> Arena:
    pose = config.START_POSE
    robot = Robot.planned(Direction(pose["direction"]), Point(*pose["south_west"]), Point(*pose["north_east"]))
    return Arena(robot, ())


def _point(d: dict) -> Point:
    return Point(int(d["x"]), int(d["y"]))


def from_request(data: dict) -> Arena:
    """Parse a PathfindingRequest body. `verbose` is ignored."""
    r = data["robot"]
    robot = Robot.planned(Direction(r["direction"]), _point(r["south_west"]), _point(r["north_east"]))
    obstacles = tuple(
        Obstacle(Direction(o["direction"]), _point(o["south_west"]), _point(o["north_east"]), int(o["image_id"]))
        for o in data.get("obstacles", [])
    )
    return Arena(robot, obstacles)


def to_request(arena: Arena) -> dict:
    """The exact body the RPi would POST for this arena. Not verbose: it is for replay, not drawing."""
    def corners(e):
        return {"south_west": {"x": e.south_west.x, "y": e.south_west.y},
                "north_east": {"x": e.north_east.x, "y": e.north_east.y}}
    return {
        "verbose": False,
        "robot": {"direction": arena.robot.direction.value, **corners(arena.robot)},
        "obstacles": [{"image_id": o.image_id, "direction": o.direction.value, **corners(o)} for o in arena.obstacles],
    }


def load(path: str | Path) -> Arena:
    with open(path) as f:
        return from_request(json.load(f))


def save(path: str | Path, arena: Arena) -> None:
    with open(path, "w") as f:
        json.dump(to_request(arena), f, indent=2)
        f.write("\n")
