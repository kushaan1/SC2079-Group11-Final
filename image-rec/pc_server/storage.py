"""Asynchronous persistence of raw and verification images."""

import atexit
import re
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Tuple
from uuid import uuid4

from vision.contracts import DetectionResult


class AsyncImageStore:
    """Queue image writes so inference responses are not delayed by disk I/O."""

    def __init__(self, capture_dir: Path, workers: int = 2) -> None:
        self.capture_dir = capture_dir
        self.raw_dir = capture_dir / "raw"
        self.annotated_dir = capture_dir / "annotated"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.annotated_dir.mkdir(parents=True, exist_ok=True)
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="image-save")
        self._futures: List[Future] = []
        atexit.register(self.close)

    def schedule(self, image: Any, result: DetectionResult) -> Tuple[str, str]:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        safe_object_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", result.object_id).strip("-")
        stem = "{}_{}_{}".format(timestamp, safe_object_id or "object", uuid4().hex[:8])
        raw_path = self.raw_dir / "{}.jpg".format(stem)
        annotated_path = self.annotated_dir / "{}.jpg".format(stem)
        future = self._executor.submit(
            self._write_pair,
            image.copy(),
            result,
            raw_path,
            annotated_path,
        )
        self._futures.append(future)
        return str(raw_path), str(annotated_path)

    @staticmethod
    def _write_pair(
        image: Any,
        result: DetectionResult,
        raw_path: Path,
        annotated_path: Path,
    ) -> None:
        import cv2

        if not cv2.imwrite(str(raw_path), image):
            raise OSError("failed to save raw image to {}".format(raw_path))

        annotated = image.copy()
        best = result.best_detection
        if best is not None:
            box = best.bbox
            cv2.rectangle(
                annotated,
                (box.x_min, box.y_min),
                (box.x_max, box.y_max),
                (0, 255, 0),
                2,
            )
            cv2.putText(
                annotated,
                result.object_id,
                (box.x_min, max(18, box.y_min - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )
        if not cv2.imwrite(str(annotated_path), annotated):
            raise OSError("failed to save annotated image to {}".format(annotated_path))

    def flush(self) -> None:
        pending, self._futures = self._futures, []
        for future in pending:
            future.result()

    def close(self) -> None:
        executor = getattr(self, "_executor", None)
        if executor is not None:
            self.flush()
            executor.shutdown(wait=True)
            self._executor = None
