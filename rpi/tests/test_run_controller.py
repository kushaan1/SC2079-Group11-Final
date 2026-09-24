import threading
import time

from rpi.run import BaseRun, RunController
from rpi.stm_driver import FakeStmDriver


class BlockingRun(BaseRun):
    """A run that sits until aborted, then records that it saw the abort."""

    def __init__(self):
        super().__init__()
        self.saw_abort = False
        self.started = threading.Event()

    def run(self):
        self.started.set()
        self.abort.wait(5.0)
        self.saw_abort = self.abort.is_set()


class CrashingRun(BaseRun):
    def run(self):
        raise RuntimeError("boom")


def test_one_run_at_a_time():
    sent = []
    controller = RunController(FakeStmDriver(), sent.append)
    first, second = BlockingRun(), BlockingRun()
    assert controller.start(first) is True
    assert first.started.wait(1.0)
    assert controller.active() is True
    assert controller.start(second) is False
    assert controller.stop() is True
    controller.join(2.0)
    assert first.saw_abort is True
    assert controller.active() is False


def test_stop_without_a_run_reports_false_and_sends_nothing_to_the_stm():
    stm = FakeStmDriver()
    controller = RunController(stm, lambda line: None)
    assert controller.stop() is False
    assert stm.sent == []


def test_stop_sends_s_to_the_stm():
    stm = FakeStmDriver()
    controller = RunController(stm, lambda line: None)
    run = BlockingRun()
    controller.start(run)
    run.started.wait(1.0)
    controller.stop()
    controller.join(2.0)
    assert stm.sent == ["S"]


def test_a_crashing_run_is_reported_and_does_not_kill_the_program():
    sent = []
    controller = RunController(FakeStmDriver(), sent.append)
    controller.start(CrashingRun())
    controller.join(2.0)
    assert controller.active() is False
    assert sent == ["MSG,Run failed: boom"]
