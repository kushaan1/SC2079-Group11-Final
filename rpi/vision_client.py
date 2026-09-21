"""POST /detect on the image-recognition server -> Verdict (spec §3.4, §5.7).

Never raises: the worker decides what a failure means.
"""

import logging
from typing import Optional

import requests

from rpi.model import Verdict

LOG = logging.getLogger(__name__)

_STATUSES = ("target", "bullseye", "no_detection")


def parse_verdict(status_code: int, body: object) -> Verdict:
    if status_code != 200 or not isinstance(body, dict):
        return Verdict("error")
    status = body.get("status")
    if status not in _STATUSES:
        return Verdict("error")
    detection = body.get("detection") or {}
    if not isinstance(detection, dict):
        return Verdict("error")
    confidence = detection.get("confidence")
    confidence = float(confidence) if isinstance(confidence, (int, float)) else None
    if status == "target":
        competition_id = detection.get("competition_id")
        if not isinstance(competition_id, int) or not 11 <= competition_id <= 40:
            return Verdict("error")
        return Verdict("target", competition_id, confidence)
    return Verdict(status, None, confidence)


class VisionClient:
    def __init__(self, base_url: str, timeout_s: float, session: Optional[object] = None) -> None:
        self._base = base_url.rstrip("/")
        self._url = self._base + "/detect"
        self._timeout_s = timeout_s
        self._session = session or requests.Session()

    @property
    def configured(self) -> bool:
        return bool(self._base)

    def detect(self, jpeg: bytes, object_id: str) -> Verdict:
        if not self.configured:
            return Verdict("error")
        try:
            response = self._session.post(
                self._url,
                files={"image": ("capture.jpg", jpeg, "image/jpeg")},
                data={"object_id": object_id},
                timeout=self._timeout_s,
            )
        except requests.RequestException as error:
            LOG.warning("vision server unreachable: %s", error)
            return Verdict("error")
        try:
            body = response.json()
        except ValueError:
            body = None
        verdict = parse_verdict(response.status_code, body)
        LOG.info("vision %s: %s", object_id, verdict)
        return verdict
