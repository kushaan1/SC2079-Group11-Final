"""Threaded capture using Buster's legacy ``picamera`` stack."""

import threading
import time
from typing import Any, Optional


class BusterCameraStream:
    """Continuously capture into a latest-frame buffer without blocking inference."""

    def __init__(
        self,
        width: int,
        height: int,
        framerate: int,
        rotation: int = 0,
    ) -> None:
        self.width = width
        self.height = height
        self.framerate = framerate
        self.rotation = rotation
        self._condition = threading.Condition()
        self._frame: Any = None
        self._sequence = 0
        self._stopped = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._camera: Any = None
        self._raw_capture: Any = None

    def start(self) -> "BusterCameraStream":
        if self._thread is not None:
            return self
        try:
            from picamera import PiCamera
            from picamera.array import PiRGBArray
        except ImportError as error:
            raise RuntimeError(
                "legacy picamera is required on Raspberry Pi OS Buster"
            ) from error

        self._camera = PiCamera()
        self._camera.resolution = (self.width, self.height)
        self._camera.framerate = self.framerate
        self._camera.rotation = self.rotation
        self._raw_capture = PiRGBArray(self._camera, size=(self.width, self.height))
        self._stopped.clear()
        self._thread = threading.Thread(target=self._capture_loop, name="buster-camera")
        self._thread.daemon = True
        self._thread.start()
        return self

    def _capture_loop(self) -> None:
        try:
            time.sleep(0.1)
            stream = self._camera.capture_continuous(
                self._raw_capture,
                format="bgr",
                use_video_port=True,
            )
            for captured in stream:
                if self._stopped.is_set():
                    break
                with self._condition:
                    self._frame = captured.array.copy()
                    self._sequence += 1
                    self._condition.notify_all()
                self._raw_capture.truncate(0)
                self._raw_capture.seek(0)
        finally:
            with self._condition:
                self._condition.notify_all()

    def read(self, timeout: Optional[float] = 2.0, after_sequence: int = 0) -> Any:
        """Return ``(sequence, BGR frame)`` newer than ``after_sequence``."""

        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while self._sequence <= after_sequence and not self._stopped.is_set():
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise TimeoutError("timed out waiting for a camera frame")
                self._condition.wait(remaining)
            if self._frame is None:
                raise RuntimeError("camera stream stopped before producing a frame")
            return self._sequence, self._frame.copy()

    def stop(self) -> None:
        self._stopped.set()
        with self._condition:
            self._condition.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._raw_capture is not None:
            self._raw_capture.close()
            self._raw_capture = None
        if self._camera is not None:
            self._camera.close()
            self._camera = None

    def __enter__(self) -> "BusterCameraStream":
        return self.start()

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.stop()
