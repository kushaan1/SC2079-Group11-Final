import math
import os

import pytest

import config
from pathfinding.search.instructions import Turn
from simulator.arena import load
from simulator.geometry import HEADING_DEG
from simulator.playback import CAPTURE_DWELL_FRAMES, Playback
from simulator.routes import GreedyRouteSource, Route

TESTDATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testdata")


def route_for(name):
    return GreedyRouteSource().plan(load(os.path.join(TESTDATA, name)).world())


def unwrap(headings):
    """Compass headings to a continuous sequence, so a turn through north still reads monotonic."""
    out = [headings[0]]
    for h in headings[1:]:
        out.append(out[-1] + ((h - out[-1] + 180) % 360) - 180)
    return out


def test_frames_are_cells_plus_dwell():
    route = route_for("02-four-obstacles.json")
    p = Playback(route)
    cells = sum(len(s.vectors) for s in route.segments)
    assert len(p.frames) == cells + CAPTURE_DWELL_FRAMES * len(route.segments)
    assert p.index == 0 and p.current is p.frames[0] and not p.finished


def test_capture_sits_on_each_segments_last_cell_then_dwells():
    route = route_for("02-four-obstacles.json")
    p = Playback(route)
    captures = [(i, f) for i, f in enumerate(p.frames) if f.captured_id is not None and not f.dwell]
    assert [f.captured_id for _, f in captures] == [s.image_id for s in route.segments]
    for i, f in captures:
        dwell = p.frames[i + 1:i + 1 + CAPTURE_DWELL_FRAMES]
        assert all(d.dwell and d.pose == f.pose and d.captured_id == f.captured_id for d in dwell)
    assert p.frames[captures[0][0] - 1].segment_index == 0


def test_distance_excludes_dwell_and_clock_adds_capture_time():
    route = route_for("02-four-obstacles.json")
    p = Playback(route)
    p.seek(len(p.frames) - 1)
    assert p.distance_cm == pytest.approx(route.total_cost * route.cell_size)
    # The clock comes from the time model, not from distance over speed: a turn is charged
    # config.TURN_TIME_S however few centimetres of arc it covers.
    assert p.estimated_seconds == pytest.approx(
        route.seconds + len(route.segments) * config.CAPTURE_DWELL_S)
    assert p.estimated_seconds > p.distance_cm / config.ROBOT_SPEED_CM_S

    first_capture = next(i for i, f in enumerate(p.frames) if f.captured_id is not None)
    p.seek(first_capture - 1)
    assert p.captured == []
    p.seek(first_capture)
    held = p.distance_cm
    assert len(p.captured) == 1                     # the capture lands on arrival
    for _ in range(CAPTURE_DWELL_FRAMES):
        p.step()
    assert p.distance_cm == held                    # the dwell drives nowhere
    assert p.frames[p.index].seconds == p.frames[first_capture].seconds   # nor does it drive time
    assert len(p.captured) == 1
    assert p.next_id == route.segments[1].image_id


def test_step_to_the_end_then_noop():
    p = Playback(route_for("01-single-obstacle.json"))
    n = 0
    while p.step() is not None:
        n += 1
    assert n == len(p.frames) - 1 and p.finished and p.step() is None
    assert [i for i, _ in p.captured] == [11]
    assert p.remaining == []
    assert len(p.trail) == sum(len(s.vectors) for s in p.route.segments)
    assert p.next_id is None


def test_reset_and_seek_clamp():
    p = Playback(route_for("01-single-obstacle.json"))
    p.seek(10 ** 6)
    assert p.finished
    p.seek(-5)
    assert p.index == 0
    p.step(); p.step()
    p.reset()
    assert p.index == 0 and p.captured == [] and p.distance_cm == p.frames[0].distance_cm


def test_trail_and_remaining_partition_the_cells():
    p = Playback(route_for("02-four-obstacles.json"))
    p.seek(300)
    cells = sum(len(s.vectors) for s in p.route.segments)
    assert len(p.trail) + len(p.remaining) == cells
    assert p.trail[-1][0] == p.current.pose


def test_playback_is_continuous():
    p = Playback(route_for("02-four-obstacles.json"))
    cells = [f for f in p.frames if not f.dwell]
    for a, b in zip(cells, cells[1:]):
        gap = math.hypot(b.pose.x - a.pose.x, b.pose.y - a.pose.y)
        if a.segment_index == b.segment_index:
            assert gap <= 2.5, (a.segment_index, a.pose, b.pose)
        else:
            assert gap <= 1.5, (a.segment_index, a.pose, b.pose)   # a capture, then straight on


def test_heading_rotates_through_a_turn():
    route = route_for("02-four-obstacles.json")
    p = Playback(route)
    start, turn = 0, None
    for move in route.segments[0].moves:
        if isinstance(move, Turn):
            turn = move
            break
        start += len(move.vectors)
    assert turn is not None and start > 0
    arc = p.frames[start - 1:start + len(turn.vectors)]        # the frame before, the arc, the end pose
    headings = unwrap([f.pose.heading_deg for f in arc])
    deltas = [b - a for a, b in zip(headings, headings[1:])]
    assert all(d > 0 for d in deltas) or all(d < 0 for d in deltas), deltas
    assert math.isclose(abs(headings[-1] - headings[0]), 90)
    assert p.frames[start + len(turn.vectors) - 1].pose.heading_deg == HEADING_DEG[turn.vectors[-1].direction]


def test_next_id_is_the_first_unvisited_segment():
    route = route_for("02-four-obstacles.json")
    p = Playback(route)
    assert p.next_id == route.segments[0].image_id
    p.seek(len(p.frames) - 1)
    assert p.next_id is None


def test_empty_route():
    p = Playback(Route(segments=[], unreachable=[], source_name="none", plan_ms=0.0))
    assert p.frames == [] and p.current is None and p.finished and p.step() is None
    assert p.distance_cm == 0 and p.estimated_seconds == 0.0 and p.captured == [] and p.next_id is None
    assert p.trail == [] and p.remaining == []


def _turns(playback):
    """(start_deg, end_deg, frames) for every turn in the route, in order."""
    from pathfinding.search.instructions import Turn
    out = []
    i = 0
    for seg_index, segment in enumerate(playback.route.segments):
        for move in segment.moves:
            n = len(move.vectors)
            if isinstance(move, Turn):
                out.append(playback.frames[i:i + n])
            i += n
        i += CAPTURE_DWELL_FRAMES
    return out


def test_arc_frames_lie_on_a_circle_of_the_turn_radius():
    import math
    p = Playback(route_for("02-four-obstacles.json"))
    lead = p.route.robot.south_length - config.TURN_PIVOT_OFFSET_CM // p.route.cell_size
    for frames in _turns(p):
        # rear point of every arc frame (frame pose minus lead along heading)
        rears = []
        for f in frames[:-1]:
            t = math.radians(f.pose.heading_deg)
            rears.append((f.pose.x - lead * math.sin(t), f.pose.y - lead * math.cos(t)))
        (x0, y0), (x1, y1) = rears[0], rears[-1]
        r = max(abs(x1 - x0), abs(y1 - y0))
        assert 30 <= r <= 45
        # The centre is offset from the first rear point perpendicular to the INITIAL heading. The
        # first arc frame is already one step into the sweep, so snap its heading back to the
        # compass point it came from before asking which way the offset goes.
        start = round(frames[0].pose.heading_deg / 90) * 90 % 360
        first_heading_is_vertical = start % 180 == 0
        cx, cy = (x0 + (x1 - x0), y0) if first_heading_is_vertical else (x0, y0 + (y1 - y0))
        for rx, ry in rears:
            assert math.isclose(math.hypot(rx - cx, ry - cy), r, abs_tol=0.6), (cx, cy, r, rx, ry)


def test_arc_frames_step_evenly():
    import math
    p = Playback(route_for("02-four-obstacles.json"))
    for frames in _turns(p):
        steps = [math.hypot(b.pose.x - a.pose.x, b.pose.y - a.pose.y) for a, b in zip(frames, frames[1:])]
        assert max(steps) <= 1.25 and min(steps) >= 0.5, steps


def test_frame_seconds_are_cumulative_and_end_at_the_routes_estimate():
    route = route_for("02-four-obstacles.json")
    p = Playback(route)
    seconds = [f.seconds for f in p.frames]
    assert seconds == sorted(seconds)
    assert seconds[-1] == pytest.approx(route.seconds)
    # Each segment's last travelling frame stands at the running total of the segments so far.
    running = 0.0
    for index, segment in enumerate(route.segments):
        running += segment.seconds
        last = max(i for i, f in enumerate(p.frames) if f.segment_index == index)
        assert p.frames[last].seconds == pytest.approx(running)
