"""Runs: the Task 1 executor, the A.5 face search, the Task 2 fastest car, and the
controller that holds at most one of them (spec §5.11, §6).
"""

import logging
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

from rpi import arena, protocol
from rpi import pose as posing
from rpi.arrow import ArrowSource, Consensus, read_arrow
from rpi.camera import Camera, CameraError
from rpi.model import FACES, START_POSE, Capture, Obstacle, Pose, Segment
from rpi.planner_client import PlannerError
from rpi.protocol import BeginFastest, FaceSearch, ImageRec
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


# --- Task 2 ---------------------------------------------------------------------------

class FastestRun(BaseRun):
    """The Task 2 run (Task 2 spec §6): seek, read, round, seek, read, round, home.
    A BaseRun, not a _DrivingRun: the planner is not involved and there is no pose to
    report. The tablet sees only MSG lines."""

    def __init__(
        self,
        message: BeginFastest,
        stm: StmDriver,
        camera: Camera,
        send: Send,
        source: ArrowSource,
        consensus: Consensus,
        stop_cm: Tuple[int, int],
        attempt_s: float,
        budget_s: float,
        nudge_cm: int,
        settle_s: float,
    ) -> None:
        super().__init__()
        self._message = message
        self._stm = stm
        self._camera = camera
        self._send = send
        self._source = source
        self._consensus = consensus
        self._stop_cm = stop_cm
        self._attempt_s = attempt_s
        self._budget_s = budget_s
        self._nudge_cm = nudge_cm
        self._settle_s = settle_s

    def _msg(self, text: str) -> None:
        self._send(protocol.msg(text))

    def run(self) -> None:
        self._msg("Fastest: arrow source %s" % self._source.describe)
        if not self._source.configured:
            self._msg("Arrow source not configured")
            return
        reason = self._source.check()
        if reason is not None:
            self._msg(reason)
            return
        if not self._stm.available:
            self._msg("STM unavailable")
            return

        started = time.monotonic()
        for number, stop_cm in ((1, self._stop_cm[0]), (2, self._stop_cm[1])):
            approached = self._approach(number, stop_cm)
            if approached is None:
                return
            travelled, reading = approached
            direction = self._read(number, stop_cm, travelled, reading)
            if direction is None:
                return
            side = "L" if direction == "left" else "R"
            ok, _ = self._call(lambda: self._stm.round(number, side, abort=self.abort))
            if not ok:
                return
        self._msg("Returning")
        ok, _ = self._call(lambda: self._stm.home(abort=self.abort))
        if not ok:
            return
        self._msg("Parked in %.1f s (Pi clock)" % (time.monotonic() - started))

    def _call(self, call: Callable[[], object]) -> Tuple[bool, object]:
        """One STM call. (True, its result), or (False, None) after MSG,Stopped or
        MSG,Aborted at <command>: <reply> - the command text is the driver's own."""
        if self.abort.is_set():
            self._msg("Stopped")
            return False, None
        try:
            return True, call()
        except StmAborted:
            self._msg("Stopped")
            return False, None
        except StmError as error:
            self._stm.stop()
            self._msg("Aborted at %s: %s" % (error.command, error.reply))
            return False, None

    def _approach(self, number: int, stop_cm: int) -> Optional[Tuple[Optional[int], Optional[int]]]:
        """Seek the obstacle, then ask the sensor. (travelled, reading); None once the run is over."""
        self._msg("Seeking obstacle %d" % number)
        ok, travelled = self._call(lambda: self._stm.seek(stop_cm, abort=self.abort))
        if not ok:
            return None
        if travelled == 0:
            self._msg("Obstacle %d already in range" % number)
        elif travelled is None:
            self._msg("Obstacle %d reached" % number)
        else:
            self._msg("Obstacle %d at %d cm" % (number, travelled))
        ok, reading = self._call(lambda: self._stm.range_cm(abort=self.abort))
        if not ok:
            return None
        LOG.info("obstacle %d: seek travelled=%s cm, sensor reads %s cm", number, travelled, reading)
        if reading is None:
            self._msg("Warning: no sensor reading")
        elif reading > stop_cm + 15:
            self._msg("Warning: sensor reads %d cm" % reading)
        return travelled, reading

    def _read(self, number: int, stop_cm: int, travelled: Optional[int],
              reading: Optional[int]) -> Optional[str]:
        """Read the arrow, nudging between attempts, within the budget. None once the run is over."""
        self._msg("Reading arrow %d" % number)
        end = time.monotonic() + self._budget_s
        first = True
        while True:
            remaining = end - time.monotonic()
            if remaining > 0:
                direction = read_arrow(self._camera, self._source, self._consensus,
                                       min(self._attempt_s, remaining), self.abort, self._settle_s)
                if self.abort.is_set():
                    self._msg("Stopped")
                    return None
                if direction is not None:
                    self._msg("Arrow %d: %s" % (number, direction.upper()))
                    return direction
            if time.monotonic() >= end:
                self._msg("Arrow %d not readable - stopped" % number)
                return None
            # No vote: move a little and look again (spec §6). Back is the norm; forward when
            # the sensor says the obstacle is further than it should be, or once after a seek
            # so short it may have stopped on a spurious echo - unless the sensor now sees
            # the obstacle at the stop distance, in which case the stop was real (obstacle 1
            # can legitimately be 60 cm out, a ~35 cm seek) and forward is the wrong way.
            false_stop = (first and travelled is not None and 0 < travelled < 50
                          and (reading is None or reading > stop_cm))
            forward = false_stop or (reading is not None and reading > stop_cm + 10)
            text = "Arrow %d: no vote, nudging %s %d cm" % (
                number, "forward" if forward else "back", self._nudge_cm)
            if false_stop:
                text += " - possible false stop"
            self._msg(text)
            # [corrected during Task 2 generation] A plain FW/BW jog, not execute()/Straight -
            # that would encode to FS/BS, Task 1's closed-loop planner straight, which is not
            # what the spec's own "the BW (or FW) between attempts" means for a quick nudge.
            nudge_line = "%s %d" % ("FW" if forward else "BW", self._nudge_cm)
            ok, _ = self._call(lambda: self._stm.raw(nudge_line, abort=self.abort))
            if not ok:
                return None
            ok, reading = self._call(lambda: self._stm.range_cm(abort=self.abort))   # the rule uses a fresh reading
            if not ok:
                return None
            first = False
