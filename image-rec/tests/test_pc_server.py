from io import BytesIO

from pc_server.app import create_app
from pc_server.detector import InvalidImageError
from vision.config import PCConfig
from vision.contracts import BoundingBox, Detection


class FakeDetector:
    def detect(self, image_bytes):
        assert image_bytes == b"fake-jpeg"
        return FakeImage(), [
            Detection("Left Arrow", 0.91, BoundingBox(1, 2, 20, 30), "target", 39, 0)
        ]


class InvalidDetector:
    def detect(self, image_bytes):
        raise InvalidImageError("bad image")


class FakeImage:
    def copy(self):
        return self


class FakeStore:
    def __init__(self):
        self.scheduled = []

    def schedule(self, image, result):
        self.scheduled.append((image, result))
        return "captures/raw/example.jpg", "captures/annotated/example.jpg"


def config(tmp_path):
    return PCConfig.from_env({"VISION_CAPTURE_DIR": str(tmp_path)})


def test_health_endpoint(tmp_path):
    app = create_app(config(tmp_path), FakeDetector(), FakeStore())
    response = app.test_client().get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"schema_version": "1.0", "status": "ok"}


def test_detect_contract_and_async_artifact_names(tmp_path):
    store = FakeStore()
    app = create_app(config(tmp_path), FakeDetector(), store)
    response = app.test_client().post(
        "/detect",
        data={"object_id": "obstacle-7", "image": (BytesIO(b"fake-jpeg"), "capture.jpg")},
    )
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["status"] == "target"
    assert payload["detection"]["competition_id"] == 39
    assert payload["artifacts"]["raw_image"].endswith("example.jpg")
    assert store.scheduled[0][1].object_id == "obstacle-7"


def test_invalid_requests_are_400(tmp_path):
    app = create_app(config(tmp_path), FakeDetector(), FakeStore())
    client = app.test_client()
    assert client.post("/detect", data={}).status_code == 400
    response = client.post(
        "/detect",
        data={"object_id": "x", "image": (BytesIO(b""), "capture.jpg")},
    )
    assert response.status_code == 400


def test_invalid_image_is_400(tmp_path):
    app = create_app(config(tmp_path), InvalidDetector(), FakeStore())
    response = app.test_client().post(
        "/detect",
        data={"object_id": "x", "image": (BytesIO(b"bad"), "capture.jpg")},
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "bad image"
