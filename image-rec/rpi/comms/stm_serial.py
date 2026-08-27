"""Newline-delimited JSON transceiver for the STM32 serial link."""

import json
import time
from typing import Any, Dict, Optional
from uuid import uuid4


PROTOCOL_VERSION = "1.0"
MAX_LINE_BYTES = 4096
VALID_ACTIONS = frozenset(
    (
        "stop",
        "move",
        "turn_left",
        "turn_right",
        "capture_ready",
        "execute_left_route",
        "execute_right_route",
    )
)


class SerialJsonTransport:
    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        timeout_seconds: float = 2.0,
        connection: Optional[Any] = None,
    ) -> None:
        if connection is None:
            import serial

            connection = serial.Serial(port, baudrate=baudrate, timeout=timeout_seconds)
        self._connection = connection
        self.timeout_seconds = timeout_seconds

    def send_command(self, action: str, **parameters: Any) -> str:
        if action not in VALID_ACTIONS:
            raise ValueError("unsupported STM action: {}".format(action))
        message_id = str(parameters.pop("message_id", uuid4().hex))
        message = {
            "version": PROTOCOL_VERSION,
            "message_id": message_id,
            "action": action,
        }
        message.update(parameters)
        self._write(message)
        return message_id

    def send_and_wait(self, action: str, **parameters: Any) -> Dict[str, Any]:
        message_id = self.send_command(action, **parameters)
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            response = self.read_message()
            if response.get("type") == "ack" and response.get("message_id") == message_id:
                return response
        raise TimeoutError("STM acknowledgement timed out for {}".format(message_id))

    def _write(self, message: Dict[str, Any]) -> None:
        encoded = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
        if len(encoded) > MAX_LINE_BYTES:
            raise ValueError("serial message exceeds {} bytes".format(MAX_LINE_BYTES))
        self._connection.write(encoded)
        if hasattr(self._connection, "flush"):
            self._connection.flush()

    def read_message(self) -> Dict[str, Any]:
        encoded = self._connection.read_until(b"\n", MAX_LINE_BYTES + 1)
        if not encoded:
            raise TimeoutError("timed out waiting for an STM message")
        if len(encoded) > MAX_LINE_BYTES or not encoded.endswith(b"\n"):
            raise ValueError("invalid or oversized serial frame")
        try:
            message = json.loads(encoded.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise ValueError("invalid JSON serial frame") from error
        if not isinstance(message, dict) or message.get("version") != PROTOCOL_VERSION:
            raise ValueError("unsupported serial message version")
        return message

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "SerialJsonTransport":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()
