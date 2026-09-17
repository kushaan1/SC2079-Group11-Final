"""Runs: the Task 1 executor, the A.5 face search, and the controller that
holds at most one of them (spec §5.11, §6).
"""

import logging
import threading
from typing import Callable, Optional

from rpi import protocol
from rpi.stm_driver import StmDriver

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
