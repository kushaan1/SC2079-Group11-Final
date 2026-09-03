"""
Headless render of an arena to a PNG. This is how an agent with no display, or a README, gets a
picture of exactly what the window would draw: same Scene, same drawing code, a Pillow painter.
"""
from __future__ import annotations

from pathlib import Path

import config
from simulator import arena_view
from simulator.arena import Arena, load
from simulator.geometry import Geometry
from simulator.painters import PilPainter
from simulator.playback import Playback
from simulator.routes import SOURCES


def render(arena: Arena, *, frame: int | None, source_name: str | None, scale: float):
    from PIL import Image
    g = Geometry(scale=scale, arena_cm=config.ARENA_SIZE_CM)
    size = int(g.arena_px + arena_view.AXIS_MARGIN_PX)
    image = Image.new("RGB", (size, size), arena_view.WINDOW)
    painter = PilPainter(image)
    route = playback = None
    if arena.obstacles:
        source = next((s for s in SOURCES if s.name == source_name), SOURCES[0])
        route = source.plan(arena.world())
        playback = Playback(route)
        playback.seek(len(playback.frames) - 1 if frame is None else frame)
    scene = arena_view.scene_of(arena, route, playback)
    arena_view.draw_static(painter, g, scene)
    arena_view.draw_dynamic(painter, g, scene)
    return image


def write(arena_path: str | Path, out_path: str | Path, frame: int | None, scale: float,
          source_name: str | None = None) -> None:
    render(load(arena_path), frame=frame, source_name=source_name, scale=scale).save(out_path, "PNG")
