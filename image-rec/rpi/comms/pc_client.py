"""Task 1 multipart HTTP client for the host-PC detector."""

from typing import Any, Dict, Optional


class PCDetectionClient:
    def __init__(
        self,
        detect_url: str,
        timeout_seconds: float,
        session: Optional[Any] = None,
    ) -> None:
        if session is None:
            import requests

            session = requests.Session()
        self._session = session
        self.detect_url = detect_url
        self.timeout_seconds = timeout_seconds

    def detect_frame(self, frame: Any, object_id: str) -> Dict[str, Any]:
        import cv2

        encoded, buffer = cv2.imencode(".jpg", frame)
        if not encoded:
            raise ValueError("camera frame could not be JPEG-encoded")
        response = self._session.post(
            self.detect_url,
            files={"image": ("capture.jpg", buffer.tobytes(), "image/jpeg")},
            data={"object_id": str(object_id)},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        self._validate_payload(payload)
        return payload

    @staticmethod
    def _validate_payload(payload: Dict[str, Any]) -> None:
        if payload.get("schema_version") != "1.0":
            raise ValueError("unsupported image-recognition schema version")
        if payload.get("status") not in ("target", "bullseye", "no_detection"):
            raise ValueError("invalid image-recognition status")
        status = payload["status"]
        detection = payload.get("detection")
        if status in ("target", "bullseye") and detection is None:
            raise ValueError("{} status requires a detection".format(status))
        if status == "no_detection" and detection is not None:
            raise ValueError("no_detection status cannot contain a chosen detection")
        if detection is not None:
            competition_id = detection.get("competition_id")
            if competition_id is not None and competition_id not in range(11, 41):
                raise ValueError("competition ID outside the supported 11-40 range")
            if status == "target" and competition_id is None:
                raise ValueError("target status requires a competition ID")
            if status == "bullseye" and competition_id is not None:
                raise ValueError("bullseye status cannot contain a competition ID")
