import pytest

from rpi import arena
from rpi.model import START_POSE, Obstacle, Pose


def test_start_pose_matches_planner_readme_example():
    robot = arena.pose_to_planner_robot(START_POSE)
    assert robot == {
        "direction": "NORTH",
        "south_west": {"x": 0, "y": 0},
        "north_east": {"x": 30, "y": 30},
    }


def test_obstacle_corners_are_inclusive_cm():
    body = arena.obstacle_to_planner(Obstacle(3, 5, 9, "E"))
    assert body == {
        "image_id": 3,
        "direction": "EAST",
        "south_west": {"x": 50, "y": 90},
        "north_east": {"x": 59, "y": 99},
    }


def test_obstacle_without_face_is_refused():
    with pytest.raises(ValueError):
        arena.obstacle_to_planner(Obstacle(2, 5, 5, None))


def test_robot_centre_is_clamped_away_from_the_far_edge():
    # cell 18 -> centre 185 cm -> corner 200, which the planner rejects (spec §3.3)
    robot = arena.pose_to_planner_robot(Pose(18.0, 18.0, 90.0))
    assert robot["north_east"] == {"x": 199, "y": 199}
    assert robot["south_west"] == {"x": 169, "y": 169}
    assert robot["direction"] == "EAST"


def test_decimal_cells_round_to_whole_cm():
    robot = arena.pose_to_planner_robot(Pose(7.5, 2.25, 180.0))
    assert robot["south_west"] == {"x": 65, "y": 13}    # 80-15, 27.5 -> 28 - 15
    assert robot["direction"] == "SOUTH"


@pytest.mark.parametrize("heading,direction", [
    (0, "NORTH"), (44, "NORTH"), (46, "EAST"), (90, "EAST"), (180, "SOUTH"),
    (270, "WEST"), (359, "NORTH"), (-90, "WEST"), (450, "EAST"),
])
def test_heading_to_direction(heading, direction):
    assert arena.heading_to_direction(heading) == direction


def test_cells_and_cm_round_trip():
    assert arena.cells_to_cm(1.0) == 15.0
    assert arena.cm_to_cells(15.0) == 1.0
    assert arena.cm_to_cells(arena.cells_to_cm(12.3)) == pytest.approx(12.3)


def test_planner_vector_to_pose():
    pose = arena.planner_vector_to_pose({"direction": "EAST", "x": 15, "y": 15})
    assert pose == Pose(1.0, 1.0, 90.0)
    assert arena.planner_vector_to_pose({"direction": "NORTHEAST", "x": 25, "y": 5}).heading == 45.0


def test_request_body():
    body = arena.to_planner_request([Obstacle(1, 10, 6, "N")], START_POSE, "greedy")
    assert body["verbose"] is True
    assert body["strategy"] == "greedy"
    assert body["robot"]["direction"] == "NORTH"
    assert body["obstacles"][0]["image_id"] == 1


def test_request_without_obstacles_is_refused():
    with pytest.raises(ValueError):
        arena.to_planner_request([], START_POSE, "optimal")
