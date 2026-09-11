import json

import numpy as np

from rpi.inference.tflite_detector import TFLiteYoloDetector, _class_aware_nms


class FakeInterpreter:
    def __init__(self, output, input_dtype=np.float32, input_quantization=(0.0, 0)):
        self.output = output
        self.input_dtype = input_dtype
        self.input_quantization = input_quantization
        self.input_value = None
        self.invoked = False

    def allocate_tensors(self):
        pass

    def get_input_details(self):
        return [
            {
                "index": 0,
                "shape": np.array([1, 4, 4, 3]),
                "dtype": self.input_dtype,
                "quantization": self.input_quantization,
            }
        ]

    def get_output_details(self):
        return [
            {
                "index": 1,
                "dtype": self.output.dtype,
                "quantization": (0.0, 0),
            }
        ]

    def set_tensor(self, index, value):
        self.input_value = value

    def invoke(self):
        self.invoked = True

    def get_tensor(self, index):
        return self.output


def labels_file(tmp_path):
    path = tmp_path / "labels.json"
    path.write_text(json.dumps(["Left Arrow", "Right Arrow"]), encoding="utf-8")
    return path


def test_parses_channel_first_yolov8_output_and_applies_nms(tmp_path):
    # Two overlapping left-arrow candidates: [cx, cy, width, height, left, right].
    rows = np.array(
        [[2.0, 2.0, 2.0, 2.0, 0.90, 0.10], [2.1, 2.1, 2.0, 2.0, 0.80, 0.20]],
        dtype=np.float32,
    )
    interpreter = FakeInterpreter(rows.T[np.newaxis, ...])
    detector = TFLiteYoloDetector(
        tmp_path / "unused.tflite",
        labels_file(tmp_path),
        confidence_threshold=0.75,
        iou_threshold=0.45,
        interpreter=interpreter,
    )
    detections = detector.detect(np.zeros((4, 4, 3), dtype=np.uint8))
    assert interpreter.invoked
    assert len(detections) == 1
    assert detections[0].competition_id == 39
    assert detections[0].bbox.to_list() == [1, 1, 3, 3]


def test_quantizes_input_for_uint8_model(tmp_path):
    output = np.zeros((1, 6, 1), dtype=np.float32)
    interpreter = FakeInterpreter(output, np.uint8, (1.0 / 255.0, 0))
    detector = TFLiteYoloDetector(
        tmp_path / "unused.tflite",
        labels_file(tmp_path),
        0.75,
        0.45,
        interpreter,
    )
    detector.detect(np.full((4, 4, 3), 255, dtype=np.uint8))
    assert interpreter.input_value.dtype == np.uint8
    assert np.all(interpreter.input_value == 255)


def test_nms_is_class_aware():
    boxes = np.array([[0, 0, 10, 10], [1, 1, 9, 9], [1, 1, 9, 9]], dtype=np.float32)
    scores = np.array([0.9, 0.8, 0.7])
    classes = np.array([0, 0, 1])
    assert _class_aware_nms(boxes, scores, classes, 0.45) == [0, 2]
