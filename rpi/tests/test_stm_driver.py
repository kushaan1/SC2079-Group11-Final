import threading
import time

import pytest

from rpi.model import Arc, Capture, Straight
from rpi.stm_driver import (
    FakeStmDriver, StmAborted, encode_instruction, encode_manual, is_motion,
)


# --- encoding (spec §5.5) ------------------------------------------------------

@pytest.mark.parametrize("instr,line", [
    (Straight("FORWARD", 30), "FW 30"),
    (Straight("BACKWARD", 10), "BW 10"),
    (Arc("FORWARD_LEFT", 90), "TL 90"),
    (Arc("FORWARD_RIGHT", 90), "TR 90"),
    (Arc("BACKWARD_LEFT", 90), "BL 90"),
    (Arc("BACKWARD_RIGHT", 90), "BR 90"),
    (Arc("FORWARD_LEFT", 45), "TL 45"),
])
def test_encode_instruction(instr, line):
    assert encode_instruction(instr) == line


def test_capture_is_not_an_stm_command():
    with pytest.raises(ValueError):
        encode_instruction(Capture())


@pytest.mark.parametrize("token,line", [
    ("f", "F"), ("b", "B"), ("s", "S"),
    ("tl", "TL 45"), ("tr", "TR 45"), ("sl", "BL 45"), ("sr", "BR 45"),
])
def test_encode_manual(token, line):
    assert encode_manual(token, 45) == line


def test_encode_manual_rejects_unknown_token():
    with pytest.raises(ValueError):
        encode_manual("x", 45)


@pytest.mark.parametrize("line,motion", [
    ("FW 30", True), ("BW 5", True), ("TL 90", True), ("BR 45", True), ("PL 180", True),
    ("F", False), ("B", False), ("S", False), ("PING", False), ("MA 50", False),
])
def test_is_motion(line, motion):
    assert is_motion(line) is motion


# --- fake driver ------------------------------------------------------------------

def test_fake_records_what_it_would_send():
    stm = FakeStmDriver(straight_cm_per_s=1000.0, turn_s=0.0)
    stm.start()
    stm.manual("f")
    stm.execute(Straight("FORWARD", 20))
    stm.execute(Arc("BACKWARD_RIGHT", 90))
    stm.manual_raw("beginFastest")
    assert stm.sent == ["F", "FW 20", "BR 90", "beginFastest"]


def test_fake_execute_takes_time_proportional_to_distance():
    stm = FakeStmDriver(straight_cm_per_s=100.0)
    started = time.monotonic()
    stm.execute(Straight("FORWARD", 10))
    assert time.monotonic() - started >= 0.09


def test_fake_stop_interrupts_a_running_execute():
    stm = FakeStmDriver(straight_cm_per_s=1.0)   # 60 cm would take a minute
    outcome = []

    def drive():
        try:
            stm.execute(Straight("FORWARD", 60))
            outcome.append("finished")
        except StmAborted:
            outcome.append("aborted")

    thread = threading.Thread(target=drive)
    thread.start()
    time.sleep(0.1)
    stm.stop()
    thread.join(timeout=2.0)
    assert outcome == ["aborted"]
    assert stm.sent[-1] == "S"


def test_fake_execute_refuses_when_the_runs_abort_event_is_already_set():
    stm = FakeStmDriver(straight_cm_per_s=1000.0)
    abort = threading.Event()
    abort.set()
    with pytest.raises(StmAborted):
        stm.execute(Straight("FORWARD", 10), abort=abort)
    assert stm.sent == []


def test_fake_mirrors_the_conversation_it_pretends_to_have():
    mirrored = []
    stm = FakeStmDriver(straight_cm_per_s=1000.0, turn_s=0.0, on_line=mirrored.append)
    stm.manual("f")
    stm.execute(Straight("FORWARD", 20))
    stm.stop()
    assert mirrored == [
        "STM> F", "STM< ACK,F",
        "STM> FW 20", "STM< ACK,FW", "STM< DONE,FW",
        "STM> S", "STM< ACK,S",
    ]


# --- raw(): a line typed by a human ------------------------------------------------------

def test_fake_raw_waits_for_done_on_motion_verbs_and_answers_ping():
    mirrored = []
    stm = FakeStmDriver(straight_cm_per_s=10000.0, turn_s=0.0, on_line=mirrored.append)
    assert stm.raw("FW 50") == "DONE,FW"
    assert stm.raw("PING") == "PONG"
    assert stm.raw("MA 50") == "ACK,MA"
    assert stm.sent == ["FW 50", "PING", "MA 50"]
    assert mirrored == ["STM> FW 50", "STM< ACK,FW", "STM< DONE,FW", "STM> PING", "STM< PONG",
                        "STM> MA 50", "STM< ACK,MA"]


def test_fake_raw_rejects_an_empty_line():
    with pytest.raises(ValueError):
        FakeStmDriver().raw("   ")
