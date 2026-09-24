import threading

from rpi.dispatcher import Dispatcher
from rpi.run import BaseRun, RunController
from rpi.stm_driver import FakeStmDriver, StmError, StmUnavailable


class BlockingRun(BaseRun):
    def __init__(self):
        super().__init__()
        self.started = threading.Event()

    def run(self):
        self.started.set()
        self.abort.wait(5.0)


class BrokenStm(FakeStmDriver):
    def __init__(self, error):
        super().__init__()
        self._error = error

    def manual(self, token):
        raise self._error


def make(stm=None, task1_factory=None, face_search_factory=None, fastest_factory=None):
    sent = []
    stm = stm or FakeStmDriver()
    controller = RunController(stm, sent.append)
    dispatcher = Dispatcher(sent.append, stm, controller, task1_factory, face_search_factory, fastest_factory)
    return dispatcher, sent, stm, controller


def test_manual_tokens_go_to_the_stm():
    dispatcher, sent, stm, _ = make()
    for line in ("f", "b", "tl", "sr", "s"):
        dispatcher.handle(line)
    assert stm.sent == ["F", "B", "TL 45", "BR 45", "S"]
    assert sent == []


def test_arena_messages_are_logged_only():
    dispatcher, sent, stm, _ = make()
    for line in ("ADD,B1,(5,5)", "SUB,B1", "FACE,B2,(3,4),N", "MOVEROBOT,1.0,1.0,0.0",
                 '{"obstacles":[]}'):
        dispatcher.handle(line)
    assert stm.sent == []
    assert sent == []


def test_unknown_line_is_reported():
    dispatcher, sent, _, _ = make()
    dispatcher.handle("dance\r")
    assert sent == ["MSG,Unknown command: dance"]


def test_begin_fastest_passes_through():
    dispatcher, sent, stm, _ = make()
    dispatcher.handle("beginFastest")
    assert stm.sent == ["beginFastest"]


def test_stm_errors_become_messages():
    dispatcher, sent, _, _ = make(stm=BrokenStm(StmUnavailable("F", "STM unavailable")))
    dispatcher.handle("f")
    assert sent == ["MSG,STM unavailable"]

    dispatcher, sent, _, _ = make(stm=BrokenStm(StmError("F", "ERR,UNKNOWN")))
    dispatcher.handle("f")
    assert sent == ["MSG,STM error: ERR,UNKNOWN"]


def test_run_start_without_a_factory_is_refused_clearly():
    dispatcher, sent, _, _ = make()
    dispatcher.handle('{"command":"imageRec","obstacles":[{"id":1,"x":5,"y":5,"face":"N"}]}')
    assert sent == ["MSG,imageRec not available in this build"]


def test_run_start_uses_the_factory_and_blocks_manual_until_stopped():
    run = BlockingRun()
    dispatcher, sent, stm, controller = make(task1_factory=lambda message: run)
    dispatcher.handle('{"command":"imageRec","obstacles":[{"id":1,"x":5,"y":5,"face":"N"}]}')
    assert run.started.wait(1.0)
    dispatcher.handle("f")
    assert sent == ["MSG,Run in progress - STOP first"]
    assert stm.sent == []
    dispatcher.handle('{"command":"imageRec","obstacles":[{"id":1,"x":5,"y":5,"face":"N"}]}')
    assert sent[-1] == "MSG,Run in progress - STOP first"
    dispatcher.handle("s")
    controller.join(2.0)
    assert stm.sent == ["S"]
    dispatcher.handle("f")
    assert stm.sent == ["S", "F"]


def test_begin_fastest_starts_the_run_when_a_factory_is_wired():
    run = BlockingRun()
    dispatcher, sent, stm, controller = make(fastest_factory=lambda message: run)
    dispatcher.handle("beginFastest")
    assert run.started.wait(1.0)
    assert stm.sent == []                       # not passed through to the STM
    dispatcher.handle("f")
    assert sent == ["MSG,Run in progress - STOP first"]
    dispatcher.handle("s")
    controller.join(2.0)
    assert stm.sent == ["S"]
