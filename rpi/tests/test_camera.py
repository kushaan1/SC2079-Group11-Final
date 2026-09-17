import pytest

from rpi.camera import FIXTURE_PATH, Camera, CameraError, FakeCamera, PiCameraLegacy


def test_fake_camera_returns_a_jpeg():
    camera = FakeCamera()
    camera.start()
    try:
        frame = camera.capture_jpeg()
        assert frame[:2] == b"\xff\xd8"
        assert frame[-2:] == b"\xff\xd9"
        assert camera.capture_jpeg() == frame
    finally:
        camera.close()


def test_fake_camera_reads_a_given_file(tmp_path):
    path = tmp_path / "x.jpg"
    path.write_bytes(b"\xff\xd8abc\xff\xd9")
    camera = FakeCamera(str(path))
    camera.start()
    assert camera.capture_jpeg() == b"\xff\xd8abc\xff\xd9"


def test_fake_camera_with_a_missing_file_fails_at_start(tmp_path):
    with pytest.raises(CameraError):
        FakeCamera(str(tmp_path / "missing.jpg")).start()


def test_fixture_path_points_at_the_shipped_frame():
    assert FIXTURE_PATH.endswith("frame.jpg")


def test_legacy_camera_reports_a_missing_picamera_clearly():
    # picamera is a Pi-only package; on the laptop it is absent by construction.
    camera = PiCameraLegacy(640, 480, 0, warmup_s=0.0)
    try:
        import picamera  # noqa: F401
    except ImportError:
        with pytest.raises(CameraError) as info:
            camera.start()
        assert "picamera" in str(info.value)
    else:
        pytest.skip("picamera present; this laptop is a Pi")


def test_capture_before_start_is_an_error():
    with pytest.raises(CameraError):
        PiCameraLegacy(640, 480, 0).capture_jpeg()
    assert issubclass(FakeCamera, Camera)
