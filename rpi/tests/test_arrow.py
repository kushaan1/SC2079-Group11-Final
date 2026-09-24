import json
import threading
import time

import pytest
import requests

import rpi.arrow as arrow_module
from rpi.arrow import (
    ARROW_IDS, DIRECTIONS, Consensus, FakeArrowSource, HttpArrowSource, Sighting,
    TfliteArrowSource, best_sightings, label_direction, load_labels, read_arrow,
    _dequantize, _quantize,
)
from rpi.camera import CameraError, FakeCamera


def left(confidence=0.9):
    return Sighting("left", confidence)


def right(confidence=0.9):
    return Sighting("right", confidence)


# --- ids (spec §5.1) --------------------------------------------------------------

def test_arrow_ids_map_the_competition_numbers():
    assert ARROW_IDS == {38: "right", 39: "left"}
    assert DIRECTIONS == ("left", "right")


# --- consensus (spec §5.1) ----------------------------------------------------------

def test_three_agreeing_frames_decide_on_the_third():
    vote = Consensus(required=3, window=5, min_confidence=0.75)
    assert vote.observe([left()]) is None
    assert vote.observe([left()]) is None
    assert vote.observe([left()]) == "left"


def test_low_confidence_sightings_do_not_count():
    vote = Consensus(required=3, window=5, min_confidence=0.75)
    for _ in range(5):
        assert vote.observe([left(0.5)]) is None


def test_the_frames_best_sighting_is_the_one_counted():
    vote = Consensus(required=3, window=5, min_confidence=0.75)
    frame = [left(0.8), right(0.95)]
    assert vote.observe(frame) is None
    assert vote.observe(frame) is None
    assert vote.observe(frame) == "right"


def test_a_confident_dissent_blocks_until_it_slides_out():
    vote = Consensus(required=3, window=5, min_confidence=0.75)
    frames = [left(), right(), left(), left(), left(), left(), left()]
    results = [vote.observe([sighting]) for sighting in frames]
    # window after frame 5 = L R L L L (four lefts, one right): blocked;
    # after frame 6 = R L L L L: still blocked; after frame 7 = L L L L L: decided.
    assert results == [None, None, None, None, None, None, "left"]


def test_empty_frames_push_agreeing_frames_out_of_the_window():
    vote = Consensus(required=3, window=5, min_confidence=0.75)
    assert vote.observe([left()]) is None
    assert vote.observe([left()]) is None
    for _ in range(4):
        assert vote.observe([]) is None
    assert vote.observe([left()]) is None      # window is now [] [] [] [] L


def test_reset_forgets_the_window():
    vote = Consensus(required=3, window=5, min_confidence=0.75)
    vote.observe([left()])
    vote.observe([left()])
    vote.reset()
    assert vote.observe([left()]) is None
    assert vote.observe([left()]) is None
    assert vote.observe([left()]) == "left"


def test_required_must_fit_the_window():
    with pytest.raises(ValueError):
        Consensus(required=6, window=5)
    with pytest.raises(ValueError):
        Consensus(required=0, window=5)


# --- fake source ----------------------------------------------------------------------

def test_fake_source_serves_one_entry_per_frame_then_nothing():
    source = FakeArrowSource(["left", None, "right"])
    assert source.sightings(b"jpeg") == [Sighting("left", 1.0)]
    assert source.sightings(b"jpeg") == []
    assert source.sightings(b"jpeg") == [Sighting("right", 1.0)]
    assert source.sightings(b"jpeg") == []
    assert source.calls == 4


def test_fake_source_cycles_when_asked():
    source = FakeArrowSource(["left", "right"], cycle=True)
    seen = [source.sightings(b"")[0].direction for _ in range(5)]
    assert seen == ["left", "right", "left", "right", "left"]


def test_fake_source_for_reads_repeats_each_direction():
    source = FakeArrowSource.for_reads(["left", "right"], frames=3)
    seen = [source.sightings(b"") for _ in range(7)]
    assert [s[0].direction for s in seen[:6]] == ["left"] * 3 + ["right"] * 3
    assert seen[6] == []
    assert source.describe == "fake left,right"


def test_fake_source_rejects_unknown_directions():
    with pytest.raises(ValueError):
        FakeArrowSource(["up"])


def test_fake_source_is_always_configured_and_healthy():
    source = FakeArrowSource([])
    assert source.configured is True
    assert source.check() is None
    assert source.describe == "fake"


# --- read loop (spec §5.1, §4) ----------------------------------------------------------

class CountingCamera(FakeCamera):
    def __init__(self):
        super().__init__()
        self.captures = 0

    def capture_jpeg(self):
        self.captures += 1
        return super().capture_jpeg()


class BrokenCamera(FakeCamera):
    def capture_jpeg(self):
        raise CameraError("no data from sensor")


class FlakyCamera(CountingCamera):
    """Fails on the first capture only."""
    def capture_jpeg(self):
        if self.captures == 0:
            self.captures += 1
            raise CameraError("first frame lost")
        return super().capture_jpeg()


class BlockingSource(FakeArrowSource):
    """Never sees an arrow; every frame takes `frame_s` (the way an HTTP timeout would)."""
    def __init__(self, frame_s=0.2):
        super().__init__([])
        self._frame_s = frame_s
        self.started = threading.Event()

    def sightings(self, jpeg):
        self.calls += 1
        self.started.set()
        time.sleep(self._frame_s)
        return []


def camera():
    cam = CountingCamera()
    cam.start()
    return cam


def vote():
    return Consensus(required=3, window=5, min_confidence=0.75)


def test_read_arrow_decides_from_the_fake_camera_and_source():
    cam = camera()
    source = FakeArrowSource(["left", "left", "left"])
    assert read_arrow(cam, source, vote(), 1.0, threading.Event()) == "left"
    assert cam.captures == 3
    assert source.calls == 3


def test_read_arrow_times_out_with_no_arrow():
    source = FakeArrowSource([None] * 1000)
    started = time.monotonic()
    assert read_arrow(camera(), source, vote(), 0.05, threading.Event()) is None
    assert time.monotonic() - started >= 0.05
    assert source.calls >= 1


def test_read_arrow_with_abort_already_set_captures_nothing():
    cam = camera()
    abort = threading.Event()
    abort.set()
    assert read_arrow(cam, FakeArrowSource(["left"] * 3), vote(), 1.0, abort, settle_s=0.1) is None
    assert cam.captures == 0


def test_read_arrow_stops_within_one_frame_when_aborted():
    source = BlockingSource(frame_s=0.2)
    abort = threading.Event()
    outcome = []
    thread = threading.Thread(target=lambda: outcome.append(read_arrow(camera(), source, vote(), 5.0, abort)))
    started = time.monotonic()
    thread.start()
    assert source.started.wait(1.0)
    abort.set()
    thread.join(2.0)
    assert outcome == [None]
    assert time.monotonic() - started < 1.0     # one 0.2 s frame, not the 5 s timeout
    assert source.calls == 1                     # no second frame was started


def test_read_arrow_treats_a_camera_failure_as_an_empty_frame():
    cam = BrokenCamera()
    cam.start()
    source = FakeArrowSource(["left"] * 3)
    assert read_arrow(cam, source, vote(), 0.05, threading.Event()) is None
    assert source.calls == 0


def test_read_arrow_recovers_after_one_camera_failure():
    cam = FlakyCamera()
    cam.start()
    assert read_arrow(cam, FakeArrowSource(["right"] * 3), vote(), 1.0, threading.Event()) == "right"


def test_read_arrow_settles_before_the_first_frame():
    started = time.monotonic()
    result = read_arrow(camera(), FakeArrowSource(["left"] * 3), vote(), 1.0, threading.Event(), settle_s=0.1)
    assert result == "left"
    assert time.monotonic() - started >= 0.09     # Event.wait(0.1) can return ~5 ms early on Windows


# --- HTTP source (spec §3.2) ---------------------------------------------------------

class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []
        self.gets = []

    def post(self, url, files=None, data=None, timeout=None):
        self.calls.append((url, files, data, timeout))
        if self.error is not None:
            raise self.error
        return self.response

    def get(self, url, timeout=None):
        self.gets.append((url, timeout))
        if self.error is not None:
            raise self.error
        return self.response


def target(cid, conf):
    return {"schema_version": "1.0", "object_id": "arrow", "status": "target",
            "detection": {"label": "x", "confidence": conf, "bbox": [0, 0, 10, 10],
                          "kind": "target", "competition_id": cid, "model_class_id": 1},
            "detections": [], "artifacts": {}, "error": None}


@pytest.mark.parametrize("body,expected", [
    (target(39, 0.93), [Sighting("left", 0.93)]),
    (target(38, 0.81), [Sighting("right", 0.81)]),
    (target(16, 0.99), []),                                            # a number, not an arrow
    ({"status": "bullseye", "detection": {"kind": "bullseye", "confidence": 0.8, "competition_id": None}}, []),
    ({"status": "error", "detection": None}, []),
])
def test_http_source_maps_arrow_targets(body, expected):
    source = HttpArrowSource("http://laptop:4000", 2.0, session=FakeSession(FakeResponse(200, body)))
    assert source.sightings(b"\xff\xd8jpeg") == expected


def test_http_source_uses_its_own_short_timeout_and_object_id():
    session = FakeSession(FakeResponse(200, target(39, 0.9)))
    HttpArrowSource("http://laptop:4000/", 2.0, session=session).sightings(b"\xff\xd8jpeg")
    url, files, data, timeout = session.calls[0]
    assert url == "http://laptop:4000/detect"
    assert files == {"image": ("capture.jpg", b"\xff\xd8jpeg", "image/jpeg")}
    assert data == {"object_id": "arrow"}
    assert timeout == 2.0                       # not Task 1's VISION_TIMEOUT_S


def test_http_source_check_is_the_health_endpoint():
    session = FakeSession(FakeResponse(200, {"status": "ok"}))
    source = HttpArrowSource("http://laptop:4000", 2.0, health_timeout_s=1.0, session=session)
    assert source.check() is None
    assert session.gets == [("http://laptop:4000/health", 1.0)]


def test_http_source_check_reports_an_unreachable_server():
    session = FakeSession(error=requests.ConnectionError("refused"))
    source = HttpArrowSource("http://laptop:4000", 2.0, session=session)
    assert source.check() == "Vision server unreachable"
    assert source.sightings(b"\xff\xd8jpeg") == []        # never raises


def test_http_source_unconfigured_without_a_url():
    source = HttpArrowSource("", 2.0, session=FakeSession(FakeResponse(200, target(39, 0.9))))
    assert source.configured is False
    assert source.describe == "http (no URL)"


def test_http_source_describe():
    assert HttpArrowSource("http://10.0.0.2:4000/", 2.0, session=FakeSession()).describe == "http http://10.0.0.2:4000"


# --- TFLite source (spec §3.2, §5.1) ------------------------------------------------------

LABELS = ["Up Arrow", "Down Arrow", "Right Arrow", "Left Arrow"]   # the exporter's arrow-labels.json


def model_files(tmp_path, model=True, labels=True):
    model_path = tmp_path / "best_arrows.tflite"
    labels_path = tmp_path / "arrow-labels.json"
    if model:
        model_path.write_bytes(b"TFL3")
    if labels:
        labels_path.write_text(json.dumps(LABELS), encoding="utf-8")
    return str(model_path), str(labels_path)


def test_tflite_source_unconfigured_when_the_model_is_missing(tmp_path):
    model_path, labels_path = model_files(tmp_path, model=False)
    source = TfliteArrowSource(model_path, labels_path)
    assert source.configured is False
    assert source.check() == "Arrow model not found: %s" % model_path


def test_tflite_source_unconfigured_without_tflite_runtime(tmp_path, monkeypatch):
    model_path, labels_path = model_files(tmp_path)
    monkeypatch.setattr(arrow_module, "_importable", lambda name: name != "tflite_runtime")
    source = TfliteArrowSource(model_path, labels_path)
    assert source.configured is False
    assert source.check() == "tflite_runtime not installed"


def test_tflite_source_check_reports_missing_labels(tmp_path):
    model_path, labels_path = model_files(tmp_path, labels=False)
    assert TfliteArrowSource(model_path, labels_path).check() == "Arrow labels not found: %s" % labels_path


def test_tflite_source_describe(tmp_path):
    model_path, labels_path = model_files(tmp_path)
    assert TfliteArrowSource(model_path, labels_path).describe == "tflite " + model_path


def test_tflite_sightings_never_raise(tmp_path):
    model_path, labels_path = model_files(tmp_path, model=False)
    assert TfliteArrowSource(model_path, labels_path).sightings(b"\xff\xd8jpeg") == []


def test_load_labels_accepts_a_list_and_a_zero_indexed_object(tmp_path):
    as_list = tmp_path / "list.json"
    as_list.write_text(json.dumps(LABELS), encoding="utf-8")
    as_dict = tmp_path / "dict.json"
    as_dict.write_text(json.dumps({"1": "Down Arrow", "0": "Up Arrow", "3": "Left Arrow", "2": "Right Arrow"}),
                       encoding="utf-8")
    assert load_labels(str(as_list)) == LABELS
    assert load_labels(str(as_dict)) == LABELS


@pytest.mark.parametrize("payload", [{}, ["", "x"], 5])
def test_load_labels_rejects_garbage(tmp_path, payload):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        load_labels(str(path))


@pytest.mark.parametrize("label,direction", [
    ("Left Arrow", "left"), ("Right Arrow", "right"), ("arrow_left", "left"),
    ("Up Arrow", None), ("Stop sign", None),
])
def test_label_direction(label, direction):
    assert label_direction(label) == direction


ROWS = [   # cx, cy, w, h, then a score per label in LABELS order
    [0.5, 0.5, 0.2, 0.2, 0.01, 0.02, 0.05, 0.90],    # a left arrow
    [0.4, 0.4, 0.2, 0.2, 0.02, 0.01, 0.40, 0.10],    # a weak right arrow
    [0.1, 0.1, 0.1, 0.1, 0.95, 0.01, 0.03, 0.02],    # an up arrow: not ours
    [0.3, 0.3, 0.2, 0.2, 0.80, 0.01, 0.78, 0.02],    # up 0.80 beats right 0.78: an up arrow, not a right one
]


def summary(sightings):
    return [(s.direction, round(s.confidence, 2)) for s in sightings]


def test_best_sightings_from_a_yolo_output():
    np = pytest.importorskip("numpy")
    output = np.array(ROWS, dtype=np.float32).T[np.newaxis]      # (1, 8, 4): the exporter's layout
    assert summary(best_sightings(output, LABELS)) == [("left", 0.9), ("right", 0.4)]   # the 0.78 row is an up arrow


def test_best_sightings_accepts_the_transposed_layout():
    np = pytest.importorskip("numpy")
    output = np.array(ROWS, dtype=np.float32)[np.newaxis]        # (1, 4, 8)
    assert summary(best_sightings(output, LABELS)) == [("left", 0.9), ("right", 0.4)]


def test_best_sightings_rejects_a_shape_that_does_not_match_the_labels():
    np = pytest.importorskip("numpy")
    with pytest.raises(ValueError):
        best_sightings(np.zeros((1, 7, 3), dtype=np.float32), LABELS)


def test_quantize_and_dequantize_round_trip_an_int8_tensor():
    np = pytest.importorskip("numpy")
    details = {"dtype": np.int8, "quantization": (1.0 / 256, -128)}
    values = np.array([[0.0, 0.5, 1.0]], dtype=np.float32)
    quantized = _quantize(values, details)
    assert quantized.dtype == np.int8
    assert quantized.tolist() == [[-128, 0, 127]]
    assert _dequantize(quantized, details)[0].tolist() == pytest.approx([0.0, 0.5, 0.996], abs=0.01)
    assert _quantize(values, {"dtype": np.float32}).tolist() == [[0.0, 0.5, 1.0]]


class FakeInterpreter:
    """The tflite Interpreter surface the source uses: an int8 32x32 input, one float output."""

    def __init__(self, np, output):
        self._np = np
        self._output = output
        self.tensors = {}

    def allocate_tensors(self):
        pass

    def get_input_details(self):
        return [{"index": 0, "shape": self._np.array([1, 32, 32, 3]), "dtype": self._np.int8,
                 "quantization": (1.0 / 255, -128)}]

    def get_output_details(self):
        return [{"index": 1, "dtype": self._np.float32, "quantization": (0.0, 0)}]

    def set_tensor(self, index, tensor):
        self.tensors[index] = tensor

    def invoke(self):
        pass

    def get_tensor(self, index):
        return self._output


def test_tflite_inference_path_with_a_fake_interpreter(tmp_path, monkeypatch):
    np = pytest.importorskip("numpy")
    import sys
    import types
    model_path, labels_path = model_files(tmp_path)
    # A stand-in cv2: a 48x64 BGR "decoded" frame, and a resize that returns the asked-for size.
    stub = types.SimpleNamespace(
        IMREAD_COLOR=1,
        imdecode=lambda buffer, flag: np.zeros((48, 64, 3), dtype=np.uint8),
        resize=lambda frame, size: np.zeros((size[1], size[0], 3), dtype=np.uint8),
    )
    monkeypatch.setitem(sys.modules, "cv2", stub)
    interpreter = FakeInterpreter(np, np.array(ROWS, dtype=np.float32).T[np.newaxis])
    source = TfliteArrowSource(model_path, labels_path, interpreter_factory=lambda: interpreter)
    assert summary(source.sightings(b"\xff\xd8jpeg")) == [("left", 0.9), ("right", 0.4)]
    tensor = interpreter.tensors[0]
    assert tensor.shape == (1, 32, 32, 3) and tensor.dtype == np.int8
    # 48x64 letterboxed into 32x32: scale 0.5, 32x24 image with 4 grey rows top and bottom.
    assert int(tensor[0, 0, 0, 0]) == round(114 / 255 / (1 / 255)) - 128      # grey (114) pad, quantised
    assert int(tensor[0, 16, 16, 0]) == -128                                # black image pixel
    assert source.sightings(b"\xff\xd8jpeg") == source.sightings(b"\xff\xd8jpeg")   # loaded once, reusable


# --- TFLite source's record() side effect [RULE DELTA Task 2 spec §0 #3, §3.2] -------------

def test_tflite_source_records_every_frame_for_storage(tmp_path):
    model_path, labels_path = model_files(tmp_path, model=False)   # not configured: sightings() is a no-op
    session = FakeSession(FakeResponse(200, {"status": "ok"}))
    source = TfliteArrowSource(model_path, labels_path, record_url="http://laptop:4000",
                               record_session=session)
    source.sightings(b"\xff\xd8jpeg")
    assert len(session.calls) == 1
    url, files, data, timeout = session.calls[0]
    assert url == "http://laptop:4000/detect"
    assert files == {"image": ("capture.jpg", b"\xff\xd8jpeg", "image/jpeg")}
    assert data == {"object_id": "arrow"}
    assert timeout == 1.0


def test_tflite_source_skips_recording_without_a_url(tmp_path):
    model_path, labels_path = model_files(tmp_path, model=False)
    session = FakeSession(FakeResponse(200, {"status": "ok"}))
    TfliteArrowSource(model_path, labels_path, record_session=session).sightings(b"jpeg")
    assert session.calls == []


def test_tflite_source_record_failure_never_raises_or_blocks_the_read(tmp_path):
    model_path, labels_path = model_files(tmp_path, model=False)
    session = FakeSession(error=requests.ConnectionError("refused"))
    source = TfliteArrowSource(model_path, labels_path, record_url="http://laptop:4000",
                               record_session=session)
    assert source.sightings(b"jpeg") == []      # no exception, still an empty (unconfigured) read
