from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

import config
from pathfinding.world.world import World, Obstacle, Robot
from pathfinding.world.primitives import Direction, Point
from simulator.arena_view import ArenaView
from simulator.playback import Playback
from simulator.routes import ROUTE_SOURCES, Route
from simulator import geometry


SPEED_TO_DELAY_MS = {
    "0.5x": 40,
    "1x": 20,
    "2x": 10,
    "4x": 5,
}


class SimulatorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("MDP Algorithms Simulator")
        self.obstacles = self._load_default_obstacles()
        self.world: World | None = None
        self.route: Route | None = None
        self.playback: Playback | None = None
        self.timer_handle = None

        self.route_sources = ROUTE_SOURCES
        self.route_source = tk.StringVar(value=self.route_sources[0].name)
        self.speed = tk.StringVar(value="1x")
        self.keep_out_visible = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Ready.")
        self.summary = tk.StringVar(value="Plan a route to begin.")

        self._build_widgets()
        self._set_world()
        self._redraw()

    def _build_widgets(self) -> None:
        outer = ttk.Frame(self.root, padding=10)
        outer.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(outer, width=geometry.ARENA_PX, height=geometry.ARENA_PX, background="white", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.view = ArenaView(self.canvas)
        # canvas mouse bindings for add/cycle/delete
        self.canvas.bind("<Button-1>", self._on_left_click)
        self.canvas.bind("<Button-3>", self._on_right_click)

        side = ttk.Frame(outer, padding=(12, 0, 0, 0))
        side.grid(row=0, column=1, sticky="ns")

        ttk.Label(side, text="Route Source").grid(row=0, column=0, sticky="w")
        self.source_box = ttk.Combobox(side, textvariable=self.route_source, values=[s.name for s in self.route_sources], state="readonly", width=24)
        self.source_box.grid(row=1, column=0, sticky="ew", pady=(2, 12))

        self.keep_out_check = ttk.Checkbutton(side, text="Keep-out overlay", variable=self.keep_out_visible, command=self._redraw)
        self.keep_out_check.grid(row=2, column=0, sticky="w", pady=(0, 12))

        ttk.Label(side, text="Obstacles").grid(row=3, column=0, sticky="w")
        self.obstacles_list = tk.Listbox(side, height=8, width=30, exportselection=False)
        self.obstacles_list.grid(row=4, column=0, sticky="ew", pady=(2, 6))
        self.obstacles_list.bind("<<ListboxSelect>>", self._select_obstacle)
        self.selected_index: int | None = None

        ttk.Label(side, text="Visited Obstacles").grid(row=5, column=0, sticky="w", pady=(10, 0))
        self.visited_list = tk.Listbox(side, height=8, width=30, exportselection=False)
        self.visited_list.grid(row=6, column=0, sticky="ew", pady=(2, 6))

        controls = ttk.Frame(outer, padding=(0, 10, 0, 0))
        controls.grid(row=1, column=0, columnspan=2, sticky="ew")

        self.plan_button = ttk.Button(controls, text="Plan", command=self.plan)
        self.play_button = ttk.Button(controls, text="Play", command=self.toggle_play)
        self.step_button = ttk.Button(controls, text="Step", command=self.step)
        self.reset_button = ttk.Button(controls, text="Reset", command=self.reset)

        self.plan_button.grid(row=0, column=0, padx=(0, 6))
        self.play_button.grid(row=0, column=1, padx=6)
        self.step_button.grid(row=0, column=2, padx=6)
        self.reset_button.grid(row=0, column=3, padx=6)

        ttk.Label(controls, text="Speed").grid(row=0, column=4, padx=(18, 4))
        self.speed_box = ttk.Combobox(controls, textvariable=self.speed, values=list(SPEED_TO_DELAY_MS), state="readonly", width=6)
        self.speed_box.grid(row=0, column=5)

        ttk.Label(controls, textvariable=self.summary).grid(row=0, column=7, sticky="e")
        ttk.Label(outer, textvariable=self.status).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))

    def _load_default_obstacles(self) -> list[Obstacle]:
        fixture = Path(__file__).resolve().parents[1] / "testdata" / "02-four-obstacles.json"
        data = json.loads(fixture.read_text())
        return [
            Obstacle(
                Direction(item["direction"]),
                Point(item["south_west"]["x"], item["south_west"]["y"]),
                Point(item["north_east"]["x"], item["north_east"]["y"]),
                item["image_id"],
            )
            for item in data["obstacles"]
        ]

    def _robot(self) -> Robot:
        pose = config.START_POSE
        return Robot(Direction(pose["direction"]), Point(*pose["south_west"]), Point(*pose["north_east"]))

    def _set_world(self) -> None:
        self.world = World(config.GRID_SIZE, self._robot(), list(self.obstacles))
        # refresh listbox whenever world changes
        self._update_obstacles_list()

    def plan(self) -> None:
        self.plan_button.configure(state="disabled")
        self.status.set("Planning...")
        self.root.update_idletasks()
        try:
            self._set_world()
            source = next(s for s in self.route_sources if s.name == self.route_source.get())
            self.route = source.plan(self.world)
            self.playback = Playback(self.route)
            self.status.set(f"Planned with {self.route.source_name} ({len(self.route.segments)} segments, {int(self.route.plan_ms)} ms)")
            self.summary.set(f"Planned in {int(self.route.plan_ms)} ms")
        except Exception as e:
            self.status.set(f"Planning failed: {e}")
            self.route = None
            self.playback = None
        finally:
            self.plan_button.configure(state="normal")
            self._redraw()

    def toggle_play(self) -> None:
        if self.timer_handle is not None:
            self.root.after_cancel(self.timer_handle)
            self.timer_handle = None
            self.play_button.configure(text="Play")
            return

        if self.playback is None:
            self.plan()
            if self.playback is None:
                return

        if self.playback.finished:
            self.playback.reset()

        self.play_button.configure(text="Pause")
        self._tick()

    def _tick(self) -> None:
        if self.playback is None:
            return
        frame = self.playback.step()
        if frame is None:
            self.play_button.configure(text="Play")
            self.status.set("Playback finished.")
            return
        self._redraw()
        self.timer_handle = self.root.after(SPEED_TO_DELAY_MS[self.speed.get()], self._tick)

    def step(self) -> None:
        if self.playback is None:
            self.plan()
            if self.playback is None:
                return
        frame = self.playback.step()
        if frame is None:
            self.status.set("Playback finished.")
        self._redraw()

    def reset(self) -> None:
        if self.playback is not None:
            self.playback.reset()
        self._redraw()

    def _redraw(self) -> None:
        self.view.clear()
        self.view.draw_grid()
        self.view.draw_start_zone()
        if self.world and self.keep_out_visible.get():
            self.view.draw_keep_out(self.world)

        # draw trail
        if self.playback is not None:
            trail = [(f.vector, f.segment_index) for f in self.playback.frames[: self.playback.index]]
            self.view.draw_trail(trail)

        # obstacles
        unreachable_map = {u.image_id: 'NO_OBJECTIVES' for u in (self.route.unreachable if self.route else [])}
        for obs in self.obstacles:
            self.view.draw_obstacle(obs, unreachable_map.get(obs.image_id))

        # robot
        if self.playback is not None and self.playback.current is not None:
            self.view.draw_robot(self.playback.current.vector, self.world.robot)
        else:
            self.view.draw_robot(self.world.robot.vector, self.world.robot)

        # update obstacle list display
        self._update_obstacles_list()
        self._update_visited_list()

    def _select_obstacle(self, event) -> None:
        sel = self.obstacles_list.curselection()
        if not sel:
            self.selected_index = None
            return
        self.selected_index = sel[0]
        # ensure selection visible on canvas by redrawing (could highlight later)
        self._redraw()

    def _update_obstacles_list(self) -> None:
        # repopulate listbox with current obstacles
        self.obstacles_list.delete(0, tk.END)
        for i, o in enumerate(self.obstacles):
            sw = o.south_west
            self.obstacles_list.insert(tk.END, f"{o.image_id}: ({sw.x},{sw.y}) {o.direction.name}")

    def _update_visited_list(self) -> None:
        self.visited_list.delete(0, tk.END)
        if self.playback is None:
            return

        seen: list[int] = []
        for image_id in self.playback.recognised:
            if image_id not in seen:
                seen.append(image_id)

        for image_id in seen:
            self.visited_list.insert(tk.END, f"{image_id}")

    def _find_obstacle_at(self, x_cm: int, y_cm: int) -> int | None:
        for i, o in enumerate(self.obstacles):
            if o.south_west.x <= x_cm <= o.north_east.x and o.south_west.y <= y_cm <= o.north_east.y:
                return i
        return None

    def _on_left_click(self, event) -> None:
        x_cm, y_cm = geometry.to_arena(event.x, event.y)
        idx = self._find_obstacle_at(x_cm, y_cm)
        if idx is not None:
            # cycle face
            self._cycle_face(idx)
            return

        # add new obstacle snapped to grid
        sw_x = geometry.snap(x_cm, geometry.GRID_STEP_CM)
        sw_y = geometry.snap(y_cm, geometry.GRID_STEP_CM)
        size = 10
        ne_x = sw_x + size - 1
        ne_y = sw_y + size - 1

        # validations: inside arena
        if sw_x < 0 or sw_y < 0 or ne_x >= config.ARENA_SIZE_CM or ne_y >= config.ARENA_SIZE_CM:
            messagebox.showinfo("Place obstacle", "Cannot place obstacle: outside arena bounds.")
            return

        # reject overlap with start zone
        if sw_x < config.START_ZONE_CM and sw_y < config.START_ZONE_CM:
            messagebox.showinfo("Place obstacle", "Cannot place obstacle: overlaps start zone.")
            return

        # reject overlap with existing obstacles
        for o in self.obstacles:
            if not (ne_x < o.south_west.x or sw_x > o.north_east.x or ne_y < o.south_west.y or sw_y > o.north_east.y):
                messagebox.showinfo("Place obstacle", "Cannot place obstacle: would overlap existing obstacle.")
                return

        # find lowest unused image id
        used = {o.image_id for o in self.obstacles}
        image_id = None
        for iid in range(config.IMAGE_ID_MIN, config.IMAGE_ID_MAX + 1):
            if iid not in used:
                image_id = iid
                break
        if image_id is None:
            messagebox.showinfo("Place obstacle", "Cannot place obstacle: no image IDs available.")
            return

        new = Obstacle(Direction("SOUTH"), Point(sw_x, sw_y), Point(ne_x, ne_y), image_id)
        self.obstacles.append(new)
        self._set_world()
        self._redraw()

    def _on_right_click(self, event) -> None:
        x_cm, y_cm = geometry.to_arena(event.x, event.y)
        idx = self._find_obstacle_at(x_cm, y_cm)
        if idx is None:
            return
        o = self.obstacles[idx]
        if messagebox.askyesno("Remove obstacle", f"Remove obstacle {o.image_id}?"):
            del self.obstacles[idx]
            self._set_world()
            self._redraw()

    def _cycle_face(self, idx: int) -> None:
        o = self.obstacles[idx]
        # cycle N->E->S->W
        order = ["NORTH", "EAST", "SOUTH", "WEST"]
        try:
            i = order.index(o.direction.name)
        except ValueError:
            i = 2
        new_dir = Direction(order[(i + 1) % len(order)])
        self.obstacles[idx] = Obstacle(new_dir, o.south_west, o.north_east, o.image_id)
        self._set_world()
        self._redraw()


def main() -> None:
    root = tk.Tk()
    app = SimulatorApp(root)
    root.mainloop()
