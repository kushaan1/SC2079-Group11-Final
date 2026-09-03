"""
The simulator window. Owns every piece of mutable state: the arena, the route, the playback,
the timer handle. Drawing is delegated to arena_view through a TkPainter; numbers come from
playback; rules come from arena. This file is wiring.

Planning, playback, arena editing with the mouse, and open/save of the RPi request JSON.
"""
from __future__ import annotations

import os
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

import config
from simulator import arena_view as av
from simulator.arena import Arena, ArenaError, empty, load, save
from simulator.fonts import Fonts
from simulator.geometry import Geometry, corners_to_cell, fit_scale, snap
from simulator.painters import TkPainter
from simulator.playback import Playback
from simulator.routes import SOURCES, Route, RouteSource

# The two canvas layers. The grid, the start zone and the obstacles are static; the route and
# the car are redrawn every animation frame.
STATIC, DYNAMIC = "static", "dynamic"

# Speed pills: label and milliseconds per frame. 1x is one centimetre every 20 ms.
SPEEDS = (("0.5x", 40), ("1x", 20), ("2x", 10), ("4x", 5))


def clock(seconds: float) -> str:
    """Seconds as m:ss. Used for the elapsed clock and for the time limit, so both agree."""
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"


class FlatButton(tk.Label):
    """A button drawn as a label so it looks the same on every platform (tk.Button ignores
    background colours on macOS). `primary` is ink-filled; otherwise a hairline outline."""

    def __init__(self, master, text, command, fonts: Fonts, primary=False):
        fill, fg = (av.INK, av.PANEL) if primary else (av.PANEL, av.INK)
        self.enabled_fg = fg
        super().__init__(master, text=text, font=fonts.ui(12), bg=fill, fg=fg, padx=12, pady=5,
                         cursor="hand2", highlightthickness=1, disabledforeground=av.MUTED,
                         highlightbackground=av.INK if primary else av.MUTED)
        self.command = command
        self.bind("<Button-1>", lambda _e: self.command() if self.command and self["state"] != "disabled" else None)

    def set_text(self, text):
        self.configure(text=text)

    def set_enabled(self, flag: bool) -> None:
        """Disabled means it looks dead too: dimmed text and the plain pointer, not a hand."""
        self.configure(state="normal" if flag else "disabled",
                       cursor="hand2" if flag else "arrow",
                       fg=self.enabled_fg if flag else av.MUTED)


class SimulatorApp:
    def __init__(self, root: tk.Tk, arena_path: str | None) -> None:
        self.root = root
        root.title("MDP simulator")
        root.configure(bg=av.WINDOW)
        self.fonts = Fonts(root)
        # Scale is a runtime value: the arena is sized to the screen it is being demoed on.
        self.geometry = Geometry(fit_scale(root.winfo_screenheight(), config.ARENA_SIZE_CM), config.ARENA_SIZE_CM)
        self.arena: Arena = load(arena_path) if arena_path else empty()

        self.route: Route | None = None
        self.playback: Playback | None = None
        self.source: RouteSource = SOURCES[0]
        self.source_var = tk.StringVar(value=self.source.name)
        self.speed_ms = SPEEDS[1][1]             # 1x
        self.timer: str | None = None            # the root.after handle while playing
        self.captured_seen = 0                   # captures already reflected in the static layer
        self.drag: tuple[int, tuple[int, int]] | None = None   # (image_id, cell) under the mouse
        self.dragged = False                     # whether the press turned into a move
        self.suppress_release = False            # a control-click removal is followed by a release

        self.status_var = tk.StringVar(value="")
        self._build_layout()
        self.redraw_static()
        self.redraw_dynamic()
        self.on_speed(self.speed_ms)

        root.bind("<space>", lambda _e: self.on_play())
        root.bind("<Right>", lambda _e: self.on_step())
        root.bind("r", lambda _e: self.on_reset())
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.canvas.bind("<Button-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        # Right-click is Button-2 on macOS and Button-3 elsewhere; control-click for trackpads.
        for right in ("<Button-2>", "<Button-3>", "<Control-Button-1>"):
            self.canvas.bind(right, self.on_remove)

    # ----- layout -------------------------------------------------------------------------

    def _build_layout(self) -> None:
        size = int(self.geometry.arena_px + av.AXIS_MARGIN_PX)
        left = tk.Frame(self.root, bg=av.WINDOW, padx=14, pady=14)
        left.grid(row=0, column=0, sticky="nsew")
        self.canvas = tk.Canvas(left, width=size, height=size, bg=av.WINDOW, highlightthickness=0)
        self.canvas.pack()
        # The status line sits under the arena, where the clicks happen and where nothing can
        # starve it of space; packed last in the fixed-height panel it was the first thing clipped.
        self.status_label = tk.Label(left, textvariable=self.status_var, font=self.fonts.ui(11),
                                     bg=av.WINDOW, fg=av.MUTED, wraplength=size, justify="left", anchor="w")
        self.status_label.pack(fill="x", pady=(8, 0))
        self.static_painter = TkPainter(self.canvas, self.fonts, STATIC)
        self.dynamic_painter = TkPainter(self.canvas, self.fonts, DYNAMIC)

        self.panel = tk.Frame(self.root, bg=av.PANEL, width=300, padx=18, pady=16)
        self.panel.grid(row=0, column=1, sticky="nsew")
        # The panel's children are packed, so it is pack propagation that has to be turned off
        # for `width=300` to hold; grid_propagate would leave the panel as wide as its rows.
        self.panel.pack_propagate(False)
        self._build_panel()

        self.bar = tk.Frame(self.root, bg=av.PANEL, padx=18, pady=10,
                            highlightthickness=1, highlightbackground=av.RULE)
        self.bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        self._build_bar()
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

    def _build_panel(self) -> None:
        f = self.fonts
        # Two rows, not three buttons abreast: side by side they ask for 288 px (measured, Avenir
        # Next) against the panel's 264 px of content width, and pack silently clips the last one.
        plan_row = tk.Frame(self.panel, bg=av.PANEL)
        plan_row.pack(anchor="w", fill="x", pady=(0, 8))
        self.plan_button = FlatButton(plan_row, "Plan route", self.on_plan, f, primary=True)
        self.plan_button.pack(side="left")
        file_row = tk.Frame(self.panel, bg=av.PANEL)
        file_row.pack(anchor="w", fill="x", pady=(0, 16))
        FlatButton(file_row, "Open arena", self.on_open, f).pack(side="left", padx=(0, 8))
        FlatButton(file_row, "Save arena", self.on_save, f).pack(side="left")

        self._heading("Route")
        self.route_frame = tk.Frame(self.panel, bg=av.PANEL)
        self.route_frame.pack(fill="x", pady=(0, 16))
        self._heading("Obstacles, click the arena to add")
        self.obstacle_frame = tk.Frame(self.panel, bg=av.PANEL)
        self.obstacle_frame.pack(fill="x", pady=(0, 16))
        self._heading("Captured, in order")
        self.captured_frame = tk.Frame(self.panel, bg=av.PANEL)
        self.captured_frame.pack(fill="x")

    def _heading(self, text: str) -> None:
        tk.Label(self.panel, text=text, font=self.fonts.ui(11, bold=True), bg=av.PANEL, fg=av.MUTED,
                 anchor="w").pack(fill="x", pady=(0, 6))

    def _row(self, parent, left: str, right: str = "", *, chip: str | None = None,
             chip_colour: str = av.MUTED, right_colour: str = av.MUTED) -> None:
        """One panel row: optional coloured chip, left text, right-aligned mono text."""
        # Compact rows: eight obstacles plus eight captures must fit a 768 px laptop screen.
        row = tk.Frame(parent, bg=av.PANEL, highlightthickness=1, highlightbackground=av.RULE)
        row.pack(fill="x", pady=(0, 1))
        if chip is not None:
            tk.Label(row, text=chip, font=self.fonts.mono(11), bg=chip_colour, fg=av.PANEL,
                     padx=6).pack(side="left", padx=(0, 8), pady=2)
        tk.Label(row, text=left, font=self.fonts.ui(12), bg=av.PANEL, fg=av.INK, anchor="w").pack(side="left", pady=2)
        tk.Label(row, text=right, font=self.fonts.mono(11), bg=av.PANEL, fg=right_colour, anchor="e").pack(side="right", pady=2)

    def _build_bar(self) -> None:
        f = self.fonts
        self.play_button = FlatButton(self.bar, "Play", self.on_play, f, primary=True)
        self.play_button.pack(side="left", padx=(0, 8))
        FlatButton(self.bar, "Step", self.on_step, f).pack(side="left", padx=(0, 8))
        FlatButton(self.bar, "Reset", self.on_reset, f).pack(side="left", padx=(0, 16))

        pills = tk.Frame(self.bar, bg=av.PANEL)
        pills.pack(side="left", padx=(0, 12))
        self.speed_pills: list[tuple[tk.Label, int]] = []
        for label, ms in SPEEDS:
            pill = tk.Label(pills, text=label, font=f.mono(11), bg=av.PANEL, fg=av.MUTED, padx=8, pady=3,
                            cursor="hand2")
            pill.pack(side="left", padx=1)
            pill.bind("<Button-1>", lambda _e, ms=ms: self.on_speed(ms))
            self.speed_pills.append((pill, ms))

        self.clock_var = tk.StringVar(value=clock(0))
        self.count_var = tk.StringVar(value="")
        tk.Label(self.bar, textvariable=self.count_var, font=f.mono(12), bg=av.PANEL, fg=av.MUTED).pack(side="right")
        # The limit is read from config, not typed: if the rules change, the label changes with them.
        tk.Label(self.bar, text=f"est. of {clock(config.TASK_1_TIME_LIMIT_S)}", font=f.ui(11),
                 bg=av.PANEL, fg=av.MUTED).pack(side="right", padx=(4, 18))
        tk.Label(self.bar, textvariable=self.clock_var, font=f.mono(15), bg=av.PANEL, fg=av.INK).pack(side="right")

        # Packed last so it takes whatever width is left between the pills and the clock.
        self.scrub = tk.Scale(self.bar, orient="horizontal", showvalue=0, from_=0, to=0,
                              command=self.on_scrub, bg=av.PANEL, troughcolor=av.RULE,
                              highlightthickness=0, sliderrelief="flat", bd=0, length=200)
        self.scrub.pack(side="left", fill="x", expand=True, padx=(0, 16))

    # ----- drawing --------------------------------------------------------------------------

    def scene(self) -> av.Scene:
        return av.scene_of(self.arena, self.route, self.playback)

    def redraw_static(self) -> None:
        self.canvas.delete(STATIC)
        av.draw_static(self.static_painter, self.geometry, self.scene())
        self.canvas.tag_lower(STATIC)
        self.refresh_panel()

    def redraw_dynamic(self) -> None:
        self.canvas.delete(DYNAMIC)
        av.draw_dynamic(self.dynamic_painter, self.geometry, self.scene())
        self.canvas.tag_raise(DYNAMIC)

    def refresh_panel(self) -> None:
        for frame in (self.route_frame, self.obstacle_frame, self.captured_frame):
            for child in frame.winfo_children():
                child.destroy()

        for source in SOURCES:
            tk.Radiobutton(self.route_frame, text=source.name, variable=self.source_var, value=source.name,
                           command=self.on_source, font=self.fonts.ui(12), bg=av.PANEL, fg=av.INK,
                           activebackground=av.PANEL, selectcolor=av.PANEL, highlightthickness=0,
                           anchor="w").pack(fill="x")
        if self.route is not None:
            self._row(self.route_frame, "Total length", f"{self.route.total_cost * self.route.cell_size:,} cm")
            # Driving only. The transport clock adds the capture dwells on top, so the two
            # numbers differ by design and the bar is the one to compare against the limit.
            self._row(self.route_frame, "Driving time", clock(self.route.seconds))
            self._row(self.route_frame, "Planned in", f"{self.route.plan_ms / 1000:.1f} s")

        scene = self.scene()
        for o in self.arena.obstacles:
            # Positions are shown in tablet cells, the vocabulary the Android team uses.
            cx, cy = corners_to_cell(o.south_west)
            if o.image_id in scene.unreachable:
                chip_colour, state, state_colour = av.FACE, scene.unreachable[o.image_id], av.FACE
            elif o.image_id in scene.captured:
                chip_colour, state, state_colour = scene.colour_of[o.image_id], "captured", av.START_EDGE
            elif o.image_id == scene.next_id:
                chip_colour, state, state_colour = scene.colour_of[o.image_id], "next", av.MUTED
            else:
                chip_colour, state, state_colour = scene.colour_of.get(o.image_id, av.MUTED), "", av.MUTED
            self._row(self.obstacle_frame, f"({cx}, {cy}) faces {o.direction.value[0]}", state,
                      chip=str(o.image_id), chip_colour=chip_colour, right_colour=state_colour)

        captured = self.playback.captured if self.playback else []
        for image_id, seconds in captured:
            self._row(self.captured_frame, f"Obstacle {image_id}", clock(seconds))
        if not captured:
            hint = "Plays as the robot arrives at each image." if self.route else "Plan a route to begin."
            tk.Label(self.captured_frame, text=hint, font=self.fonts.ui(11), bg=av.PANEL, fg=av.MUTED,
                     anchor="w").pack(fill="x")

    def refresh_readouts(self) -> None:
        """The clock and the capture count in the transport bar."""
        if self.playback is None or self.route is None:
            self.clock_var.set(clock(0))
            self.count_var.set("")
            return
        self.clock_var.set(clock(self.playback.estimated_seconds))
        self.count_var.set(f"{len(self.playback.captured)} of {len(self.route.segments)}")

    # ----- messages ------------------------------------------------------------------------

    def status(self, text: str, error: bool = False) -> None:
        """The one place a message reaches the user. A refused edit is FACE; news is quiet."""
        self.status_var.set(text)
        self.status_label.configure(fg=av.FACE if error else av.MUTED)

    # ----- planning -----------------------------------------------------------------------

    def on_source(self) -> None:
        self.source = next(s for s in SOURCES if s.name == self.source_var.get())
        self.clear_route()

    def on_plan(self) -> None:
        self.stop_timer()
        self.plan_button.set_text("Planning...")
        self.plan_button.set_enabled(False)
        self.status("")
        self.root.update_idletasks()
        try:
            self.route = self.source.plan(self.arena.world())
        except Exception as error:                      # a planner bug must not kill the demo
            self.route = None
            self.status(f"Planning failed: {error}", error=True)
        finally:
            self.plan_button.set_text("Plan route")
            self.plan_button.set_enabled(True)
        self.playback = Playback(self.route) if self.route else None
        self.captured_seen = 0
        self.scrub.configure(to=max(0, len(self.playback.frames) - 1) if self.playback else 0)
        self.scrub.set(0)                        # a new route starts at frame 0; the echo is ignored
        self.redraw_static()
        self.redraw_dynamic()
        self.refresh_readouts()

    def clear_route(self) -> None:
        """Forget the route and playback; the arena is about to differ from what was planned."""
        self.stop_timer()
        self.route = self.playback = None
        self.captured_seen = 0
        self.scrub.configure(to=0)
        self.redraw_static()
        self.redraw_dynamic()
        self.refresh_readouts()

    # ----- transport ----------------------------------------------------------------------

    def on_play(self) -> None:
        if self.playback is None or self.playback.finished:
            return
        if self.timer is None:
            self.play_button.set_text("Pause")
            self.tick()
        else:
            self.stop_timer()

    def stop_timer(self) -> None:
        if self.timer is not None:
            self.root.after_cancel(self.timer)
            self.timer = None
        self.play_button.set_text("Play")

    def tick(self) -> None:
        self.timer = None
        if self.playback is None or self.playback.step() is None:
            self.stop_timer()
            return
        self.after_frame()
        self.timer = self.root.after(self.speed_ms, self.tick)

    def on_step(self) -> None:
        self.stop_timer()
        if self.playback and self.playback.step() is not None:
            self.after_frame()

    def on_reset(self) -> None:
        self.stop_timer()
        if self.playback:
            self.playback.reset()
            self.after_frame()

    def on_speed(self, ms: int) -> None:
        self.speed_ms = ms
        for pill, pill_ms in self.speed_pills:
            selected = pill_ms == ms
            pill.configure(bg=av.INK if selected else av.PANEL, fg=av.PANEL if selected else av.MUTED)

    def on_scrub(self, value: str) -> None:
        if self.playback is None:
            return
        target = int(float(value))
        # Tk delivers a Scale's command from an idle handler, so our own scrub.set() in
        # after_frame() echoes back here AFTER the guard flag was cleared. A flag cannot tell
        # the echo from a user drag; the value can: an echo always equals the current index.
        if target == self.playback.index:
            return
        self.stop_timer()
        self.playback.seek(target)
        self.after_frame()

    def after_frame(self) -> None:
        """Everything that changes between frames. The static layer redraws only on a capture."""
        captured_now = len(self.playback.captured)
        if captured_now != self.captured_seen:
            self.captured_seen = captured_now
            self.redraw_static()
        self.redraw_dynamic()
        self.scrub.set(self.playback.index)      # echoes into on_scrub later; ignored there
        self.refresh_readouts()

    def on_close(self) -> None:
        self.stop_timer()
        self.root.destroy()

    # ----- editing --------------------------------------------------------------------------

    def cell_at(self, event) -> tuple[int, int]:
        """The tablet cell under a mouse event."""
        x_cm, y_cm = self.geometry.to_arena(event.x, event.y)
        step = config.OBSTACLE_SIZE_CM
        return snap(x_cm, step) // step, snap(y_cm, step) // step

    def on_press(self, event) -> None:
        x_cm, y_cm = self.geometry.to_arena(event.x, event.y)
        hit = self.arena.at(x_cm, y_cm)
        self.drag = (hit.image_id, self.cell_at(event)) if hit else None
        self.dragged = False

    def on_drag(self, event) -> None:
        if self.drag is None:
            return
        image_id, origin = self.drag
        cell = self.cell_at(event)
        if cell != origin:
            self.dragged = True
            self.try_edit(lambda: self.arena.move(image_id, *cell))
            self.drag = (image_id, cell)

    def on_release(self, event) -> None:
        if self.suppress_release:
            # A control-click already removed an obstacle; without this the release would
            # read as a click on empty space and add one straight back.
            self.suppress_release = False
            self.drag = None
            return
        if self.drag is None:
            x_cm, y_cm = self.geometry.to_arena(event.x, event.y)
            if 0 <= x_cm < self.geometry.arena_cm and 0 <= y_cm < self.geometry.arena_cm:
                cell = self.cell_at(event)
                self.try_edit(lambda: self.arena.add(*cell))
        elif not self.dragged:
            image_id, _ = self.drag
            self.try_edit(lambda: self.arena.cycle_face(image_id))
        self.drag = None

    def on_remove(self, event) -> None:
        # Only button 1 (control-click) is followed by a <ButtonRelease-1>; buttons 2 and 3 are not.
        self.suppress_release = event.num == 1
        x_cm, y_cm = self.geometry.to_arena(event.x, event.y)
        hit = self.arena.at(x_cm, y_cm)
        if hit:
            self.try_edit(lambda: self.arena.remove(hit.image_id))

    def try_edit(self, edit) -> None:
        """Apply an arena edit, or show why it was refused. Any accepted edit drops the route."""
        try:
            new_arena = edit()
        except ArenaError as refused:
            self.status(f"Can't place there: {refused}.", error=True)
            return
        self.arena = new_arena
        self.status("")
        self.clear_route()

    # ----- files ----------------------------------------------------------------------------

    def on_open(self) -> None:
        path = filedialog.askopenfilename(initialdir="testdata", filetypes=[("Arena JSON", "*.json")])
        if not path:
            return
        try:
            self.arena = load(path)
        except (KeyError, TypeError, ValueError, OSError, AssertionError) as error:
            self.status(f"Couldn't open {Path(path).name}: {error or 'not a valid arena'}", error=True)
            return
        self.status(f"Opened {Path(path).name}")
        self.clear_route()

    def on_save(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".json", initialfile="arena.json",
                                            filetypes=[("Arena JSON", "*.json")])
        if not path:
            return
        try:
            save(path, self.arena)
        except OSError as error:
            self.status(f"Couldn't save {Path(path).name}: {error}", error=True)
            return
        self.status(f"Saved {Path(path).name}")


def _schedule_selftest(root: tk.Tk, app: SimulatorApp) -> None:
    """Drive the window without eyes: plan, play at 4x, step, reset and scrub, edit the arena,
    re-plan, then switch to the shortest-time source and plan and play that one too, then close.

    Set MDP_SELFTEST_RAISE=1 to raise inside a callback and prove the exception hook fails the run.
    """

    def drive() -> None:
        app.on_plan()
        app.on_speed(5)
        app.on_play()
        root.after(1500, poke)

    def poke() -> None:
        # Play must still be running on its own 1.5 s later: many frames in, timer armed.
        # (A short arena may legitimately have finished by now.)
        assert app.timer is not None or app.playback.finished, "playback stopped itself"
        assert app.playback.index > 20 or app.playback.finished, f"only {app.playback.index} frames after 1.5 s"
        app.on_step()
        app.on_reset()
        app.on_scrub("50")
        if os.environ.get("MDP_SELFTEST_RAISE") == "1":
            raise RuntimeError("selftest probe")
        root.after(100, edit)

    def edit() -> None:
        # Editing: an accepted add, a refused duplicate (status line, no exception), a face
        # cycle, a removal, then a fresh plan on the edited arena.
        before = len(app.arena.obstacles)
        app.try_edit(lambda: app.arena.add(10, 10))      # free in testdata 02
        assert len(app.arena.obstacles) == before + 1, app.status_var.get()
        app.try_edit(lambda: app.arena.add(10, 10))
        assert "overlaps" in app.status_var.get()
        last = app.arena.obstacles[-1].image_id
        app.try_edit(lambda: app.arena.cycle_face(last))
        app.try_edit(lambda: app.arena.remove(last))
        assert len(app.arena.obstacles) == before
        app.on_plan()
        root.after(100, optimal)

    def optimal() -> None:
        # The second source, end to end: switching clears the route, planning fills it again.
        # The plan runs inside this callback and blocks; that is what pressing the button does.
        app.source_var.set("Shortest time")
        app.on_source()
        assert app.route is None, "switching source must drop the old route"
        app.on_plan()
        assert app.route is not None, app.status_var.get()
        assert app.route.source_name == "Shortest time", app.route.source_name
        assert app.playback.frames, "optimal route has no frames"
        app.on_play()
        root.after(500, finish)

    def finish() -> None:
        try:
            app.stop_timer()
            assert app.playback.index > 0, "optimal route did not play"
            app.status("Selftest done.")
        finally:
            root.destroy()

    root.after(300, drive)


def run(arena_path: str | None, selftest: bool = False) -> int:
    root = tk.Tk()
    failures: list[BaseException] = []

    def report(exc_type, exc, tb) -> None:
        # Tk swallows exceptions raised inside after() callbacks and event handlers; without
        # this hook a broken selftest would print a traceback and then sit there forever.
        # In front of a supervisor the window must survive a bug, so it only closes in selftest.
        failures.append(exc)
        traceback.print_exception(exc_type, exc, tb)
        if selftest:
            root.destroy()
        else:
            app.status(f"Something went wrong: {exc_type.__name__}: {exc}", error=True)

    root.report_callback_exception = report
    app = SimulatorApp(root, arena_path)
    if selftest:
        _schedule_selftest(root, app)
    root.mainloop()
    return 1 if failures else 0
