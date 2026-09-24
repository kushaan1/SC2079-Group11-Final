"""Arrow reading for Task 2 (Task 2 spec §5.1): the sources that see arrows in a
frame, the vote across frames, and the read loop that ties them to the camera.
"""

import importlib.util
import io
import json
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Dict, List, Optional, Sequence

from rpi.camera import Camera, CameraError
from rpi.vision_client import VisionClient

LOG = logging.getLogger(__name__)

# Competition image ids -> direction. The one place this mapping lives.
ARROW_IDS = {38: "right", 39: "left"}
DIRECTIONS = ("left", "right")


@dataclass(frozen=True)
class Sighting:
    """One arrow seen in one frame."""
    direction: str      # "left" | "right"
    confidence: float


class ArrowSource(ABC):
    """Something that finds arrows in a JPEG. Implementations never raise from
    sightings(): a frame that cannot be read is a frame with no arrow."""

    @abstractmethod
    def sightings(self, jpeg: bytes) -> List[Sighting]:
        pass

    @abstractmethod
    def check(self) -> Optional[str]:
        """None if usable right now, else the reason, worded for the tablet (pre-flight)."""

    @property
    @abstractmethod
    def configured(self) -> bool:
        """Whether the static preconditions hold (a URL, a model file)."""

    @property
    @abstractmethod
    def describe(self) -> str:
        """For the run's first MSG: 'http http://...' | 'tflite <path>' | 'fake left,right'."""


class FakeArrowSource(ArrowSource):
    """A scripted source: one entry per frame ("left", "right" or None), served in
    order; nothing once the script runs out unless it cycles. Tests and --fake-arrows."""

    def __init__(
        self,
        frames: Sequence[Optional[str]],
        confidence: float = 1.0,
        cycle: bool = False,
        label: Optional[str] = None,
    ) -> None:
        for entry in frames:
            if entry is not None and entry not in DIRECTIONS:
                raise ValueError("not an arrow direction: %r" % (entry,))
        self._script = list(frames)
        self._frames = list(frames)
        self._confidence = confidence
        self._cycle = cycle
        self._label = label if label is not None else ",".join(str(f) for f in frames)
        self.calls = 0

    @classmethod
    def for_reads(cls, directions: Sequence[str], frames: int, cycle: bool = False) -> "FakeArrowSource":
        """One direction per arrow read, each repeated `frames` times (the vote's `required`)."""
        script = [direction for direction in directions for _ in range(frames)]
        return cls(script, cycle=cycle, label=",".join(directions))

    def sightings(self, jpeg: bytes) -> List[Sighting]:
        self.calls += 1
        if not self._frames:
            if not self._cycle or not self._script:
                return []
            self._frames = list(self._script)
        entry = self._frames.pop(0)
        return [Sighting(entry, self._confidence)] if entry is not None else []

    def check(self) -> Optional[str]:
        return None

    @property
    def configured(self) -> bool:
        return True

    @property
    def describe(self) -> str:
        return ("fake " + self._label) if self._label else "fake"


class HttpArrowSource(ArrowSource):
    """The laptop's /detect (Task 1's model, its arrow classes), through a VisionClient
    of its own with the short Task 2 timeout. check() is GET /health."""

    OBJECT_ID = "arrow"

    def __init__(self, base_url: str, timeout_s: float, health_timeout_s: float = 1.0,
                 session: Optional[object] = None) -> None:
        self._base = base_url.rstrip("/")
        self._client = VisionClient(base_url, timeout_s, session=session)
        self._health_timeout_s = health_timeout_s

    def sightings(self, jpeg: bytes) -> List[Sighting]:
        verdict = self._client.detect(jpeg, self.OBJECT_ID)
        if verdict.status == "target" and verdict.competition_id in ARROW_IDS:
            return [Sighting(ARROW_IDS[verdict.competition_id], verdict.confidence or 0.0)]
        return []

    def check(self) -> Optional[str]:
        return self._client.health(self._health_timeout_s)

    @property
    def configured(self) -> bool:
        return self._client.configured

    @property
    def describe(self) -> str:
        return "http " + (self._base or "(no URL)")


# --- on-Pi inference ------------------------------------------------------------------
# The letterbox, quantise/dequantise and output-row parsing below follow Jerick's
# image-rec/rpi/inference/tflite_detector.py on this group's CV branch. They are
# re-written here rather than imported because that package is also named `rpi`.
# Boxes and NMS are dropped: the vote only needs each frame's best arrow per direction.

def _importable(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def load_labels(path: str) -> List[str]:
    """The exporter's labels file: a JSON list, or an object keyed "0", "1", ..."""
    with io.open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, dict):
        labels = [data.get(str(index)) for index in range(len(data))]
    elif isinstance(data, list):
        labels = data
    else:
        raise ValueError("labels must be a JSON list or a zero-indexed object")
    if not labels or not all(isinstance(label, str) and label for label in labels):
        raise ValueError("labels must be non-empty strings")
    return labels


def label_direction(label: str) -> Optional[str]:
    """'Left Arrow' -> 'left', 'arrow_right' -> 'right', anything else -> None."""
    text = label.strip().lower()
    for direction in DIRECTIONS:
        if direction in text:
            return direction
    return None


def best_sightings(output: object, labels: Sequence[str]) -> List[Sighting]:
    """YOLOv8 raw output, (1, 4 + classes, N) or (1, N, 4 + classes), with or without
    the batch axis -> the most confident sighting of each direction, best first.
    Thresholding is the vote's job: this returns whatever the model scored."""
    import numpy as np
    prediction = np.asarray(output, dtype=np.float32)
    if prediction.ndim == 3 and prediction.shape[0] == 1:
        prediction = prediction[0]
    if prediction.ndim != 2:
        raise ValueError("expected one two-dimensional YOLO output, got shape %s" % (prediction.shape,))
    attributes = 4 + len(labels)
    if prediction.shape[1] == attributes:
        rows = prediction
    elif prediction.shape[0] == attributes:
        rows = prediction.T
    else:
        raise ValueError("YOLO output shape %s does not match %d labels" % (prediction.shape, len(labels)))
    scores = rows[:, 4:]
    if len(scores) == 0:
        return []
    # As the reference does: a row counts only for its best-scoring class. YOLOv8 class
    # scores are independent sigmoids, so a row scoring Up 0.80 / Right 0.78 is an up
    # arrow, not a 0.78 right arrow - the column maximum alone would say otherwise.
    winners = scores.argmax(axis=1)
    best = {}   # type: Dict[str, float]
    for index, label in enumerate(labels):
        direction = label_direction(label)
        if direction is None:
            continue
        mine = scores[winners == index, index]
        if len(mine) == 0:
            continue
        top = float(mine.max())
        if top > best.get(direction, 0.0):
            best[direction] = top
    return sorted((Sighting(d, c) for d, c in best.items()), key=lambda s: -s.confidence)


def _quantize(tensor: object, details: dict) -> object:
    import numpy as np
    dtype = np.dtype(details["dtype"])
    if np.issubdtype(dtype, np.floating):
        return tensor.astype(dtype)
    scale, zero_point = details.get("quantization", (0.0, 0))
    if not scale:
        raise ValueError("integer input tensor has no quantization scale")
    limits = np.iinfo(dtype)
    return np.clip(np.round(tensor / scale + zero_point), limits.min, limits.max).astype(dtype)


def _dequantize(tensor: object, details: dict) -> object:
    import numpy as np
    if np.issubdtype(tensor.dtype, np.floating):
        return tensor.astype(np.float32)
    scale, zero_point = details.get("quantization", (0.0, 0))
    if not scale:
        raise ValueError("integer output tensor has no quantization scale")
    return (tensor.astype(np.float32) - zero_point) * scale


def _letterbox_tensor(frame: object, width: int, height: int, input_details: dict) -> object:
    """BGR frame -> the model's [1, height, width, 3] input: letterboxed on grey (114),
    RGB, 0..1, quantised to the input's dtype and scale."""
    import cv2
    import numpy as np
    source_height, source_width = frame.shape[:2]
    scale = min(width / float(source_width), height / float(source_height))
    resized_width = max(1, int(round(source_width * scale)))
    resized_height = max(1, int(round(source_height * scale)))
    resized = cv2.resize(frame, (resized_width, resized_height))
    canvas = np.full((height, width, 3), 114, dtype=np.uint8)
    pad_x = (width - resized_width) // 2
    pad_y = (height - resized_height) // 2
    canvas[pad_y:pad_y + resized_height, pad_x:pad_x + resized_width] = resized
    normalised = canvas[:, :, ::-1].astype(np.float32) / 255.0      # BGR -> RGB
    return _quantize(normalised[np.newaxis, ...], input_details)


class TfliteArrowSource(ArrowSource):
    """On-Pi inference with tflite-runtime and OpenCV, both imported lazily. Optional:
    `configured` needs the model, the labels and tflite_runtime; check() loads them.

    Adapted from Jerick's image-rec/rpi/inference/tflite_detector.py (this group's CV
    branch, origin/jerick-cv): the letterbox, quantisation and row parsing are his; the
    boxes, NMS and competition-id map are dropped because the vote only needs each
    frame's best arrow per direction. The model is image-rec/training/export_int8.py's
    Ultralytics YOLOv8 export with nms off, whose one raw output is (1, 4 + classes, N).

    `interpreter_factory` is a test seam: a callable returning an object with the
    tflite Interpreter's allocate_tensors/get_input_details/get_output_details/
    set_tensor/invoke/get_tensor methods. None means the real tflite_runtime.

    [RULE DELTA Task 2 spec §0 #3, §3.2] `record_url`, when set, is a fire-and-forget
    POST of every read frame to `{record_url}/detect` for storage only - the same
    endpoint and multipart shape Task 1 and HttpArrowSource use. This source decides
    the direction on its own; the PC server's raw+annotated capture (pc_server/storage.py)
    is what lets the RAW-image-with-bounding-box requirement (rules.md Task 2 rule 8,
    FAQ 16) be met even when the laptop never makes the arrow decision. The POST's
    result is discarded and a failure is only logged - it must never affect, delay
    past its own timeout, or fail the read."""

    def __init__(
        self,
        model_path: str,
        labels_path: str,
        threads: int = 2,
        interpreter_factory: Optional[Callable[[], object]] = None,
        record_url: str = "",
        record_timeout_s: float = 1.0,
        record_session: Optional[object] = None,
    ) -> None:
        self._model_path = model_path
        self._labels_path = labels_path
        self._threads = threads
        self._interpreter_factory = interpreter_factory
        self._labels = None        # type: Optional[List[str]]
        self._interpreter = None   # type: Optional[object]
        self._input = None         # type: Optional[dict]
        self._output = None        # type: Optional[dict]
        self._size = (0, 0)        # width, height
        self._record_url = record_url.rstrip("/") if record_url else ""
        self._record_timeout_s = record_timeout_s
        self._record_session = record_session

    @property
    def configured(self) -> bool:
        return (os.path.isfile(self._model_path) and os.path.isfile(self._labels_path)
                and _importable("tflite_runtime"))

    @property
    def describe(self) -> str:
        return "tflite " + self._model_path

    def check(self) -> Optional[str]:
        if not os.path.isfile(self._model_path):
            return "Arrow model not found: %s" % self._model_path
        if not os.path.isfile(self._labels_path):
            return "Arrow labels not found: %s" % self._labels_path
        if not _importable("tflite_runtime"):
            return "tflite_runtime not installed"
        if not _importable("cv2"):
            return "OpenCV (cv2) not installed"
        try:
            self._load()
        except Exception as error:
            return "Arrow model failed to load: %s" % error
        return None

    def _load(self) -> None:
        if self._interpreter is not None:
            return
        labels = load_labels(self._labels_path)
        if self._interpreter_factory is not None:
            interpreter = self._interpreter_factory()
        else:
            from tflite_runtime.interpreter import Interpreter
            interpreter = Interpreter(model_path=self._model_path, num_threads=self._threads)
        interpreter.allocate_tensors()
        input_details = interpreter.get_input_details()[0]
        shape = tuple(int(value) for value in input_details["shape"])
        if len(shape) != 4 or shape[0] != 1 or shape[3] != 3:
            raise ValueError("expected a [1, height, width, 3] input tensor, got %s" % (shape,))
        self._labels = labels
        self._interpreter = interpreter
        self._input = input_details
        self._output = interpreter.get_output_details()[0]
        self._size = (shape[2], shape[1])
        LOG.info("arrow model %s loaded: input %dx%d, labels %s", self._model_path, shape[2], shape[1], labels)

    def _record(self, jpeg: bytes) -> None:
        """[RULE DELTA] Fire-and-forget storage POST; never raises, never blocks the
        decision on its outcome. Skipped entirely when no record_url is configured."""
        if not self._record_url:
            return
        try:
            import requests
            session = self._record_session or requests
            session.post(
                self._record_url + "/detect",
                files={"image": ("capture.jpg", jpeg, "image/jpeg")},
                data={"object_id": HttpArrowSource.OBJECT_ID},
                timeout=self._record_timeout_s,
            )
        except Exception as error:      # never let a storage failure touch the read
            LOG.warning("arrow frame storage POST failed: %s", error)

    def sightings(self, jpeg: bytes) -> List[Sighting]:
        self._record(jpeg)
        try:
            self._load()
            import cv2
            import numpy as np
            frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                LOG.warning("arrow frame did not decode")
                return []
            tensor = _letterbox_tensor(frame, self._size[0], self._size[1], self._input)
            self._interpreter.set_tensor(self._input["index"], tensor)
            self._interpreter.invoke()
            output = _dequantize(self._interpreter.get_tensor(self._output["index"]), self._output)
            return best_sightings(output, self._labels)
        except Exception as error:
            LOG.warning("tflite arrow inference failed: %s", error)
            return []


class Consensus:
    """The vote: a direction wins when it is the best sighting in at least `required`
    of the last `window` frames and the other direction appears in none of them.
    A confident dissent blocks; it slides out within `window` frames."""

    def __init__(self, required: int = 3, window: int = 5, min_confidence: float = 0.75) -> None:
        if not 1 <= required <= window:
            raise ValueError("consensus needs 1 <= required <= window, got %d/%d" % (required, window))
        self._required = required
        self._min_confidence = min_confidence
        self._frames = deque(maxlen=window)   # type: Deque[Optional[str]]

    def observe(self, sightings: Sequence[Sighting]) -> Optional[str]:
        best = None   # type: Optional[Sighting]
        for sighting in sightings:
            if sighting.direction not in DIRECTIONS or sighting.confidence < self._min_confidence:
                continue
            if best is None or sighting.confidence > best.confidence:
                best = sighting
        self._frames.append(best.direction if best is not None else None)
        counts = {direction: 0 for direction in DIRECTIONS}
        for direction in self._frames:
            if direction is not None:
                counts[direction] += 1
        LOG.debug("arrow vote: frame=%s window=%s", best, list(self._frames))
        for direction in DIRECTIONS:
            other = DIRECTIONS[1] if direction == DIRECTIONS[0] else DIRECTIONS[0]
            if counts[direction] >= self._required and counts[other] == 0:
                return direction
        return None

    def reset(self) -> None:
        self._frames.clear()


def read_arrow(
    camera: Camera,
    source: ArrowSource,
    consensus: Consensus,
    timeout_s: float,
    abort: threading.Event,
    settle_s: float = 0.0,
) -> Optional[str]:
    """Settle, then capture -> sightings -> observe until a decision, the timeout or abort.
    None means no decision; the caller tells a timeout from a stop with abort.is_set().
    Abort is checked between frames; one frame is bounded by the source (its HTTP
    timeout, or one inference), which is why STOP is noticed within ~2 s worst case."""
    consensus.reset()
    if abort.wait(settle_s):
        return None
    end = time.monotonic() + timeout_s
    frames = 0
    while not abort.is_set() and time.monotonic() < end:
        try:
            jpeg = camera.capture_jpeg()
        except CameraError as error:
            LOG.warning("camera failed during the arrow read: %s", error)
            frames += 1
            consensus.observe([])
            if abort.wait(0.1):          # do not spin (and flood the log) on a dead camera
                return None
            continue
        frames += 1
        decision = consensus.observe(source.sightings(jpeg))
        if decision is not None:
            LOG.info("arrow: %s after %d frame(s)", decision, frames)
            return decision
    LOG.info("arrow: no decision after %d frame(s)", frames)
    return None
