import pytest

from rpi.model import Arc, Capture, Pose, Straight
from rpi.pose import advance

RADII = {"FORWARD_LEFT": 40, "FORWARD_RIGHT": 40, "BACKWARD_LEFT": 40, "BACKWARD_RIGHT": 40}


def close(pose, x, y, heading):
    assert pose.x == pytest.approx(x, abs=1e-6)
    assert pose.y == pytest.approx(y, abs=1e-6)
    assert pose.heading == pytest.approx(heading, abs=1e-6)


def test_forward_north():
    close(advance(Pose(1.0, 1.0, 0.0), Straight("FORWARD", 30), RADII), 1.0, 4.0, 0.0)


def test_backward_east():
    close(advance(Pose(5.0, 5.0, 90.0), Straight("BACKWARD", 20), RADII), 3.0, 5.0, 90.0)


def test_forward_left_from_north_ends_west_of_and_ahead_of_the_start_facing_west():
    close(advance(Pose(10.0, 10.0, 0.0), Arc("FORWARD_LEFT", 90), RADII), 6.0, 14.0, 270.0)


def test_forward_right_from_north():
    close(advance(Pose(10.0, 10.0, 0.0), Arc("FORWARD_RIGHT", 90), RADII), 14.0, 14.0, 90.0)


def test_backward_left_from_north_ends_behind_and_left_facing_east():
    close(advance(Pose(10.0, 10.0, 0.0), Arc("BACKWARD_LEFT", 90), RADII), 6.0, 6.0, 90.0)


def test_backward_right_from_north():
    close(advance(Pose(10.0, 10.0, 0.0), Arc("BACKWARD_RIGHT", 90), RADII), 14.0, 6.0, 270.0)


def test_arcs_use_the_per_direction_radius():
    radii = dict(RADII, FORWARD_RIGHT=20)
    close(advance(Pose(0.0, 0.0, 0.0), Arc("FORWARD_RIGHT", 90), radii), 2.0, 2.0, 90.0)


def test_45_degree_arc_follows_the_chord_not_half_the_90_degree_step():
    # Radius 4 cells: forward 4*sin(45) = 2.828, left 4*(1 - cos(45)) = 1.172 - not 2 and 2.
    close(advance(Pose(10.0, 10.0, 0.0), Arc("FORWARD_LEFT", 45), RADII),
          10.0 - 1.1715729, 10.0 + 2.8284271, 315.0)


def test_180_degree_arc_ends_beside_the_start_facing_back():
    # A half circle of radius 4 cells: no forward displacement, 2R to the right.
    close(advance(Pose(0.0, 0.0, 0.0), Arc("FORWARD_RIGHT", 180), RADII), 8.0, 0.0, 180.0)


def test_heading_wraps():
    close(advance(Pose(0.0, 0.0, 270.0), Arc("FORWARD_RIGHT", 90), RADII), -4.0, 4.0, 0.0)


def test_capture_changes_nothing():
    assert advance(Pose(3.0, 4.0, 45.0), Capture(), RADII) == Pose(3.0, 4.0, 45.0)
