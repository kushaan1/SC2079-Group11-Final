"""Flask entry point for Task 1 host-PC inference."""

import logging
from dataclasses import replace
from typing import Any, Optional

from vision.config import PCConfig
from vision.contracts import SCHEMA_VERSION, DetectionResult, status_for_detections

from .detector import InvalidImageError, UltralyticsDetector
from .storage import AsyncImageStore


LOGGER = logging.getLogger(__name__)


def create_app(
    config: Optional[PCConfig] = None,
    detector: Any = None,
    image_store: Any = None,
) -> Any:
    """Build the Flask app; dependencies may be injected for standalone tests."""

    from flask import Flask, jsonify, request

    resolved = config or PCConfig.from_env()
    detector = detector or UltralyticsDetector(
        resolved.model_path,
        resolved.confidence_threshold,
        resolved.iou_threshold,
        nearest_height_tolerance=resolved.nearest_height_tolerance,
    )
    image_store = image_store or AsyncImageStore(resolved.capture_dir, resolved.save_workers)

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = resolved.max_upload_bytes

    @app.get("/health")
    def health() -> Any:
        return jsonify({"status": "ok", "schema_version": SCHEMA_VERSION})

    @app.post("/detect")
    def detect() -> Any:
        image_upload = request.files.get("image")
        object_id = request.form.get("object_id", "").strip()
        if image_upload is None:
            return _error(jsonify, "multipart field 'image' is required", 400)
        if not object_id:
            return _error(jsonify, "multipart field 'object_id' is required", 400)
        if len(object_id) > 64 or any(ord(character) < 32 for character in object_id):
            return _error(jsonify, "object_id must be 1-64 printable characters", 400)

        image_bytes = image_upload.read()
        if not image_bytes:
            return _error(jsonify, "uploaded image is empty", 400)

        try:
            image, detections = detector.detect(image_bytes)
            result = DetectionResult(
                object_id=object_id,
                status=status_for_detections(detections),
                detections=tuple(detections),
            )
            raw_path, annotated_path = image_store.schedule(image, result)
            result = replace(result, raw_image=raw_path, annotated_image=annotated_path)
            return jsonify(result.to_dict())
        except InvalidImageError as error:
            return _error(jsonify, str(error), 400)
        except Exception:
            LOGGER.exception("Task 1 inference failed for object_id=%s", object_id)
            return _error(jsonify, "inference failed", 500)

    return app


def _error(jsonify: Any, message: str, status_code: int) -> Any:
    return jsonify({"schema_version": SCHEMA_VERSION, "error": message}), status_code


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = PCConfig.from_env()
    app = create_app(config=config)
    app.run(host=config.host, port=config.port, threaded=True)


if __name__ == "__main__":
    main()
