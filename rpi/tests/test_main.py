from rpi.bt_link import BluetoothLink
from rpi.dispatcher import Dispatcher
from rpi.main import build
from rpi.stm_driver import FakeStmDriver


def test_build_with_fakes_needs_no_hardware():
    wiring = build(fake_stm=True, fake_camera=True)
    assert isinstance(wiring.stm, FakeStmDriver)
    assert isinstance(wiring.link, BluetoothLink)
    assert isinstance(wiring.dispatcher, Dispatcher)
    assert wiring.link.connected is False


import os

from rpi.main import replay
from rpi.run import RunState
from rpi.vision_worker import Result


class FakeVision:
    def __init__(self, results):
        self._results = results

    def results(self):
        return self._results


class FakeController:
    def __init__(self, active):
        self._active = active

    def active(self):
        return self._active


def test_replay_resends_targets_then_pose_then_a_message():
    sent = []
    state = RunState()
    state.last_robot_line = "ROBOT,4.00,4.00,90"
    vision = FakeVision([Result(1, "target", 16, 0.9), Result(2, "bullseye", None, 0.5)])
    replay(sent.append, vision, state, FakeController(active=True))
    assert sent == ["TARGET,B1,16", "ROBOT,4.00,4.00,90", "MSG,Reconnected - run in progress"]


def test_replay_with_nothing_to_replay():
    sent = []
    replay(sent.append, FakeVision([]), RunState(), FakeController(active=False))
    assert sent == ["MSG,Reconnected"]


def _read_until_end(fd):
    """Blocking reads until the END sentinel; works on Windows pipes too."""
    data = b""
    while b"END\n" not in data:
        data += os.read(fd, 4096)
    return data.decode().splitlines()[:-1]


def test_image_rec_over_the_wired_program_without_a_planner_url(monkeypatch):
    monkeypatch.setenv("RPI_PLANNER_URL", "")
    import importlib
    from rpi import config
    importlib.reload(config)
    wiring = build(fake_stm=True, fake_camera=True)
    read_fd, write_fd = os.pipe()
    wiring.link._attach(write_fd)
    try:
        wiring.dispatcher.handle('{"command":"imageRec","obstacles":[{"id":1,"x":5,"y":5,"face":"N"}]}')
        wiring.controller.join(3.0)
        wiring.link.send("END")
        lines = _read_until_end(read_fd)
    finally:
        wiring.link.close()
        wiring.vision.close()
        os.close(read_fd)
    assert lines == [
        "MSG,Planning...",
        "MSG,No robot pose in start - assuming start zone",
        "MSG,Planner error: Planner URL not configured",
    ]


def test_face_search_over_the_wired_program_without_a_planner_url(monkeypatch):
    monkeypatch.setenv("RPI_PLANNER_URL", "")
    import importlib
    from rpi import config
    importlib.reload(config)
    wiring = build(fake_stm=True, fake_camera=True)
    read_fd, write_fd = os.pipe()
    wiring.link._attach(write_fd)
    try:
        wiring.dispatcher.handle('{"command":"faceSearch","obstacles":[{"id":1,"x":5,"y":5,"face":"S"}]}')
        wiring.controller.join(3.0)
        wiring.link.send("END")
        lines = _read_until_end(read_fd)
    finally:
        wiring.link.close()
        wiring.vision.close()
        os.close(read_fd)
    assert lines == [
        "MSG,Planning...",
        "MSG,No robot pose in start - assuming start zone",
        "MSG,Planner error: Planner URL not configured",
    ]


def test_stm_traffic_reaches_the_tablets_raw_log():
    wiring = build(fake_stm=True, fake_camera=True)
    read_fd, write_fd = os.pipe()
    wiring.link._attach(write_fd)
    try:
        wiring.dispatcher.handle("f")
        wiring.link.send("END")
        lines = _read_until_end(read_fd)
    finally:
        wiring.link.close()
        wiring.vision.close()
        os.close(read_fd)
    assert lines == ["STM> F", "STM< ACK,F"]


def test_stm_traffic_mirror_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("RPI_STM_TO_TABLET", "0")
    import importlib
    from rpi import config
    importlib.reload(config)
    wiring = build(fake_stm=True, fake_camera=True)
    read_fd, write_fd = os.pipe()
    wiring.link._attach(write_fd)
    try:
        wiring.dispatcher.handle("f")
        wiring.link.send("END")
        lines = _read_until_end(read_fd)
    finally:
        wiring.link.close()
        wiring.vision.close()
        os.close(read_fd)
    assert lines == []
    assert wiring.stm.sent == ["F"]
