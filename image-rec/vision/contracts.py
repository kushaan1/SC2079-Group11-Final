"""Versioned, JSON-serialisable contracts shared by PC and Raspberry Pi."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple


SCHEMA_VERSION = "1.0"
VALID_STATUSES = frozenset(("target", "bullseye", "no_detection", "error"))


@dataclass(frozen=True)
class BoundingBox:
    """Pixel-space bounding box in ``x_min, y_min, x_max, y_max`` order."""

    x_min: int
    y_min: int
    x_max: int
    y_max: int

    def __post_init__(self) -> None:
        if min(self.x_min, self.y_min) < 0:
            raise ValueError("bounding-box coordinates cannot be negative")
        if self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise ValueError("bounding box must have positive width and height")

    def to_list(self) -> List[int]:
        return [self.x_min, self.y_min, self.x_max, self.y_max]


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    bbox: BoundingBox
    kind: str
    competition_id: Optional[int] = None
    model_class_id: Optional[int] = None
    frontality_score: Optional[float] = None
    is_primary: bool = False

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.kind not in ("target", "bullseye", "unknown"):
            raise ValueError("invalid detection kind: {}".format(self.kind))
        if self.kind == "target" and self.competition_id not in range(11, 41):
            raise ValueError("target detections require an ID from 11 through 40")
        if self.kind != "target" and self.competition_id is not None:
            raise ValueError("non-target detections cannot have a competition ID")
        if self.frontality_score is not None and not 0.0 <= self.frontality_score <= 1.0:
            raise ValueError("frontality_score must be between 0 and 1")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "confidence": round(float(self.confidence), 6),
            "bbox": self.bbox.to_list(),
            "kind": self.kind,
            "competition_id": self.competition_id,
            "model_class_id": self.model_class_id,
        }


@dataclass(frozen=True)
class DetectionResult:
    object_id: str
    status: str
    detections: Tuple[Detection, ...] = field(default_factory=tuple)
    raw_image: Optional[str] = None
    annotated_image: Optional[str] = None
    error: Optional[str] = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.object_id:
            raise ValueError("object_id cannot be empty")
        if self.status not in VALID_STATUSES:
            raise ValueError("invalid result status: {}".format(self.status))
        if self.status == "error" and not self.error:
            raise ValueError("error results require an error message")

    @property
    def best_detection(self) -> Optional[Detection]:
        if not self.detections:
            return None
        targets = [item for item in self.detections if item.kind == "target"]
        candidates: Sequence[Detection] = targets or self.detections
        primary = [item for item in candidates if item.is_primary]
        if primary:
            return max(primary, key=lambda item: item.confidence)
        return max(candidates, key=lambda item: item.confidence)

    def to_dict(self) -> Dict[str, Any]:
        best = self.best_detection
        return {
            "schema_version": self.schema_version,
            "object_id": self.object_id,
            "status": self.status,
            "detection": best.to_dict() if best else None,
            "detections": [item.to_dict() for item in self.detections],
            "artifacts": {
                "raw_image": self.raw_image,
                "annotated_image": self.annotated_image,
            },
            "error": self.error,
        }


def status_for_detections(detections: Sequence[Detection]) -> str:
    """Choose a recovery-safe status, preferring target over bull's-eye."""

    if any(item.kind == "target" for item in detections):
        return "target"
    if any(item.kind == "bullseye" for item in detections):
        return "bullseye"
    return "no_detection"
