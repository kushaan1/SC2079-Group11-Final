"""Environment-backed configuration for both vision deployments."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional


MODULE_ROOT = Path(__file__).resolve().parents[1]


def _value(env: Mapping[str, str], key: str, default: str) -> str:
    value = env.get(key, default).strip()
    if not value:
        raise ValueError("{} cannot be empty".format(key))
    return value


def _integer(env: Mapping[str, str], key: str, default: int) -> int:
    return int(_value(env, key, str(default)))


def _float(env: Mapping[str, str], key: str, default: float) -> float:
    return float(_value(env, key, str(default)))


@dataclass(frozen=True)
class PCConfig:
    model_path: Path
    capture_dir: Path
    host: str
    port: int
    confidence_threshold: float
    iou_threshold: float
    max_upload_bytes: int
    save_workers: int

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "PCConfig":
        source = os.environ if env is None else env
        config = cls(
            model_path=Path(
                _value(source, "VISION_PC_MODEL_PATH", str(MODULE_ROOT / "pc_server/models/best.pt"))
            ),
            capture_dir=Path(
                _value(source, "VISION_CAPTURE_DIR", str(MODULE_ROOT / "captures"))
            ),
            host=_value(source, "VISION_PC_HOST", "0.0.0.0"),
            port=_integer(source, "VISION_PC_PORT", 4000),
            confidence_threshold=_float(source, "VISION_PC_CONFIDENCE", 0.60),
            iou_threshold=_float(source, "VISION_PC_IOU", 0.45),
            max_upload_bytes=_integer(source, "VISION_MAX_UPLOAD_BYTES", 8 * 1024 * 1024),
            save_workers=_integer(source, "VISION_SAVE_WORKERS", 2),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not 1 <= self.port <= 65535:
            raise ValueError("VISION_PC_PORT must be between 1 and 65535")
        if not 0.0 <= self.confidence_threshold <= 1.0:
            raise ValueError("VISION_PC_CONFIDENCE must be between 0 and 1")
        if not 0.0 <= self.iou_threshold <= 1.0:
            raise ValueError("VISION_PC_IOU must be between 0 and 1")
        if self.max_upload_bytes <= 0 or self.save_workers <= 0:
            raise ValueError("upload size and save worker count must be positive")


@dataclass(frozen=True)
class RPiConfig:
    pc_detect_url: str
    request_timeout_seconds: float
    camera_width: int
    camera_height: int
    camera_framerate: int
    camera_rotation: int
    tflite_model_path: Path
    tflite_labels_path: Path
    tflite_confidence_threshold: float
    tflite_iou_threshold: float
    serial_port: str
    serial_baud: int
    serial_timeout_seconds: float
    bluetooth_channel: int
    consensus_required: int
    consensus_window: int

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "RPiConfig":
        source = os.environ if env is None else env
        config = cls(
            pc_detect_url=_value(source, "VISION_PC_DETECT_URL", "http://127.0.0.1:4000/detect"),
            request_timeout_seconds=_float(source, "VISION_HTTP_TIMEOUT_SECONDS", 10.0),
            camera_width=_integer(source, "VISION_CAMERA_WIDTH", 640),
            camera_height=_integer(source, "VISION_CAMERA_HEIGHT", 480),
            camera_framerate=_integer(source, "VISION_CAMERA_FRAMERATE", 20),
            camera_rotation=_integer(source, "VISION_CAMERA_ROTATION", 0),
            tflite_model_path=Path(
                _value(
                    source,
                    "VISION_TFLITE_MODEL_PATH",
                    str(MODULE_ROOT / "rpi/models/best_arrows.tflite"),
                )
            ),
            tflite_labels_path=Path(
                _value(
                    source,
                    "VISION_TFLITE_LABELS_PATH",
                    str(MODULE_ROOT / "rpi/models/arrow-labels.json"),
                )
            ),
            tflite_confidence_threshold=_float(source, "VISION_TFLITE_CONFIDENCE", 0.75),
            tflite_iou_threshold=_float(source, "VISION_TFLITE_IOU", 0.45),
            serial_port=_value(source, "VISION_SERIAL_PORT", "/dev/ttyUSB0"),
            serial_baud=_integer(source, "VISION_SERIAL_BAUD", 115200),
            serial_timeout_seconds=_float(source, "VISION_SERIAL_TIMEOUT_SECONDS", 2.0),
            bluetooth_channel=_integer(source, "VISION_BLUETOOTH_CHANNEL", 1),
            consensus_required=_integer(source, "VISION_CONSENSUS_REQUIRED", 3),
            consensus_window=_integer(source, "VISION_CONSENSUS_WINDOW", 5),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if min(self.camera_width, self.camera_height, self.camera_framerate) <= 0:
            raise ValueError("camera dimensions and frame rate must be positive")
        if self.camera_rotation not in (0, 90, 180, 270):
            raise ValueError("VISION_CAMERA_ROTATION must be 0, 90, 180, or 270")
        if not 0.0 <= self.tflite_confidence_threshold <= 1.0:
            raise ValueError("VISION_TFLITE_CONFIDENCE must be between 0 and 1")
        if not 0.0 <= self.tflite_iou_threshold <= 1.0:
            raise ValueError("VISION_TFLITE_IOU must be between 0 and 1")
        if not 1 <= self.bluetooth_channel <= 30:
            raise ValueError("VISION_BLUETOOTH_CHANNEL must be between 1 and 30")
        if not 1 <= self.consensus_required <= self.consensus_window:
            raise ValueError("consensus requires 1 <= required <= window")
