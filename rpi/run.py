"""Runs: the Task 1 executor, the A.5 face search, and the controller that
holds at most one of them (spec §5.11, §6).
"""

import logging
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

from rpi import arena, protocol
from rpi import pose as posing
from rpi.camera import Camera, CameraError
from rpi.model import FACES, START_POSE, Capture, Obstacle, Pose, Segment
from rpi.planner_client import PlannerError
from rpi.protocol import FaceSearch, ImageRec
from rpi.stm_driver import StmAborted, StmDriver, StmError, encode_instruction
from rpi.vision_worker import Result, VisionWorker

LOG = logging.getLogger(__name__)

Send = Callable[[str], None]


class RunState:
    """What main needs to replay after a Bluetooth reconnect (spec §6.1 step 8)."""

    def __init__(self) -> None:
        self.last_robot_line = None  # type: Optional[str]


class BaseRun:
    def __init__(self) -> None:
        self.abort = threading.Event()
        self.finished = threading.Event()

    def run(self) -> None:
        raise NotImplementedError


class RunController:
    """At most one run. stop() aborts the run and stops the STM; the run
    thread itself sends MSG,Stopped when it notices."""

    def __init__(self, stm: StmDriver, send: Send) -> None:
        self._stm = stm
        self._send = send
        self._lock = threading.Lock()
        self._run = None     # type: Optional[BaseRun]
        self._thread = None  # type: Optional[threading.Thread]

    def active(self) -> bool:
        with self._lock:
            return self._run is not None and not self._run.finished.is_set()

    def start(self, run: BaseRun) -> bool:
        with self._lock:
            if self._run is not None and not self._run.finished.is_set():
                return False
            self._run = run
            self._thread = threading.Thread(target=self._drive, args=(run,), name="run", daemon=True)
            self._thread.start()
            return True

    def _drive(self, run: BaseRun) -> None:
        try:
            run.run()
        except Exception as error:   # a bug in a run must never take the program down
            LOG.exception("run crashed")
            self._send(protocol.msg("Run failed: %s" % error))
        finally:
            run.finished.set()

    def stop(self) -> bool:
        with self._lock:
            run = self._run
        if run is None or run.finished.is_set():
            return False
        run.abort.set()
        self._stm.stop()
        return True

    def join(self, timeout: float) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)


# --- runs -------------------------------------------------------------------------

class _DrivingRun(BaseRun):
    """What Task 1 and the face search share: drive a segment, capture, report pose."""

    def __init__(
        self,
        stm: StmDriver,
        camera: Camera,
        vision: VisionWorker,
        send: Send,
        state: RunState,
        radii: Dict[str, int],
        settle_s: float,
        frames: int,
    ) -> None:
        super().__init__()
        self._stm = stm
        self._camera = camera
        self._vision = vision
        self._send = send
        self._state = state
        self._radii = radii
        self._settle_s = settle_s
        self._frames = frames
        self.submitted = []  # type: List[int]
        self.last_capture_submitted = False

    def _msg(self, text: str) -> None:
        self._send(protocol.msg(text))

    def _report_pose(self, pose: Pose) -> None:
        line = protocol.robot(pose)
        self._state.last_robot_line = line
        self._send(line)

    def _drive_segment(self, segment: Segment, start: Pose, quiet: bool = False) -> Tuple[str, Pose]:
        """Execute one segment. Returns ("ok" | "stopped" | "failed", pose)."""
        pose = start
        for instr in segment.instructions:
            if self.abort.is_set():
                return "stopped", pose
            if isinstance(instr, Capture):
                self._msg("Capturing B%d" % segment.image_id)
                pose = segment.end_pose          # the planner's exact capture pose
                self._report_pose(pose)
                self._capture(segment.image_id, quiet)
                continue
            try:
                self._stm.execute(instr, abort=self.abort)
            except StmAborted:
                return "stopped", pose
            except StmError as error:
                self._stm.stop()
                self._msg("Aborted at %s: %s" % (encode_instruction(instr), error.reply))
                return "failed", pose
            pose = posing.advance(pose, instr, self._radii)
            self._report_pose(pose)
        return "ok", pose

    def _capture(self, obstacle_id: int, quiet: bool) -> bool:
        """Settle, take the frames, hand them to the worker. True if the worker took them."""
        time.sleep(self._settle_s)
        frames = []  # type: List[bytes]
        try:
            for _ in range(self._frames):
                frames.append(self._camera.capture_jpeg())
        except CameraError as error:
            LOG.warning("camera failed on B%d: %s", obstacle_id, error)
            self._msg("B%d: camera failed" % obstacle_id)
        accepted = bool(frames) and self._vision.submit(obstacle_id, frames, quiet=quiet)
        if accepted:
            self.submitted.append(obstacle_id)
        self.last_capture_submitted = accepted
        return accepted


class Task1Run(_DrivingRun):
    """The image-recognition run (spec §6.1)."""

    def __init__(self, message: ImageRec, planner: object, drain_timeout_s: float,
                 strategy_fallback: str, **driving) -> None:
        super().__init__(**driving)
        self._message = message
        self._planner = planner
        self._drain_timeout_s = drain_timeout_s
        self._fallback = strategy_fallback

    def run(self) -> None:
        message = self._message
        self._msg("Planning...")

        start = message.robot
        if start is None:
            start = START_POSE
            self._msg("No robot pose in start - assuming start zone")

        strategy = message.algorithm
        if strategy not in ("greedy", "optimal"):
            self._msg("%s not supported by planner - using %s" % (strategy, self._fallback))
            strategy = self._fallback

        try:
            request = arena.to_planner_request(message.obstacles, start, strategy)
        except ValueError as error:
            self._msg("Cannot plan: %s" % error)
            return
        try:
            plan = self._planner.plan(request)
        except PlannerError as error:
            self._msg("Planner error: %s" % error)
            return

        total = len(message.obstacles)
        self._msg("Visiting %d of %d" % (len(plan.segments), total))
        if plan.unreachable:
            self._msg("Unreachable: " + ", ".join("B%d" % image_id for image_id, _ in plan.unreachable))

        pose = start
        for segment in plan.segments:
            outcome, pose = self._drive_segment(segment, pose)
            if outcome == "stopped":
                self._msg("Stopped")
                return
            if outcome == "failed":
                return

        complete = self._wait_for_verdicts()
        if self.abort.is_set():
            self._msg("Stopped")
            return
        found = sum(
            1 for result in self._vision.results()
            if result.status == "target" and result.obstacle_id in self.submitted
        )
        text = "Done: %d of %d recognised" % (found, total)
        if not complete:
            text += ", verdicts pending"
        self._msg(text)

    def _wait_for_verdicts(self) -> bool:
        end = time.monotonic() + self._drain_timeout_s
        while True:
            if self._vision.wait_all(0.2):
                return True
            if self.abort.is_set() or time.monotonic() >= end:
                return False


_VERDICT_TEXT = {"bullseye": "bullseye", "no_detection": "nothing", "error": "no verdict"}


class FaceSearchRun(_DrivingRun):
    """The A.5 demo (spec §6.3): find the face that carries the image."""

    def __init__(self, message: FaceSearch, planner: object, verdict_timeout_s: float, **driving) -> None:
        super().__init__(**driving)
        self._message = message
        self._planner = planner
        self._verdict_timeout_s = verdict_timeout_s

    def run(self) -> None:
        message = self._message
        if not message.obstacles:
            self._msg("Face search needs one obstacle")
            return
        obstacle = message.obstacles[0]
        if len(message.obstacles) > 1:
            self._msg("Face search uses B%d only; ignoring %d other obstacle(s)"
                      % (obstacle.obstacle_id, len(message.obstacles) - 1))
        if obstacle.face is None:
            self._msg("B%d has no face" % obstacle.obstacle_id)
            return
        self._msg("Planning...")
        pose = message.robot
        if pose is None:
            pose = START_POSE
            self._msg("No robot pose in start - assuming start zone")

        checked = set()   # type: set
        face = obstacle.face
        try:
            segment = self._plan_face(obstacle, face, pose)
            while True:
                if segment is None:
                    self._msg("B%d: %s face unreachable" % (obstacle.obstacle_id, face))
                    checked.add(face)
                else:
                    outcome, pose = self._drive_segment(segment, pose, quiet=True)
                    if outcome == "stopped":
                        self._msg("Stopped")
                        return
                    if outcome == "failed":
                        return
                    # No frames reached the worker (camera or vision server down): don't
                    # sit out the verdict timeout for a verdict that can never come.
                    result = self._await_verdict(obstacle.obstacle_id) if self.last_capture_submitted else None
                    if self.abort.is_set():
                        self._msg("Stopped")
                        return
                    if result is not None and result.status == "target":
                        self._msg("Found image on %s face of B%d" % (face, obstacle.obstacle_id))
                        return
                    checked.add(face)
                    seen = _VERDICT_TEXT["error"] if result is None else _VERDICT_TEXT[result.status]
                    self._msg("B%d: %s on %s face - searching" % (obstacle.obstacle_id, seen, face))

                if len(checked) >= len(FACES):
                    self._msg("No image found on B%d" % obstacle.obstacle_id)
                    return
                face, segment = self._next_face(obstacle, pose, checked)
                if face is None:
                    self._msg("No image found on B%d - no other face reachable" % obstacle.obstacle_id)
                    return
        except PlannerError as error:
            self._msg("Planner error: %s" % error)

    def _plan_face(self, obstacle: Obstacle, face: str, pose: Pose) -> Optional[Segment]:
        """One planner request for one face. None if the planner cannot reach it."""
        candidate = Obstacle(obstacle.obstacle_id, obstacle.x, obstacle.y, face)
        plan = self._planner.plan(arena.to_planner_request([candidate], pose, "optimal"))
        return plan.segments[0] if plan.segments else None

    @staticmethod
    def _cost(segment: Segment) -> Tuple[float, int]:
        """Planner seconds when it gave them, else fewest instructions (spec §6.3 step 5)."""
        return (segment.seconds if segment.seconds > 0 else float("inf"), len(segment.instructions))

    def _next_face(self, obstacle: Obstacle, pose: Pose, checked: set) -> Tuple[Optional[str], Optional[Segment]]:
        """The cheapest unchecked face by the planner's estimate. Unreachable faces become checked."""
        best = None  # type: Optional[Tuple[str, Segment]]
        for face in FACES:
            if face in checked:
                continue
            segment = self._plan_face(obstacle, face, pose)
            if segment is None:
                checked.add(face)
                continue
            if best is None or self._cost(segment) < self._cost(best[1]):
                best = (face, segment)
        return best if best is not None else (None, None)

    def _await_verdict(self, obstacle_id: int) -> Optional[Result]:
        end = time.monotonic() + self._verdict_timeout_s
        while time.monotonic() < end and not self.abort.is_set():
            result = self._vision.wait(obstacle_id, 0.2)
            if result is not None:
                return result
        return None
