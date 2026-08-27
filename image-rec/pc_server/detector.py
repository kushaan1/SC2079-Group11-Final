"""Ultralytics adapter kept separate from HTTP and persistence concerns."""

import threading
from pathlib import Path
from typing import Any, List, Mapping, Sequence, Tuple

from vision.class_map import classify_model_label
from vision.contracts import BoundingBox, Detection


class InvalidImageError(ValueError):
    """Raised when uploaded bytes cannot be decoded as an image."""


class UltralyticsDetector:
    """Thread-safe YOLOv8 ``.pt`` detector for the host PC."""

    def __init__(
        self,
        model_path: Path,
        confidence_threshold: float,
        iou_threshold: float,
        model: Any = None,
    ) -> None:
        if model is None:
            if not model_path.is_file():
                raise FileNotFoundError(
                    "YOLO weights not found at {}. Set VISION_PC_MODEL_PATH.".format(model_path)
                )
            from ultralytics import YOLO

            model = YOLO(str(model_path))
        self._model = model
        self._confidence_threshold = confidence_threshold
        self._iou_threshold = iou_threshold
        self._lock = threading.Lock()

    def detect(self, image_bytes: bytes) -> Tuple[Any, List[Detection]]:
        import cv2
        import numpy as np

        encoded = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if image is None:
            raise InvalidImageError("uploaded file is not a decodable image")

        with self._lock:
            results = self._model.predict(
                source=image,
                conf=self._confidence_threshold,
                iou=self._iou_threshold,
                verbose=False,
            )
        if not results:
            return image, []

        return image, self._convert_result(results[0], image.shape[1], image.shape[0])

    @staticmethod
    def _convert_result(result: Any, width: int, height: int) -> List[Detection]:
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            return []

        names = getattr(result, "names", {})
        xyxy = _to_numpy(boxes.xyxy)
        confidences = _to_numpy(boxes.conf)
        class_ids = _to_numpy(boxes.cls)
        detections: List[Detection] = []

        for coordinates, confidence, raw_class_id in zip(xyxy, confidences, class_ids):
            class_id = int(raw_class_id)
            label = _class_name(names, class_id)
            kind, competition_id, canonical_label = classify_model_label(label, class_id)
            if kind == "unknown":
                continue

            x_min, y_min, x_max, y_max = _clip_box(coordinates, width, height)
            if x_max <= x_min or y_max <= y_min:
                continue
            detections.append(
                Detection(
                    label=canonical_label,
                    confidence=float(confidence),
                    bbox=BoundingBox(x_min, y_min, x_max, y_max),
                    kind=kind,
                    competition_id=competition_id,
                    model_class_id=class_id,
                )
            )

        return sorted(detections, key=lambda item: item.confidence, reverse=True)


def _to_numpy(value: Any) -> Any:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        return value.numpy()
    return value


def _class_name(names: Any, class_id: int) -> str:
    if isinstance(names, Mapping):
        return str(names.get(class_id, class_id))
    if isinstance(names, Sequence) and class_id < len(names):
        return str(names[class_id])
    return str(class_id)


def _clip_box(coordinates: Sequence[float], width: int, height: int) -> Tuple[int, int, int, int]:
    x_min, y_min, x_max, y_max = (int(round(float(value))) for value in coordinates[:4])
    return (
        max(0, min(width - 1, x_min)),
        max(0, min(height - 1, y_min)),
        max(0, min(width, x_max)),
        max(0, min(height, y_max)),
    )
