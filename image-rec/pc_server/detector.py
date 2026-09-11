"""Ultralytics adapter kept separate from HTTP and persistence concerns."""

import threading
from dataclasses import replace
from pathlib import Path
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from vision.class_map import classify_model_label
from vision.contracts import BoundingBox, Detection


FRONTALITY_SCORE_TOLERANCE = 0.05


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
        nearest_height_tolerance: float = 0.10,
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
        self._nearest_height_tolerance = nearest_height_tolerance
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

        detections = self._convert_result(results[0], image.shape[1], image.shape[0])
        return image, prioritize_nearest_target(
            image, detections, self._nearest_height_tolerance
        )

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


def prioritize_nearest_target(
    image: Any,
    detections: Sequence[Detection],
    height_tolerance: float = 0.10,
) -> List[Detection]:
    """Mark the nearest target, preferring a head-on card at similar heights."""

    targets = [item for item in detections if item.kind == "target"]
    if not targets:
        return list(detections)
    maximum_height = max(_box_height(item.bbox) for item in targets)
    similar = [
        item
        for item in targets
        if _box_height(item.bbox) >= maximum_height * (1.0 - height_tolerance)
    ]
    scored = [
        (item, card_frontality_score(image, item.bbox))
        for item in similar
    ]
    if any(score is not None for _, score in scored):
        best_frontality = max(score for _, score in scored if score is not None)
        front_candidates = [
            item
            for item, score in scored
            if score is not None and score >= best_frontality - FRONTALITY_SCORE_TOLERANCE
        ]
        selected = max(front_candidates, key=lambda item: item.confidence)
    else:
        selected = max(similar, key=lambda item: item.confidence)
    scores = {id(item): score for item, score in scored}
    return [
        replace(
            item,
            frontality_score=scores.get(id(item)),
            is_primary=item is selected,
        )
        if item.kind == "target"
        else item
        for item in detections
    ]


def card_frontality_score(image: Any, box: BoundingBox) -> Optional[float]:
    """Return a 0..1 quadrilateral frontality score, or ``None`` if no card is found."""

    import cv2
    import numpy as np

    if image is None or not hasattr(image, "shape") or len(image.shape) < 2:
        return None
    image_height, image_width = image.shape[:2]
    box_width = box.x_max - box.x_min
    box_height = box.y_max - box.y_min
    padding_x = max(2, int(round(box_width * 0.12)))
    padding_y = max(2, int(round(box_height * 0.12)))
    x1 = max(0, box.x_min - padding_x)
    y1 = max(0, box.y_min - padding_y)
    x2 = min(image_width, box.x_max + padding_x)
    y2 = min(image_height, box.y_max + padding_y)
    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        return None
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    _, light = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    edges = cv2.Canny(gray, 50, 150)
    candidates = []
    for mask in (light, edges):
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            perimeter = cv2.arcLength(contour, True)
            approximation = cv2.approxPolyDP(contour, 0.025 * perimeter, True)
            if len(approximation) != 4 or not cv2.isContourConvex(approximation):
                continue
            area = abs(float(cv2.contourArea(approximation)))
            if area < box_width * box_height * 0.35:
                continue
            points = approximation.reshape((4, 2)).astype(np.float32)
            centre = points.mean(axis=0)
            expected = np.asarray(
                ((box.x_min + box.x_max) / 2.0 - x1, (box.y_min + box.y_max) / 2.0 - y1),
                dtype=np.float32,
            )
            centre_distance = float(np.linalg.norm(centre - expected))
            if centre_distance > max(box_width, box_height) * 0.35:
                continue
            candidates.append((area, points))
    if not candidates:
        return None
    _, points = max(candidates, key=lambda item: item[0])
    return _quadrilateral_frontality(points)


def _quadrilateral_frontality(points: Any) -> float:
    import numpy as np

    centre = points.mean(axis=0)
    angles = np.arctan2(points[:, 1] - centre[1], points[:, 0] - centre[0])
    ordered = points[np.argsort(angles)]
    edges = [ordered[(index + 1) % 4] - ordered[index] for index in range(4)]
    lengths = [max(1e-6, float(np.linalg.norm(edge))) for edge in edges]
    right_angles = []
    for index in range(4):
        first = edges[index] / lengths[index]
        second = edges[(index + 1) % 4] / lengths[(index + 1) % 4]
        right_angles.append(1.0 - min(1.0, abs(float(np.dot(first, second)))))
    opposite_symmetry = 0.5 * (
        min(lengths[0], lengths[2]) / max(lengths[0], lengths[2])
        + min(lengths[1], lengths[3]) / max(lengths[1], lengths[3])
    )
    diagonals = (
        float(np.linalg.norm(ordered[0] - ordered[2])),
        float(np.linalg.norm(ordered[1] - ordered[3])),
    )
    diagonal_symmetry = min(diagonals) / max(max(diagonals), 1e-6)
    score = 0.50 * float(np.mean(right_angles)) + 0.35 * opposite_symmetry + 0.15 * diagonal_symmetry
    return max(0.0, min(1.0, score))


def _box_height(box: BoundingBox) -> int:
    return box.y_max - box.y_min
