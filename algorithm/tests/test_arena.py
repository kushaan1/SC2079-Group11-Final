import json
import os

import pytest

import config
from pathfinding.world.primitives import Direction, Point
from simulator.arena import Arena, ArenaError, empty, from_request, load, save, to_request

TESTDATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testdata")


def test_empty_arena_has_the_configured_start_pose_and_no_obstacles():
    arena = empty()
    assert arena.obstacles == ()
    assert arena.robot.direction == Direction(config.START_POSE["direction"])
    assert arena.robot.south_west == Point(*config.START_POSE["south_west"])


def test_add_takes_lowest_unused_id_and_faces_south():
    arena = empty().add(5, 9).add(12, 6)
    assert [o.image_id for o in arena.obstacles] == [1, 2]
    assert arena.obstacles[0].south_west == Point(50, 90)
    assert arena.obstacles[0].north_east == Point(59, 99)
    assert arena.obstacles[0].direction == Direction.SOUTH
    assert arena.remove(1).add(3, 3 + 1).obstacles[-1].image_id == 1


def test_add_refuses_start_zone_arena_edge_and_overlap():
    arena = empty().add(5, 9)
    with pytest.raises(ArenaError, match="start zone"):
        arena.add(3, 3)
    with pytest.raises(ArenaError, match="outside"):
        arena.add(20, 0)
    with pytest.raises(ArenaError, match="overlaps obstacle 1"):
        arena.add(5, 9)


def test_add_refuses_when_ids_run_out():
    arena = empty()
    for n in range(config.IMAGE_ID_MAX - config.IMAGE_ID_MIN + 1):
        arena = arena.add(4 + n % 16, 4 + n // 16)
    with pytest.raises(ArenaError, match="no free obstacle id"):
        arena.add(19, 19)


def test_move_cycle_remove_and_lookup():
    arena = empty().add(5, 9).add(12, 6)
    arena = arena.move(2, 15, 15)
    assert arena.find(2).south_west == Point(150, 150)
    with pytest.raises(ArenaError, match="overlaps obstacle 1"):
        arena.move(2, 5, 9)
    faces = []
    for _ in range(4):
        arena = arena.cycle_face(1)
        faces.append(arena.find(1).direction)
    assert faces == [Direction.WEST, Direction.NORTH, Direction.EAST, Direction.SOUTH]
    assert arena.at(55, 95).image_id == 1
    assert arena.at(55, 80) is None
    assert arena.remove(1).find(1) is None


def test_request_round_trip_matches_testdata():
    with open(os.path.join(TESTDATA, "02-four-obstacles.json")) as f:
        data = json.load(f)
    arena = from_request(data)
    assert [o.image_id for o in arena.obstacles] == [11, 12, 13, 14]
    assert arena.find(13).direction == Direction.WEST
    assert arena.find(13).south_west == Point(150, 150)
    out = to_request(arena)
    assert out["obstacles"] == data["obstacles"]
    assert out["robot"] == data["robot"]
    assert out["verbose"] is False


def test_from_request_applies_the_parity_bump():
    data = {"robot": {"direction": "NORTH", "south_west": {"x": 0, "y": 0}, "north_east": {"x": 29, "y": 29}},
            "obstacles": []}
    assert from_request(data).robot.north_east == Point(30, 30)


def test_save_then_load(tmp_path):
    arena = empty().add(5, 9).cycle_face(1)
    path = tmp_path / "arena.json"
    save(path, arena)
    again = load(path)
    assert again == arena
    assert json.loads(path.read_text())["obstacles"][0]["direction"] == "WEST"


def test_world_builds_from_arena():
    world = empty().add(5, 9).world()
    assert world.size == config.GRID_SIZE
    assert len(world.obstacles) == 1


def test_at_is_half_open_so_neighbouring_cells_do_not_steal_clicks():
    arena = empty().add(5, 9).add(6, 9)
    assert arena.at(50, 90).image_id == 1
    assert arena.at(59.9, 95).image_id == 1
    assert arena.at(60, 95).image_id == 2
    assert arena.at(70, 95) is None
    assert arena.at(65, 100) is None
