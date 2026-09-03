"""
Drawing the arena. Pure: a Scene in, painter calls out. Nothing here holds state or imports tk.

The look is graph paper with a car: green-lined paper, ink obstacles with a red mark on the
image face, and a top-down car with wheels and a camera dot so turns are visible without a
separate heading arrow.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import groupby

import config
from pathfinding.world.primitives import Direction
from pathfinding.world.world import Obstacle, Robot
from simulator.arena import Arena
from simulator.geometry import HEADING_DEG, Geometry, Pose, car_shapes
from simulator.painters import Painter

PAPER, GRID_MINOR, GRID_MAJOR = "#FDFDFA", "#D5E8DC", "#A8CDB6"
INK, MUTED, WINDOW, PANEL, RULE = "#1B2A2F", "#6A7A7E", "#F7F7F2", "#FFFFFF", "#E3E7E1"
START_FILL, START_EDGE = "#E8F1EA", "#2A9D6B"
FACE, CAMERA, PLANNED, BODY_FILL = "#E4572E", "#2457A8", "#9AA5A8", "#FFFFFF"
SEGMENT_COLOURS = ("#2457A8", "#E4572E", "#2A9D6B", "#8E5AC8", "#D99A00", "#0E9AA7", "#C2185B", "#7A5230")

AXIS_MARGIN_PX = 26
GRID_MINOR_CM, GRID_MAJOR_CM = 10, 50
# The image-face stripe is sized in CENTIMETRES, not pixels: 1.5 cm is about 5 px at the default
# scale, and sizing it in cm keeps it in proportion when the canvas is resized for the screen.
FACE_STRIPE_CM = 1.5
RING_INSET_CM = 3            # gap between an obstacle and its capture ring


def segment_colour(index: int) -> str:
    return SEGMENT_COLOURS[index % len(SEGMENT_COLOURS)]


@dataclass(frozen=True)
class Scene:
    arena: Arena
    colour_of: dict[int, str] = field(default_factory=dict)      # image_id -> segment colour
    unreachable: dict[int, str] = field(default_factory=dict)    # image_id -> reason
    captured: frozenset[int] = frozenset()
    next_id: int | None = None
    pose: Pose | None = None
    trail: tuple[tuple[Pose, int], ...] = ()
    remaining: tuple[tuple[Pose, int], ...] = ()
    capturing: int | None = None                                 # image_id being photographed now


def scene_of(arena: Arena, route, playback) -> Scene:
    """
    The one place a Scene is assembled from a route and a playback, so the window and the PNG
    snapshot can never disagree about what a frame looks like. `route` and `playback` may be None.
    """
    if route is None or playback is None:
        return Scene(arena)
    current = playback.current
    return Scene(
        arena,
        colour_of={s.image_id: segment_colour(i) for i, s in enumerate(route.segments)},
        unreachable={u.image_id: u.reason.value for u in route.unreachable},
        captured=frozenset(i for i, _ in playback.captured),
        next_id=playback.next_id,
        pose=current.pose if current else None,
        trail=tuple(playback.trail),
        remaining=tuple(playback.remaining),
        capturing=current.captured_id if current and current.dwell else None,
    )


def draw_static(p: Painter, g: Geometry, scene: Scene) -> None:
    size = g.arena_px
    p.rect(0, 0, size, size, fill=PAPER)
    # Layered, not interleaved: every minor line goes down first and every major line on top of
    # them, so a major line is never nicked where a later minor line crosses it.
    for cm in range(0, g.arena_cm + 1, GRID_MINOR_CM):
        if cm % GRID_MAJOR_CM == 0:
            continue
        _grid_lines(p, g, cm, GRID_MINOR, 0.8)
    for cm in range(0, g.arena_cm + 1, GRID_MAJOR_CM):
        _grid_lines(p, g, cm, GRID_MAJOR, 1.2)
    zone = config.START_ZONE_CM
    p.rect(*g.rect(0, 0, zone, zone), fill=START_FILL, outline=START_EDGE, width=1.5, dash=(6, 4))
    zx, zy = g.to_canvas(zone / 2, 3)
    p.text(zx, zy, "start", fill=START_EDGE, size=10, mono=True, anchor="s")
    for obstacle in scene.arena.obstacles:
        _draw_obstacle(p, g, obstacle, scene)
    p.rect(0, 0, size, size, outline=INK, width=2)
    for cm in range(0, g.arena_cm + 1, GRID_MAJOR_CM):
        x, _ = g.to_canvas(cm, 0)
        _, y = g.to_canvas(0, cm)
        # The first and last labels sit at the arena's corners, where a centred anchor would
        # clip off the canvas and the two axes would collide. Anchor those inward instead.
        x_anchor = "nw" if cm == 0 else "ne" if cm == g.arena_cm else "n"
        y_anchor = "sw" if cm == 0 else "nw" if cm == g.arena_cm else "w"
        p.text(x, size + 4, str(cm), fill=MUTED, size=10, mono=True, anchor=x_anchor)
        p.text(size + 4, y, str(cm), fill=MUTED, size=10, mono=True, anchor=y_anchor)


def _grid_lines(p: Painter, g: Geometry, cm: int, colour: str, width: float) -> None:
    """One vertical and one horizontal grid line at the same distance from the origin."""
    size = g.arena_px
    x, _ = g.to_canvas(cm, 0)
    _, y = g.to_canvas(0, cm)
    p.line([(x, 0), (x, size)], fill=colour, width=width)
    p.line([(0, y), (size, y)], fill=colour, width=width)


def _draw_obstacle(p: Painter, g: Geometry, o: Obstacle, scene: Scene) -> None:
    side = o.clearance
    x0, y0, x1, y1 = g.rect(o.south_west.x, o.south_west.y, side, side)
    reason = scene.unreachable.get(o.image_id)
    if reason is not None:
        p.rect(x0, y0, x1, y1, fill=PAPER, outline=FACE, width=2, dash=(4, 3))
        label_colour = FACE
    else:
        p.rect(x0, y0, x1, y1, fill=INK)
        label_colour = PAPER
    stripe = FACE_STRIPE_CM
    sx, sy = o.south_west.x, o.south_west.y
    stripe_rect = {
        Direction.NORTH: g.rect(sx, sy + side - stripe, side, stripe),
        Direction.SOUTH: g.rect(sx, sy, side, stripe),
        Direction.EAST: g.rect(sx + side - stripe, sy, stripe, side),
        Direction.WEST: g.rect(sx, sy, stripe, side),
    }[o.direction]
    p.rect(*stripe_rect, fill=FACE)
    p.text((x0 + x1) / 2, (y0 + y1) / 2, str(o.image_id), fill=label_colour, size=12, bold=True)
    if reason is not None:
        p.text((x0 + x1) / 2, y1 + 3, reason, fill=FACE, size=9, mono=True, anchor="n")


def draw_dynamic(p: Painter, g: Geometry, scene: Scene) -> None:
    _draw_route(p, g, scene.remaining, planned=True)
    _draw_route(p, g, scene.trail, planned=False)
    robot = scene.arena.robot
    pose = scene.pose if scene.pose is not None else Pose(robot.centre.x, robot.centre.y, HEADING_DEG[robot.direction])
    _draw_car(p, g, robot, pose)
    if scene.capturing is not None:
        # The capture moment is what checklist B.2 is graded on, so the obstacle being
        # photographed gets a ring for as long as the robot dwells there.
        target = scene.arena.find(scene.capturing)
        if target is not None:
            side = target.clearance
            inset = RING_INSET_CM
            p.rect(*g.rect(target.south_west.x - inset, target.south_west.y - inset,
                           side + 2 * inset, side + 2 * inset), outline=START_EDGE, width=2)


def _draw_route(p: Painter, g: Geometry, poses: tuple[tuple[Pose, int], ...], *, planned: bool) -> None:
    """One line per segment: `planned` draws the route not yet driven, otherwise the trail."""
    for index, group in groupby(poses, key=lambda item: item[1]):
        points = [g.to_canvas(pose.x, pose.y) for pose, _ in group]
        if len(points) < 2:
            continue
        if planned:
            p.line(points, fill=PLANNED, width=2, dash=(5, 6))
        else:
            p.line(points, fill=segment_colour(index), width=3)


def _draw_car(p: Painter, g: Geometry, robot: Robot, pose: Pose) -> None:
    cx, cy = pose.x, pose.y
    half = robot.clearance / 2
    p.rect(*g.rect(cx - half, cy - half, robot.clearance, robot.clearance), outline=MUTED, width=1, dash=(3, 3))
    car = car_shapes(pose)
    # Wheels before the body on purpose: the body then covers the inner 0.5 cm of each wheel, so
    # the wheels read as tyres poking out of the chassis rather than as four detached blocks.
    for wheel in car.wheels:
        p.polygon([g.to_canvas(x, y) for x, y in wheel], fill=INK)
    p.polygon([g.to_canvas(x, y) for x, y in car.body], fill=BODY_FILL, outline=INK, width=2)
    x, y, r = car.camera
    p.oval(*g.rect(x - r, y - r, 2 * r, 2 * r), fill=CAMERA)
