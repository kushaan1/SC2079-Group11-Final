import queue
import threading
import time

import pytest

from rpi.model import Arc, Straight
from rpi.stm_driver import SerialStmDriver, StmAborted, StmError, StmUnavailable


class FakeSerial:
    """In-memory stand-in for serial.Serial. `responder(line) -> list of reply lines`."""

    def __init__(self, responder=None):
        self.written = []
        self.responder = responder
        self.closed = False
        self.fail_reads = False
        self._incoming = queue.Queue()

    def write(self, data):
        line = data.decode("ascii").strip()
        self.written.append(line)
        if self.responder is not None:
            for reply in self.responder(line):
                self.push(reply)

    def flush(self):
        pass

    def readline(self):
        if self.fail_reads:
            raise OSError("device gone")
        try:
            return self._incoming.get(timeout=0.02)
        except queue.Empty:
            return b""

    def push(self, line):
        self._incoming.put((line + "\r\n").encode("ascii"))

    def reset_input_buffer(self):
        pass

    def close(self):
        self.closed = True


def echo_ack(line):
    """The handover doc's STM: PONG for PING, ACK,<verb> for everything else."""
    if line == "PING":
        return ["PONG"]
    return ["ACK," + line.split(" ")[0]]


def make(responder=echo_ack, **kwargs):
    fake = FakeSerial(responder)
    settings = dict(
        completion="ACK", ack_deadline_s=0.3, turn_deadline_s=0.5,
        straight_deadline=lambda cm: 0.5, ping_deadline_s=0.3, stop_drain_s=0.05,
        retry_delay_s=0.05,
    )
    settings.update(kwargs)
    driver = SerialStmDriver("/dev/fake", 115200, open_serial=lambda: fake, **settings)
    return driver, fake


def wait_until(predicate, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# --- startup ------------------------------------------------------------------------

def test_start_pings_and_pushes_configured_trims():
    driver, fake = make(motor_a=55, motor_b=48, steer_steps=None)
    driver.start()
    try:
        assert fake.written == ["PING", "MA 55", "MB 48"]
        assert driver.available is True
    finally:
        driver.close()


def test_start_without_pong_raises_unavailable():
    driver, fake = make(responder=lambda line: [])
    with pytest.raises(StmUnavailable):
        driver.start()
    driver.close()


# --- execute -------------------------------------------------------------------------

def test_execute_waits_for_the_ack_and_ignores_data_lines():
    def responder(line):
        if line == "PING":
            return ["PONG"]
        if line.startswith("FW"):
            return ["ENC,A,120,B,118", "ACK,FW"]
        return ["ACK," + line.split(" ")[0]]

    driver, fake = make(responder)
    driver.start()
    try:
        driver.execute(Straight("FORWARD", 30))
        driver.execute(Arc("FORWARD_LEFT", 90))
        assert fake.written == ["PING", "FW 30", "TL 90"]
    finally:
        driver.close()


def test_err_reply_raises_with_the_reply_text():
    def responder(line):
        return ["PONG"] if line == "PING" else ["ERR,GYRO"]

    driver, fake = make(responder)
    driver.start()
    try:
        with pytest.raises(StmError) as info:
            driver.execute(Arc("FORWARD_RIGHT", 90))
        assert info.value.command == "TR 90"
        assert info.value.reply == "ERR,GYRO"
    finally:
        driver.close()


def test_no_reply_sends_stop_and_resyncs():
    def responder(line):
        if line == "PING":
            return ["PONG"]
        return []   # every motion command is silently dropped

    driver, fake = make(responder)
    driver.start()
    try:
        with pytest.raises(StmError) as info:
            driver.execute(Straight("BACKWARD", 10))
        assert info.value.reply == "no reply"
        assert fake.written == ["PING", "BW 10", "S", "PING"]
    finally:
        driver.close()


def test_done_completion_model_waits_for_ack_then_done():
    def responder(line):
        if line == "PING":
            return ["PONG"]
        if line.startswith("TL"):
            return ["ACK,TL", "DONE,TL"]
        if line.startswith("BR"):
            return ["ACK,BR", "ERR,TIMEOUT"]
        return ["ACK," + line.split(" ")[0]]

    driver, fake = make(responder, completion="DONE")
    driver.start()
    try:
        driver.execute(Arc("FORWARD_LEFT", 90))
        with pytest.raises(StmError) as info:
            driver.execute(Arc("BACKWARD_RIGHT", 90))
        assert info.value.reply == "ERR,TIMEOUT"
    finally:
        driver.close()


def test_done_model_busy_error_on_receipt_is_an_error():
    def responder(line):
        return ["PONG"] if line == "PING" else ["ERR,BUSY"]

    driver, fake = make(responder, completion="DONE")
    driver.start()
    try:
        with pytest.raises(StmError) as info:
            driver.execute(Straight("FORWARD", 5))
        assert info.value.reply == "ERR,BUSY"
    finally:
        driver.close()


# --- manual ----------------------------------------------------------------------------

def test_manual_encodes_and_waits():
    driver, fake = make(manual_turn_deg=45)
    driver.start()
    try:
        driver.manual("f")
        driver.manual("sl")
        driver.manual_raw("beginFastest")
        assert fake.written == ["PING", "F", "BL 45", "beginFastest"]
    finally:
        driver.close()


# --- stop ------------------------------------------------------------------------------

def test_stop_aborts_an_in_flight_execute_then_resyncs():
    def responder(line):
        if line == "PING":
            return ["PONG"]
        if line == "S":
            return ["ACK,S"]
        return []   # FW never completes

    driver, fake = make(responder)
    driver.start()
    outcome = []

    def drive():
        try:
            driver.execute(Straight("FORWARD", 100))
            outcome.append("finished")
        except StmAborted:
            outcome.append("aborted")
        except StmError as error:
            outcome.append(error.reply)

    thread = threading.Thread(target=drive)
    thread.start()
    assert wait_until(lambda: "FW 100" in fake.written)
    driver.stop()
    thread.join(timeout=2.0)
    try:
        assert outcome == ["aborted"]
        assert fake.written == ["PING", "FW 100", "S", "PING"]
    finally:
        driver.close()


def test_stop_with_nothing_in_flight_is_harmless():
    driver, fake = make()
    driver.start()
    try:
        driver.stop()
        driver.execute(Straight("FORWARD", 5))
        assert fake.written == ["PING", "S", "PING", "FW 5"]
    finally:
        driver.close()


# --- serial loss ---------------------------------------------------------------------------

def test_serial_loss_marks_unavailable_reconnects_and_reports_both():
    fakes = []
    changes = []

    def open_serial():
        fake = FakeSerial(echo_ack)
        fakes.append(fake)
        return fake

    driver = SerialStmDriver(
        "/dev/fake", 115200, open_serial=open_serial, completion="ACK",
        ack_deadline_s=0.3, turn_deadline_s=0.5, straight_deadline=lambda cm: 0.5,
        ping_deadline_s=0.3, stop_drain_s=0.05, retry_delay_s=0.05,
        on_link_change=changes.append,
    )
    driver.start()
    try:
        assert changes == [True]
        fakes[0].fail_reads = True
        assert wait_until(lambda: not driver.available)
        with pytest.raises(StmUnavailable):
            driver.manual("f")
        assert wait_until(lambda: changes == [True, False, True])   # the second handshake succeeded
        driver.manual("f")
        assert fakes[-1].written == ["PING", "F"]
    finally:
        driver.close()
    assert changes == [True, False, True]   # close() is not a link loss
