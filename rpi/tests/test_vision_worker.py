import threading
import time

from rpi.model import Verdict
from rpi.vision_worker import Result, VisionWorker, decide


class ScriptedClient:
    """Returns verdicts in order; blocks on a gate if given one."""

    def __init__(self, verdicts, configured=True, gate=None):
        self._verdicts = list(verdicts)
        self.configured = configured
        self.gate = gate
        self.calls = []

    def detect(self, jpeg, object_id):
        if self.gate is not None:
            self.gate.wait(5.0)
        self.calls.append(object_id)
        return self._verdicts.pop(0)


# --- decide ---------------------------------------------------------------------

def test_best_target_by_confidence_wins():
    result = decide(3, [Verdict("target", 11, 0.4), Verdict("no_detection"), Verdict("target", 16, 0.9)])
    assert result == Result(3, "target", 16, 0.9)


def test_bullseye_beats_nothing():
    assert decide(2, [Verdict("no_detection"), Verdict("bullseye", None, 0.7)]).status == "bullseye"


def test_nothing_beats_error():
    assert decide(2, [Verdict("error"), Verdict("no_detection")]).status == "no_detection"


def test_all_errors_is_error():
    assert decide(2, [Verdict("error"), Verdict("error")]).status == "error"


# --- worker ----------------------------------------------------------------------

def run_worker(client, submissions):
    sent = []
    worker = VisionWorker(client, sent.append)
    worker.start()
    try:
        for obstacle_id, frames, quiet in submissions:
            worker.submit(obstacle_id, frames, quiet=quiet)
        assert worker.wait_all(2.0) is True
    finally:
        worker.close()
    return worker, sent


def test_target_sends_one_target_line():
    client = ScriptedClient([Verdict("no_detection"), Verdict("target", 38, 0.8), Verdict("target", 38, 0.6)])
    worker, sent = run_worker(client, [(3, [b"1", b"2", b"3"], False)])
    assert client.calls == ["B3", "B3", "B3"]
    assert sent == ["TARGET,B3,38"]
    assert worker.results() == [Result(3, "target", 38, 0.8)]


def test_miss_sends_one_message_per_obstacle():
    client = ScriptedClient([Verdict("bullseye"), Verdict("bullseye"), Verdict("no_detection"),
                             Verdict("error"), Verdict("error")])
    _, sent = run_worker(client, [(1, [b"a", b"b", b"c"], False), (2, [b"d", b"e"], False)])
    assert sent == ["MSG,B1: bullseye - wrong face?", "MSG,B2: recogniser unreachable"]


def test_quiet_submission_only_ever_sends_targets():
    client = ScriptedClient([Verdict("bullseye"), Verdict("target", 12, 0.5)])
    _, sent = run_worker(client, [(1, [b"a"], True), (2, [b"b"], True)])
    assert sent == ["TARGET,B2,12"]


def test_wait_returns_the_result_for_that_obstacle():
    gate = threading.Event()
    client = ScriptedClient([Verdict("target", 20, 0.9)], gate=gate)
    worker = VisionWorker(client, lambda line: None)
    worker.start()
    try:
        worker.submit(5, [b"x"])
        assert worker.wait(5, 0.1) is None          # not yet
        gate.set()
        assert worker.wait(5, 2.0) == Result(5, "target", 20, 0.9)
        assert worker.wait(6, 0.05) is None          # never submitted
    finally:
        worker.close()


def test_resubmitting_an_obstacle_replaces_its_result():
    client = ScriptedClient([Verdict("no_detection"), Verdict("target", 25, 0.7)])
    worker, _ = run_worker(client, [(4, [b"a"], True), (4, [b"b"], True)])
    assert worker.results() == [Result(4, "target", 25, 0.7)]


def test_unconfigured_client_is_reported_once_and_frames_dropped():
    client = ScriptedClient([], configured=False)
    sent = []
    worker = VisionWorker(client, sent.append)
    worker.start()
    try:
        assert worker.submit(1, [b"a"]) is False
        assert worker.submit(2, [b"b"]) is False
        assert worker.wait_all(0.5) is True
    finally:
        worker.close()
    assert sent == ["MSG,Vision URL not configured"]
    assert client.calls == []
