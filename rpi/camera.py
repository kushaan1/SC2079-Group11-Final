"""One JPEG on demand (spec §5.9). Legacy `picamera` on Buster; a fixture file on a laptop."""

import io
import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Optional

LOG = logging.getLogger(__name__)

FIXTURE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "frame.jpg")


class CameraError(Exception):
    pass


class Camera(ABC):
    @abstractmethod
    def start(self) -> None:
        pass

    @abstractmethod
    def capture_jpeg(self) -> bytes:
        pass

    @abstractmethod
    def close(self) -> None:
        pass


class PiCameraLegacy(Camera):
    """Raspberry Pi OS Buster's `picamera` (MMAL). Not picamera2, not libcamera."""

    def __init__(self, width: int, height: int, rotation: int, warmup_s: float = 2.0) -> None:
        self._size = (width, height)
        self._rotation = rotation
        self._warmup_s = warmup_s
        self._camera = None  # type: Optional[object]

    def start(self) -> None:
        try:
            from picamera import PiCamera
        except ImportError:
            raise CameraError("picamera not installed: apt install python3-picamera and "
                              "create the venv with --system-site-packages")
        try:
            camera = PiCamera()
            camera.resolution = self._size
            camera.rotation = self._rotation
        except Exception as error:
            raise CameraError("camera failed to open: %s" % error)
        self._camera = camera
        time.sleep(self._warmup_s)   # the sensor needs a moment for exposure to settle
        LOG.info("camera ready %sx%s rotation %s", self._size[0], self._size[1], self._rotation)

    def capture_jpeg(self) -> bytes:
        if self._camera is None:
            raise CameraError("camera not started")
        buffer = io.BytesIO()
        try:
            self._camera.capture(buffer, format="jpeg", use_video_port=True)
        except Exception as error:
            raise CameraError("capture failed: %s" % error)
        return buffer.getvalue()

    def close(self) -> None:
        camera, self._camera = self._camera, None
        if camera is not None:
            try:
                camera.close()
            except Exception:
                pass


class FakeCamera(Camera):
    """Returns one file's bytes every time. `--fake-camera`."""

    def __init__(self, path: Optional[str] = None) -> None:
        self._path = path or FIXTURE_PATH
        self._frame = None  # type: Optional[bytes]

    def start(self) -> None:
        try:
            with open(self._path, "rb") as handle:
                self._frame = handle.read()
        except OSError as error:
            raise CameraError("fake camera cannot read %s: %s" % (self._path, error))
        LOG.info("fake camera serving %s (%d bytes)", self._path, len(self._frame))

    def capture_jpeg(self) -> bytes:
        if self._frame is None:
            raise CameraError("camera not started")
        return self._frame

    def close(self) -> None:
        pass
