from __future__ import annotations

from dataclasses import dataclass
from typing import List

import config
from pathfinding.world.primitives import Vector


@dataclass(frozen=True)
class Frame:
    vector: Vector
    segment_index: int
    captured_image_id: int | None = None


class Playback:
    def __init__(self, route) -> None:
        self.route = route
        self._frames: List[Frame] = []
        self._index = 0
        self._build_frames()

    def _build_frames(self) -> None:
        frames: List[Frame] = []
        for si, seg in enumerate(self.route.segments):
            vectors = seg.vectors
            for i, v in enumerate(vectors):
                captured = seg.image_id if i == len(vectors) - 1 else None
                frames.append(Frame(v, si, captured))
            # dwell frames: repeat the capture frame CAPTURE_DWELL_FRAMES times
            if vectors:
                for _ in range(10):
                    frames.append(Frame(vectors[-1], si, seg.image_id))

        self._frames = frames

    @property
    def frames(self) -> List[Frame]:
        return self._frames

    @property
    def index(self) -> int:
        return self._index

    @property
    def current(self) -> Frame | None:
        if not self._frames:
            return None
        if self._index >= len(self._frames):
            return self._frames[-1]
        return self._frames[self._index]

    @property
    def finished(self) -> bool:
        return self._index >= len(self._frames)

    @property
    def recognised(self) -> List[int]:
        ids = []
        for f in self._frames[: min(self._index + 1, len(self._frames))]:
            if f.captured_image_id is not None and (not ids or ids[-1] != f.captured_image_id):
                ids.append(f.captured_image_id)
        return ids

    def step(self) -> Frame | None:
        if self.finished:
            return None
        frame = self._frames[self._index]
        self._index += 1
        return frame

    def reset(self) -> None:
        self._index = 0

    def seek(self, index: int) -> None:
        self._index = max(0, min(index, len(self._frames)))

    @property
    def distance_cm(self) -> int:
        # Count unique traveled frames (exclude dwell duplicates) — approximated as index
        return self._index

    def estimated_seconds(self) -> float:
        return self.distance_cm / config.ROBOT_SPEED_CM_S
