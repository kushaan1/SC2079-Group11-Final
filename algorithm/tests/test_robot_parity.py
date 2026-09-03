from pathfinding.world.primitives import Direction, Point
from pathfinding.world.world import Robot


def test_even_extent_is_kept():
    robot = Robot.planned(Direction.NORTH, Point(0, 0), Point(30, 30))
    assert robot.north_east == Point(30, 30)
    assert robot.centre == Point(15, 15)


def test_odd_extent_is_bumped_by_one():
    robot = Robot.planned(Direction.NORTH, Point(0, 0), Point(29, 29))
    assert robot.north_east == Point(30, 30)


def test_bump_applies_off_origin():
    robot = Robot.planned(Direction.EAST, Point(10, 20), Point(39, 49))
    assert robot.north_east == Point(40, 50)
    assert robot.centre == Point(25, 35)
