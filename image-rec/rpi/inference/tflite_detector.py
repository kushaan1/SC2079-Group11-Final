"""NumPy post-processing for a quantized YOLOv8 TFLite arrow model."""

import json
from pathlib import Path
from typing import Any, List, Sequence, Tuple

import numpy as np

from vision.class_map import classify_model_label
from vision.contracts import BoundingBox, Detection


class TFLiteYoloDetector:
    """Run raw YOLOv8 TFLite output without importing PyTorch or Ultralytics."""

    def __init__(
        self,
        model_path: Path,
        labels_path: Path,
        confidence_threshold: float,
        iou_threshold: float,
        interpreter: Any = None,
    ) -> None:
        self.labels = self._load_labels(labels_path)
        self.confidence_threshold = confidence_threshold
        self.iou_threshold = iou_threshold
        if interpreter is None:
            if not model_path.is_file():
                raise FileNotFoundError(
                    "TFLite weights not found at {}. Set VISION_TFLITE_MODEL_PATH.".format(
                        model_path
                    )
                )
            from tflite_runtime.interpreter import Interpreter

            interpreter = Interpreter(model_path=str(model_path), num_threads=2)
        self._interpreter = interpreter
        self._interpreter.allocate_tensors()
        self._input = self._interpreter.get_input_details()[0]
        self._output = self._interpreter.get_output_details()[0]
        shape = tuple(int(value) for value in self._input["shape"])
        if len(shape) != 4 or shape[0] != 1 or shape[3] != 3:
            raise ValueError("expected a [1, height, width, 3] TFLite input tensor")
        self.input_height = shape[1]
        self.input_width = shape[2]

    @staticmethod
    def _load_labels(path: Path) -> List[str]:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            ordered = [data[str(index)] for index in range(len(data))]
        elif isinstance(data, list):
            ordered = data
        else:
            raise ValueError("labels JSON must be a list or zero-indexed object")
        if not ordered or not all(isinstance(item, str) and item for item in ordered):
            raise ValueError("labels JSON contains invalid class names")
        return ordered

    def detect(self, frame: Any) -> List[Detection]:
        tensor, scale, pad_x, pad_y = self._preprocess(frame)
        self._interpreter.set_tensor(self._input["index"], tensor)
        self._interpreter.invoke()
        output = self._interpreter.get_tensor(self._output["index"])
        output = _dequantize(output, self._output)
        candidates = self._parse_raw_output(output)
        return self._to_detections(
            candidates,
            frame.shape[1],
            frame.shape[0],
            scale,
            pad_x,
            pad_y,
        )

    def _preprocess(self, frame: Any) -> Tuple[Any, float, int, int]:
        import cv2

        if frame is None or len(frame.shape) != 3 or frame.shape[2] != 3:
            raise ValueError("expected a BGR image with three channels")
        source_height, source_width = frame.shape[:2]
        scale = min(self.input_width / float(source_width), self.input_height / float(source_height))
        resized_width = max(1, int(round(source_width * scale)))
        resized_height = max(1, int(round(source_height * scale)))
        resized = cv2.resize(frame, (resized_width, resized_height))
        canvas = np.full((self.input_height, self.input_width, 3), 114, dtype=np.uint8)
        pad_x = (self.input_width - resized_width) // 2
        pad_y = (self.input_height - resized_height) // 2
        canvas[pad_y : pad_y + resized_height, pad_x : pad_x + resized_width] = resized
        rgb = canvas[:, :, ::-1]
        normalised = rgb.astype(np.float32) / 255.0
        tensor = _quantize(normalised[np.newaxis, ...], self._input)
        return tensor, scale, pad_x, pad_y

    def _parse_raw_output(self, output: Any) -> Any:
        prediction = np.squeeze(output, axis=0) if output.ndim == 3 and output.shape[0] == 1 else output
        if prediction.ndim != 2:
            raise ValueError("expected one two-dimensional YOLO output tensor")

        valid_attribute_counts = (4 + len(self.labels), 5 + len(self.labels))
        if prediction.shape[1] in valid_attribute_counts:
            rows = prediction
        elif prediction.shape[0] in valid_attribute_counts:
            rows = prediction.T
        else:
            raise ValueError(
                "YOLO output shape {} does not match {} labels".format(
                    tuple(prediction.shape), len(self.labels)
                )
            )

        if rows.shape[1] == 5 + len(self.labels):
            class_scores = rows[:, 5:] * rows[:, 4:5]
        else:
            class_scores = rows[:, 4:]
        class_ids = np.argmax(class_scores, axis=1)
        confidences = class_scores[np.arange(len(rows)), class_ids]
        keep = confidences >= self.confidence_threshold
        return np.column_stack((rows[keep, :4], confidences[keep], class_ids[keep]))

    def _to_detections(
        self,
        candidates: Any,
        source_width: int,
        source_height: int,
        scale: float,
        pad_x: int,
        pad_y: int,
    ) -> List[Detection]:
        if len(candidates) == 0:
            return []
        boxes = candidates[:, :4].astype(np.float32).copy()
        if float(np.max(np.abs(boxes))) <= 2.0:
            boxes[:, (0, 2)] *= self.input_width
            boxes[:, (1, 3)] *= self.input_height
        boxes = _xywh_to_xyxy(boxes)
        boxes[:, (0, 2)] = (boxes[:, (0, 2)] - pad_x) / scale
        boxes[:, (1, 3)] = (boxes[:, (1, 3)] - pad_y) / scale
        boxes[:, (0, 2)] = np.clip(boxes[:, (0, 2)], 0, source_width)
        boxes[:, (1, 3)] = np.clip(boxes[:, (1, 3)], 0, source_height)
        keep = _class_aware_nms(
            boxes,
            candidates[:, 4],
            candidates[:, 5].astype(np.int64),
            self.iou_threshold,
        )

        detections: List[Detection] = []
        for index in keep:
            class_id = int(candidates[index, 5])
            label = self.labels[class_id]
            kind, competition_id, canonical = classify_model_label(label, class_id)
            if kind == "unknown":
                continue
            x_min, y_min, x_max, y_max = [int(round(value)) for value in boxes[index]]
            if x_max <= x_min or y_max <= y_min:
                continue
            detections.append(
                Detection(
                    canonical,
                    float(candidates[index, 4]),
                    BoundingBox(x_min, y_min, x_max, y_max),
                    kind,
                    competition_id,
                    class_id,
                )
            )
        return detections


def _quantize(tensor: Any, details: Any) -> Any:
    dtype = np.dtype(details["dtype"])
    if np.issubdtype(dtype, np.floating):
        return tensor.astype(dtype)
    scale, zero_point = details.get("quantization", (0.0, 0))
    if not scale:
        raise ValueError("integer input tensor has no quantization scale")
    limits = np.iinfo(dtype)
    quantized = np.round(tensor / scale + zero_point)
    return np.clip(quantized, limits.min, limits.max).astype(dtype)


def _dequantize(tensor: Any, details: Any) -> Any:
    if np.issubdtype(tensor.dtype, np.floating):
        return tensor.astype(np.float32)
    scale, zero_point = details.get("quantization", (0.0, 0))
    if not scale:
        raise ValueError("integer output tensor has no quantization scale")
    return (tensor.astype(np.float32) - zero_point) * scale


def _xywh_to_xyxy(boxes: Any) -> Any:
    converted = boxes.copy()
    converted[:, 0] = boxes[:, 0] - boxes[:, 2] / 2.0
    converted[:, 1] = boxes[:, 1] - boxes[:, 3] / 2.0
    converted[:, 2] = boxes[:, 0] + boxes[:, 2] / 2.0
    converted[:, 3] = boxes[:, 1] + boxes[:, 3] / 2.0
    return converted


def _class_aware_nms(boxes: Any, scores: Any, class_ids: Any, threshold: float) -> List[int]:
    selected: List[int] = []
    for class_id in np.unique(class_ids):
        indices = np.where(class_ids == class_id)[0]
        order = indices[np.argsort(scores[indices])[::-1]]
        while len(order):
            current = int(order[0])
            selected.append(current)
            if len(order) == 1:
                break
            remaining = order[1:]
            overlap = _iou(boxes[current], boxes[remaining])
            order = remaining[overlap <= threshold]
    return sorted(selected, key=lambda index: float(scores[index]), reverse=True)


def _iou(box: Any, boxes: Any) -> Any:
    x_min = np.maximum(box[0], boxes[:, 0])
    y_min = np.maximum(box[1], boxes[:, 1])
    x_max = np.minimum(box[2], boxes[:, 2])
    y_max = np.minimum(box[3], boxes[:, 3])
    intersection = np.maximum(0.0, x_max - x_min) * np.maximum(0.0, y_max - y_min)
    box_area = max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])
    areas = np.maximum(0.0, boxes[:, 2] - boxes[:, 0]) * np.maximum(
        0.0, boxes[:, 3] - boxes[:, 1]
    )
    union = box_area + areas - intersection
    return np.divide(intersection, union, out=np.zeros_like(intersection), where=union > 0)
