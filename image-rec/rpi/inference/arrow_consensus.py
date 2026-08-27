"""N-of-M temporal agreement gate for Task 2 arrow decisions."""

from collections import Counter, deque
from typing import Deque, Optional, Sequence

from vision.contracts import Detection


ARROW_DIRECTIONS = {38: "right", 39: "left"}


class ArrowConsensus:
    def __init__(self, required: int, window: int, confidence_threshold: float) -> None:
        if not 1 <= required <= window:
            raise ValueError("consensus requires 1 <= required <= window")
        self.required = required
        self._observations: Deque[Optional[int]] = deque(maxlen=window)
        self.confidence_threshold = confidence_threshold

    def observe(self, detections: Sequence[Detection]) -> Optional[str]:
        arrows = [
            item
            for item in detections
            if item.competition_id in ARROW_DIRECTIONS
            and item.confidence >= self.confidence_threshold
        ]
        best = max(arrows, key=lambda item: item.confidence) if arrows else None
        self._observations.append(best.competition_id if best is not None else None)
        counts = Counter(item for item in self._observations if item is not None)
        if not counts:
            return None
        competition_id, count = counts.most_common(1)[0]
        tied = sum(1 for value in counts.values() if value == count) > 1
        if count >= self.required and not tied:
            return ARROW_DIRECTIONS[competition_id]
        return None

    def reset(self) -> None:
        self._observations.clear()
