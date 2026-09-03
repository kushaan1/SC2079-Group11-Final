import os
from itertools import groupby

from simulator import arena_view as av
from simulator.arena import empty, load
from simulator.geometry import Geometry, Pose
from simulator.painters import RecordingPainter

TESTDATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testdata")
G = Geometry(scale=3.0, arena_cm=200)


def calls(painter, op):
    return [(args, kwargs) for name, args, kwargs in painter.calls if name == op]


def test_start_zone_is_bottom_left_and_grid_covers_arena():
    p = RecordingPainter()
    av.draw_static(p, G, av.Scene(empty()))
    rects = calls(p, "rect")
    start = [r for r in rects if r[1].get("fill") == av.START_FILL]
    assert len(start) == 1
    x0, y0, x1, y1 = start[0][0]
    assert (x0, y1) == (0.0, 600.0) and x1 == 120.0 and y0 == 480.0
    lines = calls(p, "line")
    assert sum(1 for l in lines if l[1].get("fill") == av.GRID_MAJOR) == 5 * 2
    assert sum(1 for l in lines if l[1].get("fill") == av.GRID_MINOR) == 16 * 2


def assert_stripe_on(face, body, stripe):
    """The stripe shares the body's edge on the face it is drawn on, and is thin the other way."""
    bx0, by0, bx1, by1 = body[0]
    sx0, sy0, sx1, sy1 = stripe[0]
    if face == "SOUTH":                        # bottom edge: larger canvas y
        assert sy1 == by1 and sy0 > by0 and (sx0, sx1) == (bx0, bx1)
    elif face == "NORTH":                      # top edge: smaller canvas y
        assert sy0 == by0 and sy1 < by1 and (sx0, sx1) == (bx0, bx1)
    elif face == "EAST":
        assert sx1 == bx1 and sx0 > bx0 and (sy0, sy1) == (by0, by1)
    elif face == "WEST":
        assert sx0 == bx0 and sx1 < bx1 and (sy0, sy1) == (by0, by1)
    else:
        raise AssertionError(f"not a face: {face}")


def bodies_and_stripes(painter):
    """The body and stripe rects in draw order, which is one pair per obstacle."""
    return ([r for r in calls(painter, "rect") if r[1].get("fill") == av.INK],
            [r for r in calls(painter, "rect") if r[1].get("fill") == av.FACE])


def test_each_obstacle_gets_a_body_a_face_stripe_and_a_label():
    arena = load(os.path.join(TESTDATA, "02-four-obstacles.json"))
    p = RecordingPainter()
    av.draw_static(p, G, av.Scene(arena))
    bodies, stripes = bodies_and_stripes(p)
    labels = [t for t in calls(p, "text") if t[0][2] in {"11", "12", "13", "14"}]
    assert len(bodies) == 4 and len(stripes) == 4 and len(labels) == 4
    # 11 faces SOUTH at (50,90); 12 WEST at (120,60); 13 WEST at (150,150); 14 EAST at (60,150)
    faces = ["SOUTH", "WEST", "WEST", "EAST"]
    corners = [(50, 90), (120, 60), (150, 150), (60, 150)]
    for face, (cx, cy), body, stripe in zip(faces, corners, bodies, stripes):
        assert body[0] == G.rect(cx, cy, 10, 10)
        assert_stripe_on(face, body, stripe)


def test_a_north_facing_obstacle_puts_its_stripe_on_the_top_edge():
    arena = empty().add(5, 9).cycle_face(1).cycle_face(1)   # SOUTH -> WEST -> NORTH
    p = RecordingPainter()
    av.draw_static(p, G, av.Scene(arena))
    bodies, stripes = bodies_and_stripes(p)
    assert len(bodies) == 1 and len(stripes) == 1
    assert bodies[0][0] == G.rect(50, 90, 10, 10)
    assert_stripe_on("NORTH", bodies[0], stripes[0])


def layer_of(name, args, kwargs, size):
    """The drawing layer a call belongs to, or None for calls that do not define one."""
    if name == "rect":
        if kwargs.get("fill") == av.PAPER and args == (0, 0, size, size):
            return "paper"
        if kwargs.get("fill") == av.START_FILL:
            return "start zone"
        if kwargs.get("fill") in (av.INK, av.FACE):
            return "obstacles"
        if kwargs.get("outline") == av.INK and kwargs.get("fill") is None:
            return "border"
    if name == "line":
        return {av.GRID_MINOR: "minor grid", av.GRID_MAJOR: "major grid"}.get(kwargs.get("fill"))
    if name == "text" and kwargs.get("fill") == av.MUTED:
        return "axis labels"
    return None


def test_static_layers_are_drawn_back_to_front():
    arena = load(os.path.join(TESTDATA, "02-four-obstacles.json"))
    p = RecordingPainter()
    av.draw_static(p, G, av.Scene(arena))
    layers = [layer_of(name, args, kwargs, G.arena_px) for name, args, kwargs in p.calls]
    assert [key for key, _ in groupby(l for l in layers if l is not None)] == [
        "paper", "minor grid", "major grid", "start zone", "obstacles", "border", "axis labels"]


def test_unreachable_obstacle_uses_warning_style_and_reason():
    arena = load(os.path.join(TESTDATA, "03-unreachable.json"))
    p = RecordingPainter()
    av.draw_static(p, G, av.Scene(arena, unreachable={13: "NO_OBJECTIVES"}))
    warned = [r for r in calls(p, "rect") if r[1].get("outline") == av.FACE and r[1].get("dash")]
    assert len(warned) == 1
    assert any(t[0][2] == "NO_OBJECTIVES" for t in calls(p, "text"))


def test_car_is_drawn_at_the_pose_and_trail_uses_segment_colours():
    arena = empty().add(5, 9)
    pose = Pose(60, 40, 90)
    trail = ((Pose(15, 16, 0), 0), (Pose(15, 17, 0), 0))
    remaining = ((Pose(15, 18, 0), 1), (Pose(15, 19, 0), 1))
    p = RecordingPainter()
    av.draw_dynamic(p, G, av.Scene(arena, pose=pose, trail=trail, remaining=remaining,
                                    colour_of={1: av.segment_colour(0)}))
    polys = calls(p, "polygon")
    assert len(polys) == 5                      # body + 4 wheels
    ovals = calls(p, "oval")
    assert len(ovals) == 1 and ovals[0][1]["fill"] == av.CAMERA
    ox0, oy0, ox1, oy1 = ovals[0][0]
    assert (ox0 + ox1) / 2 > G.to_canvas(60, 40)[0]        # camera is east of the centre
    lines = calls(p, "line")
    assert any(l[1]["fill"] == av.segment_colour(0) for l in lines)
    assert any(l[1]["fill"] == av.PLANNED and l[1].get("dash") for l in lines)


def test_dynamic_draws_the_start_pose_when_there_is_no_route():
    p = RecordingPainter()
    av.draw_dynamic(p, G, av.Scene(empty()))
    assert len(calls(p, "polygon")) == 5 and len(calls(p, "line")) == 0


def test_segment_colours_cycle():
    assert av.segment_colour(0) == av.SEGMENT_COLOURS[0]
    assert av.segment_colour(8) == av.SEGMENT_COLOURS[0]


def test_capture_ring_is_drawn_only_while_capturing():
    arena = empty().add(5, 9)
    with_ring = RecordingPainter()
    av.draw_dynamic(with_ring, G, av.Scene(arena, capturing=1))
    rings = [r for r in calls(with_ring, "rect") if r[1].get("outline") == av.START_EDGE]
    assert len(rings) == 1
    x0, y0, x1, y1 = rings[0][0]
    bx0, by0, bx1, by1 = G.rect(50, 90, 10, 10)
    assert x0 < bx0 and y0 < by0 and x1 > bx1 and y1 > by1
    without = RecordingPainter()
    av.draw_dynamic(without, G, av.Scene(arena))
    assert not [r for r in calls(without, "rect") if r[1].get("outline") == av.START_EDGE]
