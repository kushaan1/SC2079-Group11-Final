import pytest

from pathfinding.world.primitives import Direction, Point
from pathfinding.world.world import Obstacle


def test_tablet_obstacle_number_is_accepted():
    """1-8 is what the tablet sends on a real run; it used to be a 422."""
    obstacle = Obstacle(Direction.SOUTH, Point(50, 90), Point(59, 99), 1)
    assert obstacle.image_id == 1


def test_id_above_the_maximum_is_rejected():
    with pytest.raises(ValueError):
        Obstacle(Direction.SOUTH, Point(50, 90), Point(59, 99), 41)
