import math

import config
from pathfinding.world.primitives import Direction, Point
from simulator.geometry import (Geometry, HEADING_DEG, Pose, car_shapes, cell_to_corners,
                                centre_to_tablet, corners_to_cell, fit_scale, rotate, snap,
                                unit)

G = Geometry(scale=3.0, arena_cm=200)


def test_origin_is_bottom_left():
    assert G.to_canvas(0, 0) == (0.0, 600.0)


def test_top_left_maps_to_canvas_origin():
    assert G.to_canvas(0, 200) == (0.0, 0.0)


def test_far_corner():
    assert G.to_canvas(200, 0) == (600.0, 600.0)
    assert G.arena_px == 600.0


def test_round_trip():
    for x, y in [(0, 0), (17, 3), (100, 100), (199, 199)]:
        px, py = G.to_canvas(x, y)
        assert G.to_arena(px, py) == (x, y)


def test_rect_is_flipped_and_upright():
    x0, y0, x1, y1 = G.rect(50, 90, 10, 10)
    assert (x0, x1) == (150.0, 180.0)
    assert y0 < y1
    assert (y0, y1) == (300.0, 330.0)
    assert y1 - y0 == 10 * G.scale


def test_fit_scale_clamps():
    assert fit_scale(900, 200) == 680 / 200
    assert fit_scale(400, 200) == 480 / 200
    assert fit_scale(2000, 200) == 720 / 200


def test_snap():
    assert snap(97, 10) == 90
    assert snap(90, 10) == 90
    assert snap(0, 10) == 0
    assert snap(9.9, 10) == 0


def test_cells_match_the_tablet():
    sw, ne = cell_to_corners(5, 9)
    assert (sw, ne) == (Point(50, 90), Point(59, 99))
    assert corners_to_cell(sw) == (5, 9)
    assert centre_to_tablet(15, 15) == (1.0, 1.0)
    assert centre_to_tablet(55, 95) == (5.0, 9.0)


def test_rotate_east_sends_forward_to_plus_x():
    (x, y), = rotate([(0, 10)], 50, 50, 90)
    assert math.isclose(x, 60) and math.isclose(y, 50, abs_tol=1e-9)


def test_rotate_east_sends_right_hand_to_south():
    (x, y), = rotate([(10, 0)], 50, 50, 90)
    assert math.isclose(x, 50, abs_tol=1e-9) and math.isclose(y, 40)


def test_car_camera_is_at_the_front():
    north = car_shapes(Pose(100, 100, 0))
    assert len(north.body) == 8 and len(north.wheels) == 4
    cx, cy, r = north.camera
    assert cy > 100 and math.isclose(cx, 100, abs_tol=1e-9) and r > 0
    west = car_shapes(Pose(100, 100, HEADING_DEG[Direction.WEST]))
    wx, wy, _ = west.camera
    assert wx < 100 and math.isclose(wy, 100, abs_tol=1e-9)


def test_car_body_spans_the_configured_chassis():
    body = car_shapes(Pose(100, 100, 0)).body
    xs = [p[0] for p in body]
    ys = [p[1] for p in body]
    w, l = config.ROBOT_BODY_CM
    assert math.isclose(max(xs) - min(xs), w) and math.isclose(max(ys) - min(ys), l)
    east = car_shapes(Pose(100, 100, 90))
    xs = [p[0] for p in east.body]
    assert math.isclose(max(xs) - min(xs), l)          # length now lies along x
    assert math.isclose(min(xs), 100 - l / 2)          # translated to the centre
    wheel_xs = [p[0] for q in east.wheels for p in q]
    assert min(wheel_xs) > 100 - l / 2 and max(wheel_xs) < 100 + l / 2   # wheels inboard along the length


def test_unit_points_along_the_compass():
    dx, dy = unit(0)
    assert math.isclose(dx, 0, abs_tol=1e-9) and math.isclose(dy, 1)
    dx, dy = unit(90)
    assert math.isclose(dx, 1) and math.isclose(dy, 0, abs_tol=1e-9)


def test_car_can_be_drawn_part_way_through_a_turn():
    """A heading between compass points is honoured, not snapped."""
    (camx, camy) = car_shapes(Pose(100, 100, 45)).camera[:2]
    assert camx > 100 and camy > 100
