import time

from rpi.arrow import ArrowSource, Consensus, FakeArrowSource, Sighting
from rpi.camera import CameraError, FakeCamera
from rpi.protocol import BeginFastest
from rpi.run import FastestRun, RunController
from rpi.stm_driver import FakeStmDriver, StmError


# --- doubles -----------------------------------------------------------------------------

class Refusing(FakeArrowSource):
    """A source that is not configured, or whose pre-flight fails."""

    def __init__(self, configured=True, reason=None):
        super().__init__([], label="refusing")
        self._configured = configured
        self._reason = reason

    @property
    def configured(self):
        return self._configured

    def check(self):
        return self._reason


class Blind(ArrowSource):
    """Never sees an arrow; every frame takes `frame_s`."""

    def __init__(self, frame_s=0.02):
        self._frame_s = frame_s
        self.frames = 0

    def sightings(self, jpeg):
        self.frames += 1
        if self._frame_s:
            time.sleep(self._frame_s)
        return []

    def check(self):
        return None

    @property
    def configured(self):
        return True

    @property
    def describe(self):
        return "fake blind"


class SeesAfterNudge(Blind):
    """Nothing until the STM has been nudged, then `direction` every frame."""

    def __init__(self, stm, direction="left"):
        super().__init__(frame_s=0.0)
        self._stm = stm
        self._direction = direction

    def sightings(self, jpeg):
        self.frames += 1
        nudged = any(line.startswith(("BW ", "FW ")) for line in self._stm.sent)
        return [Sighting(self._direction, 1.0)] if nudged else []


class Unavailable(FakeStmDriver):
    @property
    def available(self):
        return False


class SeekTimesOut(FakeStmDriver):
    def seek(self, cm, abort=None):
        self.calls.append(("seek", cm))
        raise StmError("seek %d" % cm, "ERR,TIMEOUT")


class NudgeFails(FakeStmDriver):
    def raw(self, line, abort=None):
        self.sent.append(line)
        raise StmError(line, "ERR,UNKNOWN")


def fake_stm(seek=(87, 0), ranges=(31, 29), **kwargs):
    return FakeStmDriver(straight_cm_per_s=10000.0, turn_s=0.0,
                         seek_distances=list(seek), range_readings=list(ranges), **kwargs)


class BrokenCamera(FakeCamera):
    def capture_jpeg(self):
        raise CameraError("no data from sensor")


def harness(arrows=("left", "right"), stm=None, source=None, camera=None, attempt_s=0.2, budget_s=1.0,
            stop_cm=(30, 30), **stm_kwargs):
    sent = []
    stm = stm if stm is not None else fake_stm(**stm_kwargs)
    camera = camera if camera is not None else FakeCamera()
    camera.start()
    source = source if source is not None else FakeArrowSource.for_reads(list(arrows), frames=3)
    run = FastestRun(BeginFastest(), stm, camera, sent.append, source, Consensus(3, 5, 0.75),
                     stop_cm, attempt_s, budget_s, 10, 0.0)
    controller = RunController(stm, sent.append)
    return run, controller, sent, stm


def wait_until(predicate, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def finish(run, controller, timeout=5.0):
    controller.start(run)
    controller.join(timeout)
    assert run.finished.is_set()


# --- the transcript (spec §6) -------------------------------------------------------------

def test_full_run_line_by_line():
    run, controller, sent, stm = harness()
    finish(run, controller)
    assert sent[:-1] == [
        "MSG,Fastest: arrow source fake left,right",
        "MSG,Seeking obstacle 1",
        "MSG,Obstacle 1 at 87 cm",
        "MSG,Reading arrow 1",
        "MSG,Arrow 1: LEFT",
        "MSG,Seeking obstacle 2",
        "MSG,Obstacle 2 already in range",
        "MSG,Reading arrow 2",
        "MSG,Arrow 2: RIGHT",
        "MSG,Returning",
    ]
    assert sent[-1].startswith("MSG,Parked in ") and sent[-1].endswith(" s (Pi clock)")
    assert stm.calls == [
        ("seek", 30), ("range",), ("round", 1, "L"),
        ("seek", 30), ("range",), ("round", 2, "R"),
        ("home",),
    ]
    assert stm.sent == []                 # no nudges, no stop


def test_stop_thresholds_come_from_the_config_pair():
    run, controller, sent, stm = harness(stop_cm=(35, 25))
    finish(run, controller)
    assert [call for call in stm.calls if call[0] == "seek"] == [("seek", 35), ("seek", 25)]


# --- pre-flight (spec §6, §7) ----------------------------------------------------------------

def test_refused_when_the_source_is_not_configured():
    run, controller, sent, stm = harness(source=Refusing(configured=False))
    finish(run, controller)
    assert sent == ["MSG,Fastest: arrow source fake refusing", "MSG,Arrow source not configured"]
    assert stm.calls == []


def test_refused_when_the_pre_flight_fails():
    run, controller, sent, stm = harness(source=Refusing(reason="Vision server unreachable"))
    finish(run, controller)
    assert sent == ["MSG,Fastest: arrow source fake refusing", "MSG,Vision server unreachable"]
    assert stm.calls == []


def test_refused_when_the_stm_is_unavailable():
    run, controller, sent, stm = harness(stm=Unavailable(straight_cm_per_s=10000.0))
    finish(run, controller)
    assert sent == ["MSG,Fastest: arrow source fake left,right", "MSG,STM unavailable"]
    assert stm.calls == []


# --- stop (spec §4, §7) -----------------------------------------------------------------------

def test_stop_during_the_arrow_read():
    run, controller, sent, stm = harness(source=Blind(frame_s=0.02), attempt_s=5.0, budget_s=30.0)
    controller.start(run)
    assert wait_until(lambda: "MSG,Reading arrow 1" in sent)
    controller.stop()
    controller.join(5.0)
    assert sent[-1] == "MSG,Stopped"
    assert stm.sent == ["S"]
    assert stm.calls == [("seek", 30), ("range",)]      # no ROUND after a stop


def test_stop_during_a_manoeuvre():
    run, controller, sent, stm = harness(seek=(87,), ranges=(31,), manoeuvre_s=60.0)
    controller.start(run)
    assert wait_until(lambda: ("round", 1, "L") in stm.calls)
    controller.stop()
    controller.join(5.0)
    assert sent[-1] == "MSG,Stopped"
    assert stm.calls == [("seek", 30), ("range",), ("round", 1, "L")]
    assert stm.sent == ["S"]


# --- STM errors (spec §7) ---------------------------------------------------------------------

def test_stm_error_aborts_the_run_with_the_drivers_reply():
    run, controller, sent, stm = harness(stm=SeekTimesOut(straight_cm_per_s=10000.0))
    finish(run, controller)
    assert sent[-1] == "MSG,Aborted at seek 30: ERR,TIMEOUT"
    assert stm.sent == ["S"]                              # the run stops the car, as Task 1 does


def test_nudge_failure_ends_the_run():
    stm = NudgeFails(straight_cm_per_s=10000.0, seek_distances=[87], range_readings=[31])
    run, controller, sent, stm = harness(stm=stm, source=Blind(frame_s=0.0), attempt_s=0.05, budget_s=2.0)
    finish(run, controller)
    assert sent[-1] == "MSG,Aborted at BW 10: ERR,UNKNOWN"
    assert stm.sent == ["BW 10", "S"]


# --- seek and sensor narration (spec §6) ------------------------------------------------------

def test_seek_without_a_distance_is_narrated_as_reached():
    run, controller, sent, stm = harness(seek=(None, None))
    finish(run, controller)
    assert sent[2] == "MSG,Obstacle 1 reached"
    assert sent[6] == "MSG,Obstacle 2 reached"
    assert sent[-1].startswith("MSG,Parked in ")


def test_far_sensor_reading_is_a_warning_and_the_run_continues():
    run, controller, sent, stm = harness(ranges=(52, 29))
    finish(run, controller)
    assert sent[2:5] == ["MSG,Obstacle 1 at 87 cm", "MSG,Warning: sensor reads 52 cm", "MSG,Reading arrow 1"]
    assert sent[-1].startswith("MSG,Parked in ")


def test_no_sensor_reading_is_a_warning():
    run, controller, sent, stm = harness(ranges=())
    finish(run, controller)
    assert sent[3] == "MSG,Warning: no sensor reading"
    assert sent[-1].startswith("MSG,Parked in ")


# --- the nudge loop (spec §6) -------------------------------------------------------------------

def test_no_vote_nudges_back_and_reads_again():
    stm = fake_stm(seek=(87, 0), ranges=(31, 41, 29))
    run, controller, sent, stm = harness(stm=stm, source=SeesAfterNudge(stm, "left"), attempt_s=0.05, budget_s=2.0)
    finish(run, controller)
    assert sent[3:6] == ["MSG,Reading arrow 1", "MSG,Arrow 1: no vote, nudging back 10 cm", "MSG,Arrow 1: LEFT"]
    assert stm.sent == ["BW 10"]
    assert stm.calls[:4] == [("seek", 30), ("range",), ("range",), ("round", 1, "L")]   # RANGE again after the nudge
    assert sent[-1].startswith("MSG,Parked in ")


def test_no_vote_with_a_far_reading_nudges_forward():
    stm = fake_stm(seek=(87, 0), ranges=(52, 30, 29))
    run, controller, sent, stm = harness(stm=stm, source=SeesAfterNudge(stm, "right"), attempt_s=0.05, budget_s=2.0)
    finish(run, controller)
    assert "MSG,Arrow 1: no vote, nudging forward 10 cm" in sent
    assert stm.sent == ["FW 10"]
    assert ("round", 1, "R") in stm.calls


def test_short_seek_makes_the_first_nudge_forward():
    stm = fake_stm(seek=(20, 0), ranges=(38, 29, 29))       # 20 cm seek, sensor does not see 30 cm
    run, controller, sent, stm = harness(stm=stm, source=SeesAfterNudge(stm, "left"), attempt_s=0.05, budget_s=2.0)
    finish(run, controller)
    assert "MSG,Arrow 1: no vote, nudging forward 10 cm - possible false stop" in sent
    assert stm.sent == ["FW 10"]


def test_short_seek_with_the_obstacle_in_view_nudges_back():
    stm = fake_stm(seek=(35, 0), ranges=(29, 39, 29))       # obstacle 1 at its nearest: a real stop
    run, controller, sent, stm = harness(stm=stm, source=SeesAfterNudge(stm, "left"), attempt_s=0.05, budget_s=2.0)
    finish(run, controller)
    assert "MSG,Arrow 1: no vote, nudging back 10 cm" in sent
    assert stm.sent == ["BW 10"]


def test_budget_exhausted_stops_the_run():
    run, controller, sent, stm = harness(source=Blind(frame_s=0.0), attempt_s=0.05, budget_s=0.22)
    finish(run, controller)
    assert sent[-1] == "MSG,Arrow 1 not readable - stopped"
    nudges = [line for line in sent if line.startswith("MSG,Arrow 1: no vote, nudging")]
    assert 2 <= len(nudges) <= 5                          # 0.22 s budget / 0.05 s attempts
    assert stm.sent == ["BW 10"] * len(nudges)
    assert not any(call[0] in ("round", "home") for call in stm.calls)


def test_camera_failure_counts_as_empty_frames_until_the_budget_ends():
    source = FakeArrowSource.for_reads(["left", "right"], frames=3)
    run, controller, sent, stm = harness(source=source, camera=BrokenCamera(), attempt_s=0.05, budget_s=0.25)
    finish(run, controller)
    assert sent[-1] == "MSG,Arrow 1 not readable - stopped"
    assert source.calls == 0                                # no frame ever reached the source
    assert not any(call[0] in ("round", "home") for call in stm.calls)
