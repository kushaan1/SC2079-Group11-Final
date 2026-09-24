import threading
import time

import pytest

from rpi.model import Arc, Capture, Straight
from rpi.stm_driver import (
    RANGE_LINE, FakeStmDriver, StmAborted, encode_home, encode_instruction, encode_manual,
    encode_round, encode_seek, is_motion, parse_range, parse_seek_distance,
)


# --- encoding (spec §5.5) ------------------------------------------------------

@pytest.mark.parametrize("instr,line", [
    (Straight("FORWARD", 30), "FS 30"),
    (Straight("BACKWARD", 10), "BS 10"),
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
    ("FS 30", True), ("BS 5", True), ("FW 30", True), ("BW 5", True), ("TL 90", True), ("BR 45", True), ("PL 180", True),
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
    assert stm.sent == ["F", "FS 20", "BR 90", "beginFastest"]


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
        "STM> FS 20", "STM< ACK,FS", "STM< DONE,FS",
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


# --- Task 2 encodings (Task 2 spec §3.1, §5.2): the handover §5.3 proposal ----------------

@pytest.mark.parametrize("line,expected", [
    (encode_seek(30), "SEEK 30"),
    (encode_round(1, "L"), "ROUND 1 L"),
    (encode_round(2, "R"), "ROUND 2 R"),
    (encode_home(), "HOME"),
    (RANGE_LINE, "RANGE"),
])
def test_task2_encodings(line, expected):
    assert line == expected


@pytest.mark.parametrize("obstacle,side", [(3, "L"), (1, "X")])
def test_encode_round_rejects_bad_arguments(obstacle, side):
    with pytest.raises(ValueError):
        encode_round(obstacle, side)


@pytest.mark.parametrize("line,motion", [
    ("SEEK 30", True), ("ROUND 2 R", True), ("HOME", True), ("RANGE", False),
])
def test_task2_verbs_and_is_motion(line, motion):
    assert is_motion(line) is motion


@pytest.mark.parametrize("reply,distance", [
    ("DONE,SEEK,87", 87), ("DONE,SEEK,0", 0), ("DONE,SEEK,87.0", 87),
    ("DONE,SEEK,abc", None), ("DONE,SEEK", None), ("ACK,SEEK", None),
])
def test_parse_seek_distance(reply, distance):
    assert parse_seek_distance(reply) == distance


@pytest.mark.parametrize("reply,reading", [("RANGE,52", 52), ("RANGE,x", None), ("ENC,A,1", None)])
def test_parse_range(reply, reading):
    assert parse_range(reply) == reading


def test_fake_labels_its_task2_aborts_with_the_wire_line():
    stm = FakeStmDriver(straight_cm_per_s=10000.0)
    abort = threading.Event()
    abort.set()
    with pytest.raises(StmAborted) as info:
        stm.seek(30, abort=abort)
    assert info.value.command == "SEEK 30"


# --- Task 2 calls on the fake (Task 2 spec §5.2) ----------------------------------------

def test_fake_records_task2_calls_in_order_and_returns_the_scripts():
    stm = FakeStmDriver(straight_cm_per_s=10000.0, seek_distances=[87, 0], range_readings=[31, 29])
    assert stm.seek(30) == 87
    assert stm.range_cm() == 31
    stm.round(1, "L")
    assert stm.seek(30) == 0
    assert stm.range_cm() == 29
    stm.round(2, "R")
    stm.home()
    assert stm.calls == [
        ("seek", 30), ("range",), ("round", 1, "L"),
        ("seek", 30), ("range",), ("round", 2, "R"),
        ("home",),
    ]
    assert stm.sent == []          # no wire form yet: the fake records calls, not sent lines


def test_fake_seek_and_range_return_none_once_their_scripts_run_out():
    stm = FakeStmDriver(straight_cm_per_s=10000.0, seek_distances=[None], range_readings=[])
    assert stm.seek(30) is None
    assert stm.seek(30) is None
    assert stm.range_cm() is None


@pytest.mark.parametrize("obstacle,side", [(3, "L"), (1, "X")])
def test_fake_round_rejects_bad_arguments(obstacle, side):
    with pytest.raises(ValueError):
        FakeStmDriver().round(obstacle, side)


def test_fake_task2_calls_refuse_when_the_runs_abort_is_set():
    stm = FakeStmDriver(straight_cm_per_s=10000.0)
    abort = threading.Event()
    abort.set()
    for call in (lambda: stm.seek(30, abort=abort), lambda: stm.round(1, "L", abort=abort),
                 lambda: stm.home(abort=abort), lambda: stm.range_cm(abort=abort)):
        with pytest.raises(StmAborted):
            call()
    assert stm.calls == []


def wait_until(predicate, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_fake_stop_interrupts_a_manoeuvre():
    stm = FakeStmDriver(manoeuvre_s=60.0)
    outcome = []

    def drive():
        try:
            stm.round(1, "L")
            outcome.append("finished")
        except StmAborted:
            outcome.append("aborted")

    thread = threading.Thread(target=drive, daemon=True)
    thread.start()
    assert wait_until(lambda: stm.calls)        # the call is recorded only after the fake armed itself
    stm.stop()
    thread.join(timeout=2.0)
    assert outcome == ["aborted"]
    assert stm.sent == ["S"]
    assert stm.calls == [("round", 1, "L")]


def test_fake_seek_takes_time_proportional_to_the_scripted_distance():
    stm = FakeStmDriver(straight_cm_per_s=100.0, seek_distances=[10])
    started = time.monotonic()
    assert stm.seek(30) == 10
    assert time.monotonic() - started >= 0.09
