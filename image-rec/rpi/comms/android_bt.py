"""Bluetooth RFCOMM JSON-line status channel for Android."""

import json
import socket
from datetime import datetime, timezone
from typing import Any, Dict, Optional


MAX_FRAME_BYTES = 4096


def make_status_message(message_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if message_type not in ("status", "detection", "error", "ack"):
        raise ValueError("unsupported Android message type")
    timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return {
        "version": "1.0",
        "type": message_type,
        "timestamp": timestamp,
        "payload": payload,
    }


class BluetoothStatusServer:
    def __init__(self, channel: int = 1, server_socket: Optional[Any] = None) -> None:
        if server_socket is None:
            try:
                server_socket = socket.socket(
                    socket.AF_BLUETOOTH,
                    socket.SOCK_STREAM,
                    socket.BTPROTO_RFCOMM,
                )
            except AttributeError as error:
                raise RuntimeError("this Python build does not expose Bluetooth RFCOMM") from error
        self._server = server_socket
        self._client: Optional[Any] = None
        self.channel = channel

    def accept(self) -> Any:
        self._server.bind(("", self.channel))
        self._server.listen(1)
        self._client, address = self._server.accept()
        return address

    def send(self, message_type: str, payload: Dict[str, Any]) -> None:
        if self._client is None:
            raise RuntimeError("no Android RFCOMM client is connected")
        message = make_status_message(message_type, payload)
        encoded = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
        if len(encoded) > MAX_FRAME_BYTES:
            raise ValueError("Bluetooth frame exceeds {} bytes".format(MAX_FRAME_BYTES))
        self._client.sendall(encoded)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
        self._server.close()

    def __enter__(self) -> "BluetoothStatusServer":
        self.accept()
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()
