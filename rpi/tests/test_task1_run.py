import threading
import time

import pytest

from rpi.camera import CameraError, FakeCamera
from rpi.model import Arc, Capture, Obstacle, Plan, Pose, Segment, Straight, Verdict
from rpi.planner_client import PlannerError
from rpi.protocol import ImageRec
from rpi.run import RunController, RunState, Task1Run
from rpi.stm_driver import FakeStmDriver, StmError
from rpi.vision_worker import VisionWorker

RADII = {"FORWARD_LEFT": 40, "FORWARD_RIGHT": 40, "BACKWARD_LEFT": 40, "BACKWARD_RIGHT": 40}
OBSTACLES = (Obstacle(1, 10, 6, "N"), Obstacle(2, 14, 15, "E"))
MESSAGE = ImageRec("greedy", Pose(1.0, 1.0, 0.0), OBSTACLES)
PLAN = Plan(
    segments=(
        Segment(1, (Straight("FORWARD", 30), Arc("FORWARD_RIGHT", 90), Capture()), Pose(4.0, 4.0, 90.0), 3.0),
        Segment(2, (Straight("BACKWARD", 10), Arc("FORWARD_LEFT", 90), Straight("FORWARD", 20), Capture()),
                Pose(8.0, 8.0, 0.0), 4.0),
    ),
    unreachable=(),
)


class FakePlanner:
    def __init__(self, plan=PLAN, error=None):
        self._plan = plan
        self._error = error
        self.requests = []

    def plan(self, body):
        self.requests.append(body)
        if self._error is not None:
            raise self._error
        return self._plan


class ScriptedVision:
    """A vision client: verdicts by object_id, released by a gate."""

    def __init__(self, verdicts, gate=None):
        self.configured = True
        self._verdicts = verdicts
        self.gate = gate

    def detect(self, jpeg, object_id):
        if self.gate is not None:
            self.gate.wait(5.0)
        return self._verdicts.get(object_id, Verdict("no_detection"))


class BrokenCamera(FakeCamera):
    def capture_jpeg(self):
        raise CameraError("no data from sensor")


class GyroFailsOnTurns(FakeStmDriver):
    def execute(self, instr, abort=None):
        if isinstance(instr, Arc):
            self.sent.append("TR 90")
            raise StmError("TR 90", "ERR,GYRO")
        super().execute(instr, abort=abort)


def harness(message=MESSAGE, planner=None, stm=None, camera=None, vision_client=None,
            drain_timeout_s=2.0):
    sent = []
    stm = stm or FakeStmDriver(straight_cm_per_s=10000.0, turn_s=0.0)
    camera = camera or FakeCamera()
    camera.start()
    worker = VisionWorker(vision_client or ScriptedVision({}), sent.append)
    worker.start()
    state = RunState()
    run = Task1Run(
        message, planner or FakePlanner(), drain_timeout_s=drain_timeout_s, strategy_fallback="optimal",
        stm=stm, camera=camera, vision=worker, send=sent.append, state=state, radii=RADII,
        settle_s=0.0, frames=3,
    )
    controller = RunController(stm, sent.append)
    return run, controller, sent, stm, worker, state


def wait_for(sent, line, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if line in sent:
            return True
        time.sleep(0.01)
    return False


def test_full_run_line_by_line():
    gate = threading.Event()
    vision = ScriptedVision({"B1": Verdict("target", 16, 0.9), "B2": Verdict("bullseye", None, 0.8)}, gate)
    run, controller, sent, stm, worker, state = harness(vision_client=vision)
    try:
        controller.start(run)
        assert wait_for(sent, "ROBOT,8.00,8.00,0")   # the run's last line before it waits on verdicts
        gate.set()                      # verdicts only now, so their lines land after the driving
        controller.join(5.0)
    finally:
        worker.close()
    assert sent == [
        "MSG,Planning...",
        "MSG,Visiting 2 of 2",
        "ROBOT,1.00,4.00,0",            # FS 30 from (1,1,N)
        "ROBOT,5.00,8.00,90",           # TR 90, radius 40 cm
        "MSG,Capturing B1",
        "ROBOT,4.00,4.00,90",           # snap to the planner's capture pose (spec §6.2 order)
        "ROBOT,3.00,4.00,90",           # BS 10 facing east
        "ROBOT,7.00,8.00,0",            # FL 90
        "ROBOT,7.00,10.00,0",           # FS 20
        "MSG,Capturing B2",
        "ROBOT,8.00,8.00,0",            # snap
        "TARGET,B1,16",
        "MSG,B2: bullseye - wrong face?",
        "MSG,Done: 1 of 2 recognised",
    ]
    assert stm.sent == ["FS 30", "TR 90", "BS 10", "TL 90", "FS 20"]
    assert state.last_robot_line == "ROBOT,8.00,8.00,0"
    assert run.submitted == [1, 2]


def test_planner_error_means_the_robot_never_moves():
    run, controller, sent, stm, worker, _ = harness(planner=FakePlanner(error=PlannerError("planner unreachable: refused")))
    try:
        run.run()
    finally:
        worker.close()
    assert sent == ["MSG,Planning...", "MSG,Planner error: planner unreachable: refused"]
    assert stm.sent == []


def test_turn_in_place_falls_back_to_optimal_and_says_so():
    planner = FakePlanner(plan=Plan((), ()))
    run, _, sent, _, worker, _ = harness(message=ImageRec("turnInPlace", Pose(1.0, 1.0, 0.0), OBSTACLES),
                                          planner=planner)
    try:
        run.run()
    finally:
        worker.close()
    assert planner.requests[0]["strategy"] == "optimal"
    assert "MSG,turnInPlace not supported by planner - using optimal" in sent


def test_missing_robot_pose_assumes_the_start_zone():
    planner = FakePlanner(plan=Plan((), ()))
    run, _, sent, _, worker, _ = harness(message=ImageRec("greedy", None, OBSTACLES), planner=planner)
    try:
        run.run()
    finally:
        worker.close()
    assert "MSG,No robot pose in start - assuming start zone" in sent
    assert planner.requests[0]["robot"]["south_west"] == {"x": 0, "y": 0}


def test_unreachable_obstacles_are_announced():
    planner = FakePlanner(plan=Plan((), ((3, "NO_PATH"), (5, "NO_OBJECTIVES"))))
    run, _, sent, _, worker, _ = harness(planner=planner)
    try:
        run.run()
    finally:
        worker.close()
    assert sent[1:3] == ["MSG,Visiting 0 of 2", "MSG,Unreachable: B3, B5"]
    assert sent[-1] == "MSG,Done: 0 of 2 recognised"


def test_stop_mid_segment():
    run, controller, sent, stm, worker, _ = harness(stm=FakeStmDriver(straight_cm_per_s=1.0))
    try:
        controller.start(run)
        assert wait_for(stm.sent, "FS 30")       # the 30 s move is in flight
        controller.stop()
        controller.join(5.0)
    finally:
        worker.close()
    assert sent[-1] == "MSG,Stopped"
    assert stm.sent == ["FS 30", "S"]
    assert not any(line.startswith("MSG,Done") for line in sent)


def test_stm_error_aborts_with_the_reply():
    stm = GyroFailsOnTurns(straight_cm_per_s=10000.0)
    run, _, sent, _, worker, _ = harness(stm=stm)
    try:
        run.run()
    finally:
        worker.close()
    assert sent[-1] == "MSG,Aborted at TR 90: ERR,GYRO"
    assert stm.sent == ["FS 30", "TR 90", "S"]


def test_camera_failure_is_reported_and_the_run_continues():
    run, _, sent, stm, worker, _ = harness(camera=BrokenCamera())
    try:
        run.run()
    finally:
        worker.close()
    assert "MSG,B1: camera failed" in sent
    assert "MSG,B2: camera failed" in sent
    assert sent[-1] == "MSG,Done: 0 of 2 recognised"
    assert len(stm.sent) == 5


def test_done_reports_pending_verdicts_when_the_server_is_slow():
    vision = ScriptedVision({}, gate=threading.Event())    # never released during the run
    run, _, sent, _, worker, _ = harness(vision_client=vision, drain_timeout_s=0.3)
    try:
        run.run()
        # Assert BEFORE releasing the gate: once it opens, the worker appends its
        # (late) miss messages after the Done line, which is exactly the real behaviour.
        assert sent[-1] == "MSG,Done: 0 of 2 recognised, verdicts pending"
    finally:
        vision.gate.set()
        worker.close()
