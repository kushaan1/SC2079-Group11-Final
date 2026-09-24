import pytest

from rpi.arrow import FakeArrowSource, HttpArrowSource, TfliteArrowSource
from rpi.bt_link import BluetoothLink
from rpi.dispatcher import Dispatcher
from rpi.main import build, parse_args
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


# --- Task 2 wiring (Task 2 spec §4, §8) --------------------------------------------------

def test_build_wires_the_tflite_arrow_source_by_default():
    wiring = build(fake_stm=True, fake_camera=True)
    assert isinstance(wiring.arrow_source, TfliteArrowSource)
    assert wiring.arrow_source.configured is False        # no model on the laptop


def test_build_with_fake_arrows_installs_the_scripted_source():
    wiring = build(fake_stm=True, fake_camera=True, fake_arrows=["left", "right"])
    assert isinstance(wiring.arrow_source, FakeArrowSource)
    assert wiring.arrow_source.describe == "fake left,right"


def test_build_picks_the_http_source_from_config(monkeypatch):
    monkeypatch.setenv("RPI_ARROW_SOURCE", "http")
    import importlib
    from rpi import config
    importlib.reload(config)
    wiring = build(fake_stm=True, fake_camera=True)
    assert isinstance(wiring.arrow_source, HttpArrowSource)


def test_parse_args_fake_arrows():
    assert parse_args([]).fake_arrows is None
    assert parse_args(["--fake-arrows", "LEFT, right"]).fake_arrows == ["left", "right"]
    with pytest.raises(SystemExit):
        parse_args(["--fake-arrows", "left,up"])


def test_begin_fastest_over_the_wired_program_without_a_model():
    # Default source is tflite; no model file exists on the laptop, so it's unconfigured.
    wiring = build(fake_stm=True, fake_camera=True)
    read_fd, write_fd = os.pipe()
    wiring.link._attach(write_fd)
    try:
        wiring.dispatcher.handle("beginFastest")
        wiring.controller.join(3.0)
        wiring.link.send("END")
        lines = _read_until_end(read_fd)
    finally:
        wiring.link.close()
        wiring.vision.close()
        os.close(read_fd)
    assert lines[0].startswith("MSG,Fastest: arrow source tflite ")
    assert lines[1] == "MSG,Arrow source not configured"
    assert wiring.stm.sent == []                 # no longer passed through to the STM


def test_begin_fastest_over_the_wired_program_without_a_vision_url(monkeypatch):
    monkeypatch.setenv("RPI_VISION_URL", "")
    monkeypatch.setenv("RPI_ARROW_SOURCE", "http")
    import importlib
    from rpi import config
    importlib.reload(config)
    wiring = build(fake_stm=True, fake_camera=True)
    read_fd, write_fd = os.pipe()
    wiring.link._attach(write_fd)
    try:
        wiring.dispatcher.handle("beginFastest")
        wiring.controller.join(3.0)
        wiring.link.send("END")
        lines = _read_until_end(read_fd)
    finally:
        wiring.link.close()
        wiring.vision.close()
        os.close(read_fd)
    assert lines == ["MSG,Fastest: arrow source http (no URL)", "MSG,Arrow source not configured"]
    assert wiring.stm.sent == []                 # no longer passed through to the STM


def test_begin_fastest_over_the_wired_program_with_fake_arrows(monkeypatch):
    monkeypatch.setenv("RPI_CAPTURE_SETTLE_S", "0")
    monkeypatch.setenv("RPI_ARROW_ATTEMPT_S", "0.2")
    monkeypatch.setenv("RPI_ARROW_BUDGET_S", "1")
    import importlib
    from rpi import config
    importlib.reload(config)
    wiring = build(fake_stm=True, fake_camera=True, fake_arrows=["left", "right"])
    wiring.camera.start()
    read_fd, write_fd = os.pipe()
    wiring.link._attach(write_fd)
    try:
        wiring.dispatcher.handle("beginFastest")
        wiring.controller.join(5.0)
        wiring.link.send("END")
        lines = _read_until_end(read_fd)
    finally:
        wiring.link.close()
        wiring.vision.close()
        wiring.camera.close()
        os.close(read_fd)
    assert lines[:-1] == [
        "MSG,Fastest: arrow source fake left,right",
        "MSG,Seeking obstacle 1",
        "MSG,Obstacle 1 reached",                  # the fake STM has no scripted distance...
        "MSG,Warning: no sensor reading",          # ...and no scripted sensor
        "MSG,Reading arrow 1",
        "MSG,Arrow 1: LEFT",
        "MSG,Seeking obstacle 2",
        "MSG,Obstacle 2 reached",
        "MSG,Warning: no sensor reading",
        "MSG,Reading arrow 2",
        "MSG,Arrow 2: RIGHT",
        "MSG,Returning",
    ]
    assert lines[-1].startswith("MSG,Parked in ")
    assert wiring.stm.calls == [
        ("seek", 30), ("range",), ("round", 1, "L"),
        ("seek", 30), ("range",), ("round", 2, "R"),
        ("home",),
    ]


def test_every_fake_arrows_run_starts_from_the_top_of_the_script(monkeypatch):
    # A run stopped mid-read leaves the shared script part-consumed; the next run must not
    # inherit that (it would read the sides swapped). So the factory builds a fresh script.
    monkeypatch.setenv("RPI_CAPTURE_SETTLE_S", "0")
    monkeypatch.setenv("RPI_ARROW_ATTEMPT_S", "0.2")
    monkeypatch.setenv("RPI_ARROW_BUDGET_S", "1")
    import importlib
    from rpi import config
    importlib.reload(config)
    wiring = build(fake_stm=True, fake_camera=True, fake_arrows=["left", "right"])
    wiring.camera.start()
    wiring.arrow_source.sightings(b"")            # one frame consumed, as an interrupted read would
    read_fd, write_fd = os.pipe()
    wiring.link._attach(write_fd)
    try:
        wiring.dispatcher.handle("beginFastest")
        wiring.controller.join(5.0)
        wiring.link.send("END")
        lines = _read_until_end(read_fd)
    finally:
        wiring.link.close()
        wiring.vision.close()
        wiring.camera.close()
        os.close(read_fd)
    assert lines[5] == "MSG,Arrow 1: LEFT"
    assert lines[10] == "MSG,Arrow 2: RIGHT"
