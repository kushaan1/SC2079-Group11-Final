"""Frames in, TARGET lines out, off the driving thread (spec §5.8).

The run drops frames here and keeps driving. This thread posts them one at a
time, picks the best verdict per obstacle, and tells the tablet once.
"""

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from rpi import protocol
from rpi.model import Verdict

LOG = logging.getLogger(__name__)

_STOP = object()


@dataclass(frozen=True)
class Result:
    obstacle_id: int
    status: str
    competition_id: Optional[int]
    confidence: Optional[float]


def decide(obstacle_id: int, verdicts: List[Verdict]) -> Result:
    """Best target by confidence; else bullseye; else nothing; else error."""
    targets = [v for v in verdicts if v.status == "target"]
    if targets:
        best = max(targets, key=lambda v: v.confidence if v.confidence is not None else -1.0)
        return Result(obstacle_id, "target", best.competition_id, best.confidence)
    for status in ("bullseye", "no_detection"):
        for v in verdicts:
            if v.status == status:
                return Result(obstacle_id, status, None, v.confidence)
    return Result(obstacle_id, "error", None, None)


_MISS_TEXT = {
    "bullseye": "B%d: bullseye - wrong face?",
    "no_detection": "B%d: nothing recognised",
    "error": "B%d: recogniser unreachable",
}


class VisionWorker:
    def __init__(self, client: object, send: Callable[[str], None], frames_per_obstacle: int = 3) -> None:
        self._client = client
        self._send = send
        self._frames_per_obstacle = frames_per_obstacle
        self._queue = queue.Queue()        # type: queue.Queue
        self._cond = threading.Condition()
        self._results = {}                 # type: Dict[int, Result]
        self._pending = 0
        self._warned_unconfigured = False
        self._thread = None                # type: Optional[threading.Thread]

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="vision-worker", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._queue.put(_STOP)
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    @property
    def pending(self) -> int:
        with self._cond:
            return self._pending

    def submit(self, obstacle_id: int, frames: List[bytes], quiet: bool = False) -> bool:
        """Queue frames for an obstacle. False if they were dropped (no server configured)."""
        if not getattr(self._client, "configured", True):
            if not self._warned_unconfigured:
                self._warned_unconfigured = True
                self._send(protocol.msg("Vision URL not configured"))
            return False
        with self._cond:
            self._results.pop(obstacle_id, None)
            self._pending += 1
        self._queue.put((obstacle_id, list(frames)[: self._frames_per_obstacle], quiet))
        return True

    def wait(self, obstacle_id: int, timeout_s: float) -> Optional[Result]:
        end = time.monotonic() + timeout_s
        with self._cond:
            while obstacle_id not in self._results:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    return None
                self._cond.wait(remaining)
            return self._results[obstacle_id]

    def wait_all(self, timeout_s: float) -> bool:
        end = time.monotonic() + timeout_s
        with self._cond:
            while self._pending > 0:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(remaining)
            return True

    def results(self) -> List[Result]:
        with self._cond:
            return list(self._results.values())

    def _loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            obstacle_id, frames, quiet = item
            try:
                verdicts = [self._client.detect(frame, "B%d" % obstacle_id) for frame in frames]
                result = decide(obstacle_id, verdicts)
            except Exception:   # the client never raises by contract; belt and braces
                LOG.exception("vision worker failed on B%d", obstacle_id)
                result = Result(obstacle_id, "error", None, None)
            if result.status == "target":
                self._send(protocol.target(obstacle_id, result.competition_id))
            elif not quiet:
                self._send(protocol.msg(_MISS_TEXT[result.status] % obstacle_id))
            with self._cond:
                self._results[obstacle_id] = result
                self._pending -= 1
                self._cond.notify_all()
