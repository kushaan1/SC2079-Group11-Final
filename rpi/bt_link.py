"""The Bluetooth link to the tablet: /dev/rfcomm0 in raw mode, line framing,
a locked send, and a reconnect loop (spec §5.2).

`rfcomm watch` outside this program creates the device node when the tablet
connects and removes it when it leaves; this loop opens it whenever it exists.

POSIX-only modules (`select`, `tty`) are imported inside `run_forever` so the
module loads on Windows, where the framer and `send` are unit-tested.
"""

import logging
import os
import threading
import time
from typing import Callable, List, Optional

LOG = logging.getLogger(__name__)


class LineFramer:
    """Accumulate bytes; emit complete lines. A line may span several reads."""

    def __init__(self) -> None:
        self._buffer = b""

    def feed(self, data: bytes) -> List[str]:
        self._buffer += data
        lines = []  # type: List[str]
        while b"\n" in self._buffer:
            raw, self._buffer = self._buffer.split(b"\n", 1)
            if raw.endswith(b"\r"):
                raw = raw[:-1]
            if raw:
                lines.append(raw.decode("utf-8", errors="replace"))
        return lines

    def reset(self) -> None:
        self._buffer = b""


class BluetoothLink:
    def __init__(
        self,
        port: str,
        on_line: Callable[[str], None],
        on_reconnect: Optional[Callable[[], None]] = None,
        retry_delay_s: float = 3.0,
        tick_s: float = 0.5,
    ) -> None:
        self._port = port
        self._on_line = on_line
        self._on_reconnect = on_reconnect
        self._retry_delay_s = retry_delay_s
        self._tick_s = tick_s
        self._fd = None         # type: Optional[int]   # what send() writes to; None = link down
        self._device_fd = None  # type: Optional[int]   # what run_forever() opened; closed only there
        self._lock = threading.RLock()
        self._framer = LineFramer()
        self._stop = threading.Event()
        self._ever_connected = False

    @property
    def connected(self) -> bool:
        return self._fd is not None

    def send(self, line: str) -> bool:
        """Write one line. Never raises and never blocks: the device is opened
        non-blocking, so a tablet that vanished mid-run costs dropped lines, not a
        stalled run thread."""
        payload = (line + "\n").encode("utf-8")
        with self._lock:
            fd = self._fd
            if fd is None:
                LOG.info("BT not connected; dropped: %s", line)
                return False
            try:
                os.write(fd, payload)
            except BlockingIOError:
                LOG.warning("BT output buffer full; dropped: %s", line)
                return False
            except OSError as error:
                LOG.warning("BT write failed (%s); link down", error)
                self._fd = None     # closing is the reader thread's job (it may be in select on it)
                return False
        LOG.info("BT out: %s", line)
        return True

    def _attach(self, fd: int) -> None:
        with self._lock:
            self._framer.reset()
            self._device_fd = fd
            self._fd = fd
        LOG.info("BT connected on %s", self._port)
        if self._ever_connected and self._on_reconnect is not None:
            self._on_reconnect()
        self._ever_connected = True

    def _mark_down(self) -> None:
        with self._lock:
            fd, self._device_fd = self._device_fd, None
            self._fd = None
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

    def run_forever(self) -> None:
        """Open the device whenever it exists, read lines, reopen after a drop."""
        import select  # POSIX fd select; see module docstring
        import tty

        while not self._stop.is_set():
            if not os.path.exists(self._port):
                self._stop.wait(self._retry_delay_s)
                continue
            try:
                fd = os.open(self._port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
                tty.setraw(fd)   # no echo, no CR/LF translation by the line discipline
            except OSError as error:
                LOG.warning("BT open failed (%s); retrying", error)
                self._stop.wait(self._retry_delay_s)
                continue

            self._attach(fd)
            try:
                while not self._stop.is_set():
                    readable, _, _ = select.select([fd], [], [], self._tick_s)
                    if not readable:
                        continue
                    try:
                        data = os.read(fd, 1024)
                    except BlockingIOError:
                        continue    # spurious wake-up on a non-blocking fd
                    if not data:
                        break   # EOF: the tablet went away
                    LOG.debug("BT in: %r", data)
                    for line in self._framer.feed(data):
                        LOG.info("BT in: %s", line)
                        try:
                            self._on_line(line)
                        except Exception:   # a handler bug must not drop the link
                            LOG.exception("handler failed on %r", line)
            except OSError as error:
                LOG.warning("BT read failed (%s)", error)
            finally:
                self._mark_down()
                LOG.info("BT disconnected")
            self._stop.wait(self._retry_delay_s)

    def close(self) -> None:
        self._stop.set()
        self._mark_down()
