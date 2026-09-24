"""The only module that knows the STM's wire format (spec §3.2, §5.5).

`StmDriver` is what the rest of the program codes against. `SerialStmDriver`
talks to the real board; `FakeStmDriver` completes moves on a timer so the
whole pipeline runs on a laptop.
"""

import logging
import queue
import threading
import time
from abc import ABC, abstractmethod
from typing import Callable, List, Optional, Tuple

from rpi.model import ARC_KINDS, Arc, Instruction, Straight

LOG = logging.getLogger(__name__)


class StmError(Exception):
    """The STM answered with ERR,... or did not answer."""

    def __init__(self, command: str, reply: str) -> None:
        super().__init__("%s -> %s" % (command, reply))
        self.command = command
        self.reply = reply


class StmAborted(StmError):
    """A move was cut short by stop()."""


class StmUnavailable(StmError):
    """The serial link is down."""


# --- encoding ---------------------------------------------------------------------

_MANUAL_PLAIN = {"f": "F", "b": "B", "s": "S"}
_MANUAL_ARCS = {"tl": "TL", "tr": "TR", "sl": "BL", "sr": "BR"}
_ARC_VERBS = {"FORWARD_LEFT": "TL", "FORWARD_RIGHT": "TR", "BACKWARD_LEFT": "BL", "BACKWARD_RIGHT": "BR"}
# [corrected during Task 2 generation] The Task 2 plan's own replacement of this line dropped
# "BS" by omission - it would have broken is_motion("BS ...") and, with it, every Task 1
# reverse straight (every segment after the first starts with one). Kept here.
_MOTION_VERBS = ("FS", "BS", "FW", "BW", "TL", "TR", "BL", "BR", "PL", "PR", "SEEK", "ROUND", "HOME")


def encode_instruction(instr: Instruction) -> str:
    if isinstance(instr, Straight):
        verb = "FS" if instr.move == "FORWARD" else "BS"
        return "%s %d" % (verb, instr.cm)
    if isinstance(instr, Arc) and instr.kind in ARC_KINDS:
        return "%s %d" % (_ARC_VERBS[instr.kind], instr.degrees)
    raise ValueError("not an STM motion: %r" % (instr,))


def encode_manual(token: str, turn_deg: int) -> str:
    if token in _MANUAL_PLAIN:
        return _MANUAL_PLAIN[token]
    if token in _MANUAL_ARCS:
        return "%s %d" % (_MANUAL_ARCS[token], turn_deg)
    raise ValueError("not a manual token: %r" % (token,))


def is_motion(line: str) -> bool:
    """True for commands whose completion the STM reports; F/B jogs are not."""
    return line.split(" ", 1)[0] in _MOTION_VERBS


ROUND_SIDES = ("L", "R")


def check_round_arguments(obstacle: int, side: str) -> None:
    if obstacle not in (1, 2) or side not in ROUND_SIDES:
        raise ValueError("round takes obstacle 1 or 2 and side L or R, got %r %r" % (obstacle, side))


# Task 2 (Task 2 spec §3.1): proposed in docs/rpi-stm-handover.md §5.3. If the STM team
# respells a verb, change it here, in _MOTION_VERBS and in SerialStmDriver._deadline.
RANGE_LINE = "RANGE"


def encode_seek(cm: int) -> str:
    return "SEEK %d" % cm


def encode_round(obstacle: int, side: str) -> str:
    check_round_arguments(obstacle, side)
    return "ROUND %d %s" % (obstacle, side)


def encode_home() -> str:
    return "HOME"


def parse_seek_distance(reply: str) -> Optional[int]:
    """DONE,SEEK,87 -> 87. Lenient: DONE,SEEK,87.0 -> 87; DONE,SEEK or DONE,SEEK,abc -> None."""
    parts = reply.split(",")
    if len(parts) < 3:
        return None
    try:
        return int(float(parts[2]))
    except ValueError:
        return None


def parse_range(reply: str) -> Optional[int]:
    """RANGE,52 -> 52; anything else -> None."""
    parts = reply.split(",")
    if len(parts) < 2 or parts[0] != RANGE_LINE:
        return None
    try:
        return int(float(parts[1]))
    except ValueError:
        return None


# --- traffic mirror ----------------------------------------------------------------

def _mirror(hook: Optional[Callable[[str], None]], text: str) -> None:
    """Hand one line of the serial conversation ("STM> FS 30" / "STM< ACK,FS") to the
    optional hook - the tablet's raw log. A failing hook must never touch the driver."""
    if hook is None:
        return
    try:
        hook(text)
    except Exception:
        LOG.exception("STM mirror hook failed")


# --- interface ----------------------------------------------------------------------

class StmDriver(ABC):
    @abstractmethod
    def start(self) -> None:
        """Open the link and prove it (raises StmUnavailable)."""

    @abstractmethod
    def manual(self, token: str) -> None:
        """A tablet movement token. Waits for the STM's reply."""

    @abstractmethod
    def manual_raw(self, line: str) -> None:
        """A line passed through untouched (beginFastest)."""

    @abstractmethod
    def raw(self, line: str, abort: Optional[threading.Event] = None) -> str:
        """A line typed by a human (the STM console). Motion verbs wait for ACK then
        DONE with their usual deadlines; anything else (PING, RANGE, MA 50, a typo)
        returns the first reply line of any kind. Raises StmError on ERR or silence."""

    @abstractmethod
    def execute(self, instr: Instruction, abort: Optional[threading.Event] = None) -> None:
        """A planner instruction. Returns when the STM says the motion is done.
        Raises StmAborted without sending anything if `abort` is already set."""

    # -- Task 2 (Task 2 spec §3.1, §5.2) --

    @abstractmethod
    def seek(self, cm: int, abort: Optional[threading.Event] = None) -> Optional[int]:
        """Forward until the range sensor reads <= cm, then stop. Returns the distance the
        STM says it travelled (0 = it was already in range), or None when it gave no
        number. Raises StmError on ERR/silence, StmAborted on stop."""

    @abstractmethod
    def round(self, obstacle: int, side: str, abort: Optional[threading.Event] = None) -> None:
        """Round obstacle 1 or 2 on side "L" or "R"; returns when the STM says it is done."""

    @abstractmethod
    def home(self, abort: Optional[threading.Event] = None) -> None:
        """The return leg into the carpark; returns when the STM says it is done."""

    @abstractmethod
    def range_cm(self, abort: Optional[threading.Event] = None) -> Optional[int]:
        """One forward range reading, or None when the STM gives none. Never raises for a
        missing or error reply - only StmAborted on stop and StmUnavailable on a dead link."""

    @abstractmethod
    def stop(self) -> None:
        """S now, from any thread; an in-flight execute() raises StmAborted."""

    @abstractmethod
    def close(self) -> None:
        pass

    @property
    @abstractmethod
    def available(self) -> bool:
        pass


# --- fake -----------------------------------------------------------------------------

class FakeStmDriver(StmDriver):
    """Completes moves on a timer. Records every line it would have sent."""

    def __init__(
        self,
        straight_cm_per_s: float = 30.0,
        turn_s: float = 3.0,
        turn_deg: int = 45,
        on_line: Optional[Callable[[str], None]] = None,
        seek_distances: Optional[List[Optional[int]]] = None,
        range_readings: Optional[List[Optional[int]]] = None,
        manoeuvre_s: float = 0.0,
    ) -> None:
        self._cm_per_s = straight_cm_per_s
        self._turn_s = turn_s
        self._turn_deg = turn_deg
        self._on_line = on_line
        self._abort = threading.Event()
        self.sent = []  # type: List[str]
        # Task 2 scripts, popped one per call. An empty list or a None entry is "the STM gave
        # no number". Manoeuvres take manoeuvre_s (0 so a laptop rehearsal runs straight through).
        self.seek_distances = list(seek_distances or [])   # type: List[Optional[int]]
        self.range_readings = list(range_readings or [])   # type: List[Optional[int]]
        self._manoeuvre_s = manoeuvre_s
        self.calls = []  # type: List[tuple]

    def _pretend(self, line: str, reply: str) -> None:
        """Record the line and mirror it with the reply the real board would give."""
        self.sent.append(line)
        _mirror(self._on_line, "STM> " + line)
        _mirror(self._on_line, "STM< " + reply)

    def start(self) -> None:
        LOG.info("fake STM ready")

    @property
    def available(self) -> bool:
        return True

    def manual(self, token: str) -> None:
        line = encode_manual(token, self._turn_deg)
        self._pretend(line, "ACK," + _verb(line))

    def manual_raw(self, line: str) -> None:
        self._pretend(line, "ACK," + _verb(line))

    def raw(self, line: str, abort: Optional[threading.Event] = None) -> str:
        line = line.strip()
        if not line:
            raise ValueError("empty line")
        if abort is not None and abort.is_set():
            raise StmAborted(line, "stopped")
        reply = "PONG" if line == "PING" else "ACK," + _verb(line)
        self._pretend(line, reply)
        if is_motion(line):
            reply = "DONE," + _verb(line)
            _mirror(self._on_line, "STM< " + reply)
        return reply

    def execute(self, instr: Instruction, abort: Optional[threading.Event] = None) -> None:
        line = encode_instruction(instr)
        if abort is not None and abort.is_set():
            raise StmAborted(line, "stopped")
        self._pretend(line, "ACK," + _verb(line))
        if isinstance(instr, Straight):
            duration = instr.cm / self._cm_per_s if self._cm_per_s > 0 else 0.0
        else:
            duration = self._turn_s * (instr.degrees / 90.0)
        # Only a stop() that arrives DURING this move aborts it. A stale flag from an
        # earlier stop is cleared here; the pre-set case is the run's `abort` event's job.
        self._abort.clear()
        if self._abort.wait(duration):
            raise StmAborted(line, "stopped")
        _mirror(self._on_line, "STM< DONE," + _verb(line))

    # -- Task 2: the fake records intent in `calls`; StmAborted labels are the wire lines --

    def _begin(self, call: tuple, label: str, abort: Optional[threading.Event]) -> None:
        if abort is not None and abort.is_set():
            raise StmAborted(label, "stopped")
        self._abort.clear()      # as in execute(): only a stop() during this call aborts it
        self.calls.append(call)  # after the clear, so a stop() that sees the call is never lost
        if abort is not None and abort.is_set():
            # A stop() that landed around the clear: RunController sets the run's flag
            # before it calls stop(), so this catches what the clear may have erased.
            raise StmAborted(label, "stopped")

    def _elapse(self, label: str, duration: float) -> None:
        if self._abort.wait(duration):
            raise StmAborted(label, "stopped")

    def seek(self, cm: int, abort: Optional[threading.Event] = None) -> Optional[int]:
        label = encode_seek(cm)
        self._begin(("seek", cm), label, abort)
        travelled = self.seek_distances.pop(0) if self.seek_distances else None
        duration = (travelled or 0) / self._cm_per_s if self._cm_per_s > 0 else 0.0
        self._elapse(label, duration)
        return travelled

    def round(self, obstacle: int, side: str, abort: Optional[threading.Event] = None) -> None:
        label = encode_round(obstacle, side)          # validates the arguments too
        self._begin(("round", obstacle, side), label, abort)
        self._elapse(label, self._manoeuvre_s)

    def home(self, abort: Optional[threading.Event] = None) -> None:
        self._begin(("home",), encode_home(), abort)
        self._elapse(encode_home(), self._manoeuvre_s)

    def range_cm(self, abort: Optional[threading.Event] = None) -> Optional[int]:
        self._begin(("range",), RANGE_LINE, abort)
        return self.range_readings.pop(0) if self.range_readings else None

    def stop(self) -> None:
        self._pretend("S", "ACK,S")
        self._abort.set()

    def close(self) -> None:
        pass


# --- serial ---------------------------------------------------------------------------

class _NoReply(Exception):
    pass


def _verb(line: str) -> str:
    return line.split(" ", 1)[0]


def _reply_prefixes(line: str) -> Tuple[str, ...]:
    """What counts as THIS command's reply: `ACK,<verb>` or any error. Matching
    the verb means a stray `ACK,S` from a concurrent stop() is never mistaken
    for the in-flight move's acknowledgement."""
    return ("ACK," + _verb(line), "ERR,")


def _default_open(port: str, baud: int) -> Callable[[], object]:
    def open_serial():
        import serial   # pyserial; imported here so tests never need it
        # exclusive: a second program opening the same port (the STM console while the
        # main program runs, or vice versa) fails at open instead of stealing replies.
        return serial.Serial(port, baud, timeout=0.2, exclusive=True)
    return open_serial


class SerialStmDriver(StmDriver):
    def __init__(
        self,
        port: str,
        baud: int,
        open_serial: Optional[Callable[[], object]] = None,
        completion: str = "ACK",
        ack_deadline_s: float = 1.0,
        turn_deadline_s: float = 10.0,
        seek_deadline_s: float = 20.0,
        route_deadline_s: float = 25.0,
        home_deadline_s: float = 40.0,
        straight_deadline: Optional[Callable[[int], float]] = None,
        ping_deadline_s: float = 2.0,
        stop_drain_s: float = 0.5,
        retry_delay_s: float = 3.0,
        motor_a: Optional[int] = None,
        motor_b: Optional[int] = None,
        steer_steps: Optional[int] = None,
        manual_turn_deg: int = 45,
        on_link_change: Optional[Callable[[bool], None]] = None,
        on_line: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._open_serial = open_serial or _default_open(port, baud)
        self._on_link_change = on_link_change
        self._on_line = on_line
        self._completion = completion.upper()
        self._ack_deadline_s = ack_deadline_s
        self._turn_deadline_s = turn_deadline_s
        self._seek_deadline_s = seek_deadline_s
        self._route_deadline_s = route_deadline_s
        self._home_deadline_s = home_deadline_s
        self._straight_deadline = straight_deadline or (lambda cm: cm / 10.0 + 5.0)
        self._ping_deadline_s = ping_deadline_s
        self._stop_drain_s = stop_drain_s
        self._retry_delay_s = retry_delay_s
        self._trims = (("MA", motor_a), ("MB", motor_b), ("AS", steer_steps))
        self._manual_turn_deg = manual_turn_deg

        self._serial = None            # type: Optional[object]
        self._available = False
        self._replies = queue.Queue()  # type: queue.Queue
        self._lock = threading.Lock()  # one command in flight at a time
        self._aborted = threading.Event()
        self._closed = threading.Event()
        self._ready = threading.Event()   # set after the first successful handshake
        self._link_up = False             # a handshake has succeeded and nothing failed since
        self._threads = []             # type: List[threading.Thread]

    # -- lifecycle --

    def start(self) -> None:
        """Start the link threads and wait for the first successful PING.

        Opening lives in the reconnect thread so there is one code path for
        "connect", whether at startup or after a lost port. If the STM does not
        answer in time this raises, but the thread keeps trying in the background.
        """
        self._spawn(self._read_loop, "stm-reader")
        self._spawn(self._reconnect_loop, "stm-reconnect")
        grace = self._ping_deadline_s * 2 + self._stop_drain_s + 1.0
        if not self._ready.wait(grace):
            raise StmUnavailable("PING", "no PONG; retrying in the background")

    def close(self) -> None:
        self._closed.set()
        self._mark_down(notify=False)   # shutting down is not a link loss
        for thread in self._threads:
            thread.join(timeout=1.0)

    def _notify(self, up: bool) -> None:
        if self._on_link_change is not None:
            try:
                self._on_link_change(up)
            except Exception:
                LOG.exception("on_link_change failed")

    @property
    def available(self) -> bool:
        return self._available

    def _spawn(self, target: Callable[[], None], name: str) -> None:
        thread = threading.Thread(target=target, name=name, daemon=True)
        thread.start()
        self._threads.append(thread)

    def _open(self) -> None:
        try:
            ser = self._open_serial()
            ser.reset_input_buffer()
        except Exception as error:
            raise StmUnavailable("open", str(error))
        self._serial = ser
        self._available = True

    def _mark_down(self, notify: bool = True) -> None:
        was_up, self._link_up = self._link_up, False
        self._available = False
        ser, self._serial = self._serial, None
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass
        if was_up and notify:
            self._notify(False)

    def _handshake(self) -> None:
        self._command("PING", self._ping_deadline_s, expect=("PONG",))
        for verb, value in self._trims:
            if value is not None:
                self._command("%s %d" % (verb, value), self._ack_deadline_s)

    # -- threads --

    def _read_loop(self) -> None:
        while not self._closed.is_set():
            ser = self._serial
            if ser is None:
                self._closed.wait(0.05)
                continue
            try:
                raw = ser.readline()
            except Exception as error:
                LOG.warning("STM read failed (%s); link down", error)
                self._mark_down()
                continue
            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace").strip()
            if line:
                LOG.info("STM in: %s", line)
                _mirror(self._on_line, "STM< " + line)
                self._replies.put(line)

    def _reconnect_loop(self) -> None:
        """Open + handshake whenever there is no serial; first attempt is immediate."""
        while not self._closed.is_set():
            if self._serial is None:
                try:
                    self._open()
                    self._handshake()
                    self._link_up = True
                    LOG.info("STM link up")
                    self._notify(True)
                    self._ready.set()     # last, so start() cannot return before the hook ran
                except StmError as error:
                    LOG.warning("STM link attempt failed: %s", error)
                    self._mark_down()
            self._closed.wait(self._retry_delay_s)

    # -- wire --

    def _write(self, line: str) -> None:
        ser = self._serial
        if ser is None or not self._available:
            raise StmUnavailable(line, "STM unavailable")
        LOG.info("STM out: %s", line)
        _mirror(self._on_line, "STM> " + line)
        try:
            ser.write((line + "\n").encode("ascii"))
            ser.flush()
        except Exception as error:
            self._mark_down()
            raise StmUnavailable(line, str(error))

    def _write_quiet(self, line: str) -> None:
        try:
            self._write(line)
        except StmUnavailable:
            pass

    def _await(self, prefixes: Tuple[str, ...], deadline_s: float, command: str, honour_abort: bool = True) -> str:
        """The next reply starting with one of `prefixes`; other lines are logged and skipped."""
        end = time.monotonic() + deadline_s
        while True:
            if honour_abort and self._aborted.is_set():
                raise StmAborted(command, "stopped")
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise _NoReply()
            try:
                line = self._replies.get(timeout=min(0.05, remaining))
            except queue.Empty:
                continue
            if honour_abort and self._aborted.is_set():
                raise StmAborted(command, "stopped")   # stop() fired while we were blocked in get()
            if line.startswith(prefixes):
                return line
            LOG.info("STM (skipped while waiting for %s): %s", command, line)

    def _deadline(self, line: str) -> float:
        parts = line.split(" ")
        verb = parts[0]
        amount = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        if verb in ("FS", "BS", "FW", "BW"):
            return self._straight_deadline(amount)
        if verb in ("TL", "TR", "BL", "BR", "PL", "PR"):
            return self._turn_deadline_s
        if verb == "SEEK":                     # Task 2 (spec §5.2): by verb, never by the number
            return self._seek_deadline_s
        if verb == "ROUND":
            return self._route_deadline_s
        if verb == "HOME":
            return self._home_deadline_s
        return self._ack_deadline_s

    def _command(
        self,
        line: str,
        deadline_s: float,
        expect: Optional[Tuple[str, ...]] = None,
        motion: bool = False,
        abort: Optional[threading.Event] = None,
    ) -> str:
        if expect is None:
            expect = _reply_prefixes(line)
        with self._lock:
            if (abort is not None and abort.is_set()) or self._aborted.is_set():
                raise StmAborted(line, "stopped")      # a stop is in progress or the run was stopped while we queued
            self._write(line)
            try:
                if motion and self._completion == "DONE":
                    verb = _verb(line)
                    # A DONE that arrives without its ACK (e.g. DONE,SEEK,0 "at once") is accepted.
                    first = self._await(("ACK," + verb, "DONE," + verb, "ERR,"), self._ack_deadline_s, line)
                    if first.startswith("ERR,"):
                        raise StmError(line, first)
                    final = first if first.startswith("DONE,") else self._await(("DONE," + verb, "ERR,"), deadline_s, line)
                else:
                    final = self._await(expect, deadline_s, line)
            except _NoReply:
                LOG.warning("STM: no reply to %s within %.1fs", line, deadline_s)
                self._write_quiet("S")
                self._resync()
                raise StmError(line, "no reply")
            if final.startswith("ERR,"):
                raise StmError(line, final)
            return final

    def _resync(self) -> None:
        """Discard whatever is queued, then PING and discard until PONG. Caller holds the lock."""
        end = time.monotonic() + self._stop_drain_s
        while time.monotonic() < end:
            try:
                LOG.info("STM (drained): %s", self._replies.get(timeout=0.02))
            except queue.Empty:
                pass
        self._write_quiet("PING")
        try:
            self._await(("PONG",), self._ping_deadline_s, "PING", honour_abort=False)
        except _NoReply:
            LOG.warning("STM did not answer PING during resync")

    # -- StmDriver --

    def manual(self, token: str) -> None:
        line = encode_manual(token, self._manual_turn_deg)
        self._command(line, self._deadline(line), motion=is_motion(line))

    def manual_raw(self, line: str) -> None:
        # A passthrough line has no known verb on the STM side, so any ACK or ERR is its reply.
        self._command(line, self._ack_deadline_s, expect=("ACK,", "ERR,"))

    def raw(self, line: str, abort: Optional[threading.Event] = None) -> str:
        line = line.strip()
        if not line:
            raise ValueError("empty line")
        if is_motion(line):
            return self._command(line, self._deadline(line), motion=True, abort=abort)
        # Not a motion: PONG, RANGE,52, ACK,MA, ERR,UNKNOWN - the first line of any kind.
        return self._command(line, self._ping_deadline_s, expect=("",), abort=abort)

    def execute(self, instr: Instruction, abort: Optional[threading.Event] = None) -> None:
        line = encode_instruction(instr)
        self._command(line, self._deadline(line), motion=True, abort=abort)

    # -- Task 2 (Task 2 spec §3.1, §5.2) --

    def seek(self, cm: int, abort: Optional[threading.Event] = None) -> Optional[int]:
        line = encode_seek(cm)
        final = self._command(line, self._deadline(line), motion=True, abort=abort)
        travelled = parse_seek_distance(final)
        if travelled is None:
            LOG.warning("STM: %s reply carries no distance: %s", line, final)
        return travelled

    def round(self, obstacle: int, side: str, abort: Optional[threading.Event] = None) -> None:
        line = encode_round(obstacle, side)
        self._command(line, self._deadline(line), motion=True, abort=abort)

    def home(self, abort: Optional[threading.Event] = None) -> None:
        line = encode_home()
        self._command(line, self._deadline(line), motion=True, abort=abort)

    def range_cm(self, abort: Optional[threading.Event] = None) -> Optional[int]:
        """A data line, not a motion: awaited by its own prefix, and a missing or error
        reply is None with a log line - no stop, no resync."""
        with self._lock:
            if (abort is not None and abort.is_set()) or self._aborted.is_set():
                raise StmAborted(RANGE_LINE, "stopped")
            self._write(RANGE_LINE)
            try:
                reply = self._await((RANGE_LINE + ",", "ERR,"), self._ack_deadline_s, RANGE_LINE)
            except _NoReply:
                LOG.warning("STM: no reply to %s", RANGE_LINE)
                return None
        if reply.startswith("ERR,"):
            LOG.warning("STM: %s -> %s", RANGE_LINE, reply)
            return None
        return parse_range(reply)

    def stop(self) -> None:
        self._aborted.set()
        self._write_quiet("S")
        with self._lock:          # an in-flight command unwinds first
            self._resync()
            self._aborted.clear()
