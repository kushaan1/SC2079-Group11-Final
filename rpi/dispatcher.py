"""Tablet message -> action. The table in spec §4.3."""

import logging
from typing import Callable, Optional

from rpi import protocol
from rpi.protocol import (
    Add, BeginFastest, Face, FaceSearch, ImageRec, Manual, MoveRobot, SendArena, Sub,
)
from rpi.run import BaseRun, RunController
from rpi.stm_driver import StmDriver, StmError, StmUnavailable

LOG = logging.getLogger(__name__)

RunFactory = Callable[[object], BaseRun]
BUSY = "Run in progress - STOP first"


class Dispatcher:
    def __init__(
        self,
        send: Callable[[str], None],
        stm: StmDriver,
        controller: RunController,
        task1_factory: Optional[RunFactory] = None,
        face_search_factory: Optional[RunFactory] = None,
    ) -> None:
        self._send = send
        self._stm = stm
        self._controller = controller
        self._task1_factory = task1_factory
        self._face_search_factory = face_search_factory

    def handle(self, line: str) -> None:
        message = protocol.parse(line)

        if isinstance(message, Manual):
            if message.token == "s":
                if self._controller.stop():
                    return            # the run thread sends MSG,Stopped
                self._manual("s")
                return
            if self._controller.active():
                self._send(protocol.msg(BUSY))
                return
            self._manual(message.token)
            return

        if isinstance(message, (Add, Sub, Face, MoveRobot, SendArena)):
            LOG.info("arena message noted, not acted on: %s", line.strip())
            return

        if isinstance(message, ImageRec):
            self._start("imageRec", self._task1_factory, message)
            return

        if isinstance(message, FaceSearch):
            self._start("faceSearch", self._face_search_factory, message)
            return

        if isinstance(message, BeginFastest):
            if self._controller.active():
                self._send(protocol.msg(BUSY))
                return
            try:
                self._stm.manual_raw("beginFastest")
            except StmUnavailable:
                self._send(protocol.msg("STM unavailable"))
            except StmError as error:
                self._send(protocol.msg("STM error: %s" % error.reply))
            return

        self._send(protocol.msg("Unknown command: %s" % line.strip()))

    def _manual(self, token: str) -> None:
        try:
            self._stm.manual(token)
        except StmUnavailable:
            self._send(protocol.msg("STM unavailable"))
        except StmError as error:
            self._send(protocol.msg("STM error: %s" % error.reply))

    def _start(self, name: str, factory: Optional[RunFactory], message: object) -> None:
        if factory is None:
            self._send(protocol.msg("%s not available in this build" % name))
            return
        if self._controller.active():
            self._send(protocol.msg(BUSY))
            return
        if not self._controller.start(factory(message)):
            self._send(protocol.msg(BUSY))
