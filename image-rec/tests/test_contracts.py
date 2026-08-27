import pytest

from vision.contracts import BoundingBox, Detection, DetectionResult, status_for_detections


def detection(kind="target", confidence=0.9):
    return Detection(
        label="Left Arrow" if kind == "target" else "Bullseye",
        confidence=confidence,
        bbox=BoundingBox(1, 2, 20, 30),
        kind=kind,
        competition_id=39 if kind == "target" else None,
    )


def test_result_prefers_target_and_serialises_versioned_contract():
    result = DetectionResult(
        object_id="obstacle-3",
        status="target",
        detections=(detection("bullseye", 0.99), detection("target", 0.8)),
    )
    payload = result.to_dict()
    assert payload["schema_version"] == "1.0"
    assert payload["detection"]["competition_id"] == 39
    assert payload["detections"][0]["kind"] == "bullseye"


def test_status_keeps_bullseye_distinct_from_no_detection():
    assert status_for_detections([]) == "no_detection"
    assert status_for_detections([detection("bullseye")]) == "bullseye"
    assert status_for_detections([detection("bullseye"), detection("target")]) == "target"


def test_invalid_target_id_is_rejected():
    with pytest.raises(ValueError):
        Detection("bad", 0.9, BoundingBox(0, 0, 2, 2), "target", 41)
