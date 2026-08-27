"""Capture one Task 1 image, call the PC detector, and relay its status."""

import argparse
import json
from typing import Any, Optional

from rpi.camera import BusterCameraStream
from rpi.comms.android_bt import BluetoothStatusServer
from rpi.comms.pc_client import PCDetectionClient
from rpi.comms.stm_serial import SerialJsonTransport
from vision.config import RPiConfig


def run_once(
    object_id: str,
    config: RPiConfig,
    camera: Any,
    pc_client: Any,
    stm: Optional[Any] = None,
    android: Optional[Any] = None,
) -> Any:
    _, frame = camera.read(timeout=3.0)
    result = pc_client.detect_frame(frame, object_id)
    if stm is not None:
        stm.send_and_wait("capture_ready", message_id="capture-{}".format(object_id))
    if android is not None:
        android.send("detection", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("object_id", help="arena obstacle identifier")
    parser.add_argument("--serial", action="store_true", help="notify the STM32 after capture")
    parser.add_argument("--android", action="store_true", help="wait for and notify Android")
    args = parser.parse_args()
    config = RPiConfig.from_env()
    camera = BusterCameraStream(
        config.camera_width,
        config.camera_height,
        config.camera_framerate,
        config.camera_rotation,
    )
    pc_client = PCDetectionClient(config.pc_detect_url, config.request_timeout_seconds)
    stm = (
        SerialJsonTransport(
            config.serial_port,
            config.serial_baud,
            config.serial_timeout_seconds,
        )
        if args.serial
        else None
    )
    android = BluetoothStatusServer(config.bluetooth_channel) if args.android else None
    try:
        if android is not None:
            android.accept()
        with camera:
            result = run_once(args.object_id, config, camera, pc_client, stm, android)
        print(json.dumps(result, indent=2, sort_keys=True))
    finally:
        if stm is not None:
            stm.close()
        if android is not None:
            android.close()


if __name__ == "__main__":
    main()
