"""The only module that knows the STM's wire format (spec §3.2, §5.5).

`StmDriver` is what the rest of the program codes against. `SerialStmDriver`
talks to the real board; `FakeStmDriver` completes moves on a timer so the
whole pipeline runs on a laptop.
"""

import logging
import threading
import time
from abc import ABC, abstractmethod
from typing import List, Optional

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
_MOTION_VERBS = ("FW", "BW", "FS", "TL", "TR", "BL", "BR", "PL", "PR")


def encode_instruction(instr: Instruction) -> str:
    if isinstance(instr, Straight):
        verb = "FW" if instr.move == "FORWARD" else "BW"
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
    def execute(self, instr: Instruction, abort: Optional[threading.Event] = None) -> None:
        """A planner instruction. Returns when the STM says the motion is done.
        Raises StmAborted without sending anything if `abort` is already set."""

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

    def __init__(self, straight_cm_per_s: float = 30.0, turn_s: float = 3.0, turn_deg: int = 45) -> None:
        self._cm_per_s = straight_cm_per_s
        self._turn_s = turn_s
        self._turn_deg = turn_deg
        self._abort = threading.Event()
        self.sent = []  # type: List[str]

    def start(self) -> None:
        LOG.info("fake STM ready")

    @property
    def available(self) -> bool:
        return True

    def manual(self, token: str) -> None:
        self.sent.append(encode_manual(token, self._turn_deg))

    def manual_raw(self, line: str) -> None:
        self.sent.append(line)

    def execute(self, instr: Instruction, abort: Optional[threading.Event] = None) -> None:
        line = encode_instruction(instr)
        if abort is not None and abort.is_set():
            raise StmAborted(line, "stopped")
        self.sent.append(line)
        if isinstance(instr, Straight):
            duration = instr.cm / self._cm_per_s if self._cm_per_s > 0 else 0.0
        else:
            duration = self._turn_s * (instr.degrees / 90.0)
        # Only a stop() that arrives DURING this move aborts it. A stale flag from an
        # earlier stop is cleared here; the pre-set case is the run's `abort` event's job.
        self._abort.clear()
        if self._abort.wait(duration):
            raise StmAborted(line, "stopped")

    def stop(self) -> None:
        self.sent.append("S")
        self._abort.set()

    def close(self) -> None:
        pass
