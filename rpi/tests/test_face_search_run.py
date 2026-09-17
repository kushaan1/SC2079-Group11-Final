import threading
import time

from rpi.camera import FakeCamera
from rpi.model import Capture, Obstacle, Plan, Pose, Segment, Straight, Verdict
from rpi.planner_client import PlannerError
from rpi.protocol import FaceSearch
from rpi.run import FaceSearchRun, RunController, RunState
from rpi.stm_driver import FakeStmDriver
from rpi.vision_worker import VisionWorker

RADII = {"FORWARD_LEFT": 40, "FORWARD_RIGHT": 40, "BACKWARD_LEFT": 40, "BACKWARD_RIGHT": 40}
OBSTACLE = Obstacle(1, 10, 6, "S")
MESSAGE = FaceSearch(Pose(1.0, 1.0, 0.0), (OBSTACLE,))

# One segment per face; N is unreachable. seconds decide the order: W (3) before E (5).
PLANS = {
    "SOUTH": Plan((Segment(1, (Straight("FORWARD", 10), Capture()), Pose(10.0, 3.0, 0.0), 2.0),), ()),
    "EAST": Plan((Segment(1, (Capture(),), Pose(13.0, 6.0, 270.0), 5.0),), ()),
    "WEST": Plan((Segment(1, (Capture(),), Pose(7.0, 6.0, 90.0), 3.0),), ()),
    "NORTH": Plan((), ((1, "NO_OBJECTIVES"),)),
}


class FacePlanner:
    def __init__(self, plans=PLANS, error=None):
        self._plans = plans
        self._error = error
        self.faces = []

    def plan(self, body):
        if self._error is not None:
            raise self._error
        face = body["obstacles"][0]["direction"]
        self.faces.append(face)
        return self._plans[face]


class SequenceVision:
    """One verdict per capture (the harness uses one frame per capture)."""

    def __init__(self, verdicts, gate=None):
        self.configured = True
        self._verdicts = list(verdicts)
        self.gate = gate

    def detect(self, jpeg, object_id):
        if self.gate is not None:
            self.gate.wait(5.0)
        return self._verdicts.pop(0) if self._verdicts else Verdict("no_detection")


def harness(message=MESSAGE, planner=None, vision_client=None, verdict_timeout_s=2.0):
    sent = []
    stm = FakeStmDriver(straight_cm_per_s=10000.0, turn_s=0.0)
    camera = FakeCamera()
    camera.start()
    worker = VisionWorker(vision_client or SequenceVision([]), sent.append, frames_per_obstacle=1)
    worker.start()
    run = FaceSearchRun(
        message, planner or FacePlanner(), verdict_timeout_s=verdict_timeout_s,
        stm=stm, camera=camera, vision=worker, send=sent.append, state=RunState(), radii=RADII,
        settle_s=0.0, frames=1,
    )
    return run, RunController(stm, sent.append), sent, stm, worker


def wait_for(sent, line, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if line in sent:
            return True
        time.sleep(0.01)
    return False


def test_bullseye_on_the_declared_face_then_the_cheapest_other_face_has_the_image():
    planner = FacePlanner()
    run, _, sent, stm, worker = harness(planner=planner, vision_client=SequenceVision(
        [Verdict("bullseye", None, 0.8), Verdict("target", 25, 0.9)]))
    try:
        run.run()
    finally:
        worker.close()
    assert sent == [
        "MSG,Planning...",
        "ROBOT,1.00,2.00,0",
        "MSG,Capturing B1",
        "ROBOT,10.00,3.00,0",
        "MSG,B1: bullseye on S face - searching",
        "MSG,Capturing B1",
        "ROBOT,7.00,6.00,90",
        "TARGET,B1,25",
        "MSG,Found image on W face of B1",
    ]
    assert planner.faces == ["SOUTH", "NORTH", "EAST", "WEST"]
    assert stm.sent == ["FW 10"]


def test_all_faces_examined_without_an_image():
    planner = FacePlanner()
    run, _, sent, _, worker = harness(planner=planner, vision_client=SequenceVision(
        [Verdict("bullseye"), Verdict("bullseye"), Verdict("no_detection")]))
    try:
        run.run()
    finally:
        worker.close()
    assert sent[-1] == "MSG,No image found on B1"
    assert "MSG,B1: bullseye on W face - searching" in sent
    assert "MSG,B1: nothing on E face - searching" in sent
    assert planner.faces == ["SOUTH", "NORTH", "EAST", "WEST", "EAST"]


def test_stop_while_waiting_for_a_verdict():
    gate = threading.Event()
    run, controller, sent, stm, worker = harness(vision_client=SequenceVision([Verdict("target", 11)], gate))
    try:
        controller.start(run)
        assert wait_for(sent, "MSG,Capturing B1")
        controller.stop()
        controller.join(5.0)
        # Assert before the gate opens: afterwards the worker legitimately appends
        # the late TARGET line, and the run must NOT have claimed a find.
        assert sent[-1] == "MSG,Stopped"
        assert stm.sent[-1] == "S"
    finally:
        gate.set()
        worker.close()
    assert "MSG,Found image on S face of B1" not in sent


def test_no_vision_server_does_not_stall_the_search():
    class Unconfigured:
        configured = False

        def detect(self, jpeg, object_id):
            raise AssertionError("never called")

    planner = FacePlanner()
    run, _, sent, _, worker = harness(planner=planner, vision_client=Unconfigured(), verdict_timeout_s=30.0)
    started = time.monotonic()
    try:
        run.run()
    finally:
        worker.close()
    assert time.monotonic() - started < 5.0
    assert sent[-1] == "MSG,No image found on B1"
    assert "MSG,Vision URL not configured" in sent
    assert "MSG,B1: no verdict on S face - searching" in sent


def test_planner_error_ends_the_search():
    run, _, sent, stm, worker = harness(planner=FacePlanner(error=PlannerError("planner unreachable: x")))
    try:
        run.run()
    finally:
        worker.close()
    assert sent == ["MSG,Planning...", "MSG,Planner error: planner unreachable: x"]
    assert stm.sent == []


def test_no_obstacle_or_no_face_is_refused():
    run, _, sent, _, worker = harness(message=FaceSearch(Pose(1.0, 1.0, 0.0), ()))
    run.run()
    worker.close()
    assert sent == ["MSG,Face search needs one obstacle"]

    run, _, sent, _, worker = harness(message=FaceSearch(None, (Obstacle(2, 5, 5, None),)))
    run.run()
    worker.close()
    assert sent == ["MSG,B2 has no face"]


def test_extra_obstacles_are_ignored_with_a_note():
    planner = FacePlanner()
    run, _, sent, _, worker = harness(
        message=FaceSearch(Pose(1.0, 1.0, 0.0), (OBSTACLE, Obstacle(2, 3, 3, "N"))),
        planner=planner, vision_client=SequenceVision([Verdict("target", 30, 0.5)]))
    try:
        run.run()
    finally:
        worker.close()
    assert sent[0] == "MSG,Face search uses B1 only; ignoring 1 other obstacle(s)"
    assert sent[-1] == "MSG,Found image on S face of B1"
