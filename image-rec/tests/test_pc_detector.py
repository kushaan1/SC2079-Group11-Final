from types import SimpleNamespace

import numpy as np
import cv2

from pc_server.detector import (
    UltralyticsDetector,
    card_frontality_score,
    prioritize_nearest_target,
)
from vision.contracts import BoundingBox, Detection


class TensorLike:
    def __init__(self, values):
        self.values = np.asarray(values)

    def cpu(self):
        return self

    def numpy(self):
        return self.values


def test_converts_targets_and_preserves_bullseye_signal():
    result = SimpleNamespace(
        names={0: "Left Arrow", 41: "Bullseye"},
        boxes=SimpleNamespace(
            xyxy=TensorLike([[-3.0, 2.0, 30.0, 40.0], [10.0, 10.0, 20.0, 20.0]]),
            conf=TensorLike([0.85, 0.95]),
            cls=TensorLike([0, 41]),
        ),
    )
    detections = UltralyticsDetector._convert_result(result, width=25, height=35)
    assert [item.kind for item in detections] == ["bullseye", "target"]
    assert detections[1].competition_id == 39
    assert detections[1].bbox.to_list() == [0, 2, 25, 35]


def test_unknown_model_classes_are_not_reported():
    result = SimpleNamespace(
        names={0: "not-in-contract"},
        boxes=SimpleNamespace(
            xyxy=TensorLike([[1, 1, 5, 5]]),
            conf=TensorLike([0.9]),
            cls=TensorLike([0]),
        ),
    )
    assert UltralyticsDetector._convert_result(result, 10, 10) == []


def target(competition_id, confidence, box):
    return Detection(
        "target-{}".format(competition_id),
        confidence,
        BoundingBox(*box),
        "target",
        competition_id,
    )


def test_similar_height_targets_prefer_the_head_on_card_before_confidence():
    image = np.zeros((160, 260, 3), dtype=np.uint8)
    cv2.rectangle(image, (20, 20), (100, 120), (235, 235, 235), -1)
    trapezoid = np.asarray(((155, 20), (215, 32), (225, 118), (140, 120)), dtype=np.int32)
    cv2.fillConvexPoly(image, trapezoid, (235, 235, 235))
    head_on = target(11, 0.70, (20, 20, 100, 120))
    angled = target(12, 0.96, (140, 20, 225, 120))
    ranked = prioritize_nearest_target(image, [angled, head_on], height_tolerance=0.10)
    selected = next(item for item in ranked if item.is_primary)
    assert selected.competition_id == 11
    assert card_frontality_score(image, head_on.bbox) > card_frontality_score(image, angled.bbox)


def test_larger_card_wins_when_heights_are_not_similar():
    image = np.zeros((200, 240, 3), dtype=np.uint8)
    cv2.rectangle(image, (10, 10), (90, 170), (235, 235, 235), -1)
    cv2.rectangle(image, (140, 50), (210, 145), (235, 235, 235), -1)
    large = target(11, 0.60, (10, 10, 90, 170))
    small = target(12, 0.99, (140, 50, 210, 145))
    ranked = prioritize_nearest_target(image, [small, large], height_tolerance=0.10)
    assert next(item for item in ranked if item.is_primary).competition_id == 11


def test_confidence_breaks_tie_when_no_card_contour_is_available():
    image = np.zeros((120, 220, 3), dtype=np.uint8)
    low = target(11, 0.70, (10, 10, 80, 100))
    high = target(12, 0.90, (120, 10, 190, 100))
    ranked = prioritize_nearest_target(image, [low, high], height_tolerance=0.10)
    assert next(item for item in ranked if item.is_primary).competition_id == 12
