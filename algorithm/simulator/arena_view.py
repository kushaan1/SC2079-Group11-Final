from __future__ import annotations

import tkinter as tk
from typing import List, Tuple

import config
from pathfinding.world.world import World, Obstacle, Robot
from pathfinding.world.primitives import Vector, Direction
from simulator import geometry


class ArenaView:
    def __init__(self, canvas: tk.Canvas) -> None:
        self.canvas = canvas

    def clear(self) -> None:
        self.canvas.delete("all")

    def draw_grid(self) -> None:
        # background and border
        self.canvas.create_rectangle(0, 0, geometry.ARENA_PX, geometry.ARENA_PX, fill="#f8fafc", outline="#0f172a", width=2)
        # grid lines every GRID_STEP_CM
        for cm in range(0, config.ARENA_SIZE_CM + 1, geometry.GRID_STEP_CM):
            x, _ = geometry.to_canvas(cm, 0)
            _, y = geometry.to_canvas(0, cm)
            major = (cm % 50) == 0
            colour = "#94a3b8" if major else "#d6dee9"
            width = 2 if major else 1
            self.canvas.create_line(x, 0, x, geometry.ARENA_PX, fill=colour, width=width)
            self.canvas.create_line(0, y, geometry.ARENA_PX, y, fill=colour, width=width)

    def draw_start_zone(self) -> None:
        x0, y0, x1, y1 = geometry.cell_rect(0, 0, config.START_ZONE_CM)
        self.canvas.create_rectangle(x0, y0, x1, y1, fill="#dcfce7", outline="#15803d", width=2)
        self.canvas.create_text((x0 + x1) / 2, (y0 + y1) / 2, text="START", fill="#14532d", font=("TkDefaultFont", 11, "bold"))

    def draw_keep_out(self, world: World) -> None:
        try:
            grid = world.grid
        except Exception:
            return
        size = world.size
        for x in range(0, size, 2):
            for y in range(0, size, 2):
                if not grid[x, y]:
                    x0, y0, x1, y1 = geometry.cell_rect(x, y, 2)
                    self.canvas.create_rectangle(x0, y0, x1, y1, fill="#fff5e6", outline="")

    def draw_obstacle(self, obstacle: Obstacle, unreachable_reason: str | None = None) -> None:
        x0, y0, x1, y1 = geometry.cell_rect(obstacle.south_west.x, obstacle.south_west.y, obstacle.clearance)
        fill = "#fecaca" if unreachable_reason is not None else "#cbd5e1"
        outline = "#991b1b" if unreachable_reason is not None else "#334155"
        self.canvas.create_rectangle(x0, y0, x1, y1, fill=fill, outline=outline, width=2)
        # draw image id
        cx = (x0 + x1) / 2
        cy = (y0 + y1) / 2
        self.canvas.create_text(cx, cy, text=str(obstacle.image_id), font=("TkDefaultFont", 10, "bold"))
        # face indicator: draw a short thick line on the face
        if obstacle.direction == Direction.NORTH:
            self.canvas.create_line(x0, y0, x1, y0, fill=outline, width=4)
        elif obstacle.direction == Direction.SOUTH:
            self.canvas.create_line(x0, y1, x1, y1, fill=outline, width=4)
        elif obstacle.direction == Direction.EAST:
            self.canvas.create_line(x1, y0, x1, y1, fill=outline, width=4)
        elif obstacle.direction == Direction.WEST:
            self.canvas.create_line(x0, y0, x0, y1, fill=outline, width=4)
        if unreachable_reason:
            self.canvas.create_text(cx, y1 + 12, text=str(unreachable_reason), fill="#991b1b", font=("TkDefaultFont", 9))

    def draw_trail(self, trail: List[Tuple[Vector, int]]) -> None:
        if not trail:
            return
        # group by segment index and draw each in a different colour
        seg_points = {}
        for v, si in trail:
            seg_points.setdefault(si, []).append(geometry.to_canvas(v.x, v.y))
        colours = ["#2196f3", "#8bc34a", "#ff9800", "#9c27b0", "#00bcd4"]
        for si, pts in seg_points.items():
            if len(pts) < 2:
                continue
            colour = colours[si % len(colours)]
            for start, end in zip(pts, pts[1:]):
                if not (isinstance(start, tuple) and isinstance(end, tuple)):
                    continue
                if len(start) != 2 or len(end) != 2:
                    continue
                try:
                    self.canvas.create_line(start[0], start[1], end[0], end[1], fill=colour, width=2)
                except tk.TclError as e:
                    print(f"arena_view.draw_trail: skipping segment {si} pair {start}->{end} due to TclError: {e}")

    def draw_robot(self, vector: Vector, robot: Robot) -> None:
        x, y = geometry.to_canvas(vector.x, vector.y)
        half = robot.clearance * geometry.SCALE_PX_PER_CM / 2
        # body
        self.canvas.create_rectangle(x - half, y - half, x + half, y + half, fill="#607d8b", outline="#263238", width=2)
        # heading triangle based on direction
        if vector.direction == Direction.NORTH:
            tri = [x, y - half - 8, x - 8, y - half + 8, x + 8, y - half + 8]
        elif vector.direction == Direction.SOUTH:
            tri = [x, y + half + 8, x - 8, y + half - 8, x + 8, y + half - 8]
        elif vector.direction == Direction.EAST:
            tri = [x + half + 8, y, x + half - 8, y - 8, x + half - 8, y + 8]
        else:  # WEST
            tri = [x - half - 8, y, x - half + 8, y - 8, x - half + 8, y + 8]
        self.canvas.create_polygon(*tri, fill="#ff5722")
        

