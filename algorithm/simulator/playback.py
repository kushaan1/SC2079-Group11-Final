"""
The animation timeline: the planner's moves turned into robot poses, with a pause at every
capture, plus the numbers the window shows (distance, estimated clock, captured list).

Two things have to be undone here before the cells can be animated. Both come from the way the
planner stores a turn.

1. Order. ``search.Segment.moves`` now hands over each turn's arc in driving order (the raw
   ``turn.__curve`` output is an interleaved collision-check set, not a path). This module relies
   on that ordering and does not re-sort anything.
2. Reference point and heading. An arc cell is the path of a point ``lead`` cm BEHIND the robot
   centre, and every arc cell carries the POST-turn heading. Played back as-is the car would
   never rotate. So the heading is swept evenly across the arc, and the centre is placed on the
   quarter circle those cells discretise rather than on the cells themselves -- the integer cells
   sit up to 1.2 cm off that circle and stair-step visibly.

Pure logic. Nothing here knows about tkinter or drawing.
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass

import config
from pathfinding.search.instructions import Turn, TurnInstruction
from simulator.geometry import HEADING_DEG, Pose, unit
from simulator.routes import Route

# Frames the robot holds still at each obstacle so the capture moment is visible. Display
# pacing, not a physical constant, so it lives here rather than in config.
CAPTURE_DWELL_FRAMES = 10

# The turns whose compass heading DECREASES: driving forward-left and reversing to the right
# both swing the nose anticlockwise. Used to recover the pre-turn heading from the post-turn
# one, which is all the planner records on an arc cell.
_ANTICLOCKWISE = (TurnInstruction.FORWARD_LEFT, TurnInstruction.BACKWARD_RIGHT)


@dataclass(frozen=True)
class Frame:
    pose: Pose
    segment_index: int
    captured_id: int | None      # set on a segment's last cell and its dwell frames
    dwell: bool                  # True for the repeated frames; they are not travel
    distance_cm: float           # cumulative, including this frame; dwell repeats the previous


class Playback:
    def __init__(self, route: Route) -> None:
        self.route = route
        self.frames: list[Frame] = []
        cell_size = route.cell_size
        # Call-time config read: the pivot fudge factor may be re-tuned between plans.
        lead = (route.robot.south_length - config.TURN_PIVOT_OFFSET_CM // cell_size
                if route.robot is not None else 0)
        distance = 0.0

        for index, segment in enumerate(route.segments):
            first = len(self.frames)
            for move in segment.moves:
                if isinstance(move, Turn):
                    *arc, end = move.vectors
                    end_deg = HEADING_DEG[end.direction]
                    start_deg = (end_deg + (90 if move.turn in _ANTICLOCKWISE else -90)) % 360
                    delta = ((end_deg - start_deg + 180) % 360) - 180
                    m = len(arc)
                    step = move.turn.arc_length(cell_size) * cell_size / (m + 1)
                    if m:
                        # The rear point rides a quarter circle between the arc's first and last
                        # cells. Its centre sits beside the first of them, perpendicular to the
                        # initial heading: offset along x when starting north/south, along y when
                        # starting east/west. Placing the frames on that circle instead of on the
                        # integer cells is what keeps a turn from stair-stepping.
                        x0, y0 = arc[0].x, arc[0].y
                        dx, dy = arc[-1].x - x0, arc[-1].y - y0
                        cx, cy = (x0 + dx, y0) if start_deg % 180 == 0 else (x0, y0 + dy)
                        phi0 = math.atan2(y0 - cy, x0 - cx)
                        phi1 = math.atan2(arc[-1].y - cy, arc[-1].x - cx)
                        sweep = ((phi1 - phi0 + math.pi) % (2 * math.pi)) - math.pi   # signed, +-pi/2
                        radius = math.hypot(x0 - cx, y0 - cy)
                        for k in range(m):
                            # The m arc frames plus the end frame divide the sweep into m + 1 equal
                            # steps, so the last arc frame is not a duplicate of the end pose.
                            t = (k + 1) / (m + 1)
                            phi = phi0 + sweep * t
                            heading = (start_deg + delta * t) % 360
                            ux, uy = unit(heading)
                            distance += step
                            self.frames.append(Frame(
                                Pose(cx + radius * math.cos(phi) + lead * ux,
                                     cy + radius * math.sin(phi) + lead * uy, heading),
                                index, None, False, distance))
                    distance += step
                    self.frames.append(Frame(Pose(end.x, end.y, end_deg), index, None, False, distance))
                else:
                    for vector in move.vectors:
                        distance += cell_size
                        self.frames.append(Frame(
                            Pose(vector.x, vector.y, HEADING_DEG[vector.direction]),
                            index, None, False, distance))

            if len(self.frames) > first:
                arrival = self.frames[-1]
                self.frames[-1] = Frame(arrival.pose, index, segment.image_id, False, arrival.distance_cm)
                for _ in range(CAPTURE_DWELL_FRAMES):
                    self.frames.append(Frame(arrival.pose, index, segment.image_id, True, arrival.distance_cm))

        self.index = 0
        # Precomputed once: the properties below are read every animation tick, so none of them
        # may walk the whole frame list.
        self._capture_frames = [i for i, f in enumerate(self.frames)
                                if f.captured_id is not None and not f.dwell]
        self._cells: list[tuple[Pose, int]] = []
        self._cell_count: list[int] = []
        for frame in self.frames:
            if not frame.dwell:
                self._cells.append((frame.pose, frame.segment_index))
            self._cell_count.append(len(self._cells))

    @property
    def current(self) -> Frame | None:
        return self.frames[self.index] if self.frames else None

    @property
    def finished(self) -> bool:
        return self.index >= len(self.frames) - 1

    def step(self) -> Frame | None:
        if self.finished:
            return None
        self.index += 1
        return self.current

    def reset(self) -> None:
        self.index = 0

    def seek(self, index: int) -> None:
        self.index = max(0, min(index, len(self.frames) - 1)) if self.frames else 0

    def _captures_upto(self, index: int) -> int:
        return bisect.bisect_right(self._capture_frames, index)

    @property
    def distance_cm(self) -> float:
        """Centimetres driven so far. Dwell frames repeat the previous value; they do not move."""
        return self.frames[self.index].distance_cm if self.frames else 0.0

    def seconds_at(self, index: int) -> float:
        """Estimated elapsed time when frame `index` is reached, driving plus captures so far."""
        return (self.frames[index].distance_cm / config.ROBOT_SPEED_CM_S
                + self._captures_upto(index) * config.CAPTURE_DWELL_S)

    @property
    def estimated_seconds(self) -> float:
        return self.seconds_at(self.index) if self.frames else 0.0

    @property
    def captured(self) -> list[tuple[int, float]]:
        """(image_id, estimated seconds) for every capture reached, in visit order."""
        return [(self.frames[j].captured_id, self.seconds_at(j))
                for j in self._capture_frames if j <= self.index]

    @property
    def next_id(self) -> int | None:
        """The obstacle the robot is heading for, or None once every capture is done."""
        done = self._captures_upto(self.index)
        return self.route.segments[done].image_id if done < len(self.route.segments) else None

    @property
    def trail(self) -> list[tuple[Pose, int]]:
        return self._cells[:self._cell_count[self.index]] if self.frames else []

    @property
    def remaining(self) -> list[tuple[Pose, int]]:
        return self._cells[self._cell_count[self.index]:] if self.frames else []
