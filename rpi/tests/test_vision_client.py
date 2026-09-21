import pytest

from rpi.model import Verdict
from rpi.vision_client import VisionClient, parse_verdict


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

    def post(self, url, files=None, data=None, timeout=None):
        self.calls.append((url, files, data, timeout))
        if self.error is not None:
            raise self.error
        return self.response


def target(cid, conf):
    return {"schema_version": "1.0", "object_id": "B3", "status": "target",
            "detection": {"label": "x", "confidence": conf, "bbox": [0, 0, 10, 10],
                          "kind": "target", "competition_id": cid, "model_class_id": 1},
            "detections": [], "artifacts": {}, "error": None}


@pytest.mark.parametrize("status_code,body,expected", [
    (200, target(38, 0.93), Verdict("target", 38, 0.93)),
    (200, {"status": "bullseye", "detection": {"kind": "bullseye", "confidence": 0.8, "competition_id": None}},
     Verdict("bullseye", None, 0.8)),
    (200, {"status": "no_detection", "detection": None}, Verdict("no_detection")),
    (200, {"status": "error", "detection": None, "error": "inference failed"}, Verdict("error")),
    (200, target(41, 0.9), Verdict("error")),           # outside 11-40
    (200, {"status": "target", "detection": None}, Verdict("error")),
    (400, {"error": "multipart field 'image' is required"}, Verdict("error")),
    (500, None, Verdict("error")),
    (200, [1, 2], Verdict("error")),
])
def test_parse_verdict(status_code, body, expected):
    assert parse_verdict(status_code, body) == expected


def test_detect_posts_the_jpeg_and_object_id():
    session = FakeSession(FakeResponse(200, target(11, 0.5)))
    client = VisionClient("http://laptop:4000/", 10.0, session=session)
    assert client.detect(b"\xff\xd8jpeg", "B3") == Verdict("target", 11, 0.5)
    url, files, data, timeout = session.calls[0]
    assert url == "http://laptop:4000/detect"
    assert files == {"image": ("capture.jpg", b"\xff\xd8jpeg", "image/jpeg")}
    assert data == {"object_id": "B3"}
    assert timeout == 10.0


def test_detect_never_raises():
    import requests
    session = FakeSession(error=requests.ConnectionError("refused"))
    assert VisionClient("http://laptop:4000", 10.0, session=session).detect(b"", "B1") == Verdict("error")


def test_unconfigured_client_is_an_error_without_a_request():
    session = FakeSession(FakeResponse(200, target(11, 0.5)))
    client = VisionClient("", 10.0, session=session)
    assert client.configured is False
    assert client.detect(b"", "B1") == Verdict("error")
    assert session.calls == []
