import json

import pytest

from rpi.comms.stm_serial import SerialJsonTransport


class FakeSerial:
    def __init__(self, lines=None):
        self.lines = list(lines or [])
        self.written = []
        self.closed = False

    def write(self, value):
        self.written.append(value)

    def flush(self):
        pass

    def read_until(self, delimiter, size):
        return self.lines.pop(0) if self.lines else b""

    def close(self):
        self.closed = True


def test_writes_versioned_json_line():
    connection = FakeSerial()
    transport = SerialJsonTransport("unused", connection=connection)
    message_id = transport.send_command("execute_left_route", message_id="route-1")
    assert message_id == "route-1"
    assert connection.written[0].endswith(b"\n")
    assert json.loads(connection.written[0]) == {
        "version": "1.0",
        "message_id": "route-1",
        "action": "execute_left_route",
    }


def test_rejects_bad_action_and_bad_input_version():
    transport = SerialJsonTransport(
        "unused",
        connection=FakeSerial([b'{"version":"2.0"}\n']),
    )
    with pytest.raises(ValueError, match="unsupported STM action"):
        transport.send_command("guess")
    with pytest.raises(ValueError, match="version"):
        transport.read_message()
