import pytest

from rpi.camera.buster_stream import BusterCameraStream


class BrokenCamera:
    def capture_continuous(self, *args, **kwargs):
        raise OSError("camera disconnected")


def test_capture_failure_stops_stream_and_rejects_stale_frame(monkeypatch):
    monkeypatch.setattr("rpi.camera.buster_stream.time.sleep", lambda ignored: None)
    stream = BusterCameraStream(640, 480, 20)
    stream._camera = BrokenCamera()
    stream._raw_capture = object()
    stream._frame = object()
    stream._sequence = 4

    stream._capture_loop()

    assert stream._stopped.is_set()
    with pytest.raises(RuntimeError, match="newer frame") as captured:
        stream.read(after_sequence=4)
    assert isinstance(captured.value.__cause__, OSError)
