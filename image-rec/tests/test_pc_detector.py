from types import SimpleNamespace

import numpy as np

from pc_server.detector import UltralyticsDetector


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
