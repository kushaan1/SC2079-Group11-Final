"""Make a confidence-gated Task 2 arrow decision using local TFLite inference."""

import argparse
import json
import time
from typing import Any, Optional

from rpi.camera import BusterCameraStream
from rpi.comms.android_bt import BluetoothStatusServer
from rpi.comms.stm_serial import SerialJsonTransport
from rpi.inference import ArrowConsensus, TFLiteYoloDetector
from vision.config import RPiConfig


def wait_for_arrow(
    camera: Any,
    detector: Any,
    consensus: ArrowConsensus,
    timeout_seconds: float,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    sequence = 0
    while time.monotonic() < deadline:
        sequence, frame = camera.read(timeout=2.0, after_sequence=sequence)
        direction = consensus.observe(detector.detect(frame))
        if direction is not None:
            return direction
    raise TimeoutError("no stable arrow decision before timeout; re-approach and recapture")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision-timeout", type=float, default=10.0)
    parser.add_argument("--serial", action="store_true", help="send the calibrated route command")
    parser.add_argument("--android", action="store_true", help="wait for and notify Android")
    args = parser.parse_args()
    config = RPiConfig.from_env()
    camera = BusterCameraStream(
        config.camera_width,
        config.camera_height,
        config.camera_framerate,
        config.camera_rotation,
    )
    detector = TFLiteYoloDetector(
        config.tflite_model_path,
        config.tflite_labels_path,
        config.tflite_confidence_threshold,
        config.tflite_iou_threshold,
    )
    consensus = ArrowConsensus(
        config.consensus_required,
        config.consensus_window,
        config.tflite_confidence_threshold,
    )
    stm: Optional[Any] = (
        SerialJsonTransport(
            config.serial_port,
            config.serial_baud,
            config.serial_timeout_seconds,
        )
        if args.serial
        else None
    )
    android: Optional[Any] = (
        BluetoothStatusServer(config.bluetooth_channel) if args.android else None
    )
    try:
        if android is not None:
            android.accept()
        with camera:
            direction = wait_for_arrow(camera, detector, consensus, args.decision_timeout)
        payload = {"status": "target", "direction": direction, "competition_id": 39 if direction == "left" else 38}
        if stm is not None:
            stm.send_and_wait("execute_{}_route".format(direction))
        if android is not None:
            android.send("detection", payload)
        print(json.dumps(payload, sort_keys=True))
    finally:
        if stm is not None:
            stm.close()
        if android is not None:
            android.close()


if __name__ == "__main__":
    main()
