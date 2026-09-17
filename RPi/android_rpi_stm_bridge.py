#android_rpi_stm_bridge QUIET V2
#!/usr/bin/env python3
import logging
import os
import select
import serial
import sys
import time
import tty
from logging.handlers import RotatingFileHandler

STM_PORT = "/dev/ttyACM0"
STM_BAUD = 115200
BT_PORT = "/dev/rfcomm0"
LOG_FILE = "/home/pi/scripts/android_rpi_stm_bridge.log"
LOG_MAX_BYTES = 512 * 1024
LOG_BACKUP_COUNT = 3
STM_REPLY_TIMEOUT = 2
RETRY_DELAY = 3


def configure_logging():
    logger = logging.getLogger("android_rpi_stm_bridge")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


LOG = configure_logging()


def bt_write_line(fd, text):
    outgoing = (text + "\r\n").encode("utf-8")
    LOG.info("BT raw out: %r", outgoing)
    os.write(fd, outgoing)


def read_stm_reply(stm):
    raw_reply = stm.readline()
    LOG.info("STM raw in: %r", raw_reply)

    time.sleep(0.05)
    extra_count = stm.in_waiting
    if extra_count:
        extra = stm.read(extra_count)
        LOG.warning("STM extra bytes after reply: %r", extra)

    if not raw_reply:
        return "ERROR,STM_TIMEOUT"

    return raw_reply.decode("utf-8", errors="replace").strip()


def main():
    if not os.path.exists(BT_PORT):
        raise RuntimeError(f"Bluetooth RFCOMM device is missing: {BT_PORT}")

    if not os.path.exists(STM_PORT):
        raise RuntimeError(f"STM USB serial device is missing: {STM_PORT}")

    LOG.info(
        "Opening STM serial: port=%s baud=%d timeout=%s",
        STM_PORT,
        STM_BAUD,
        STM_REPLY_TIMEOUT,
    )

    with serial.Serial(STM_PORT, STM_BAUD, timeout=STM_REPLY_TIMEOUT) as stm:
        stm.reset_input_buffer()
        LOG.info("STM serial opened; stale STM input buffer cleared")

        with open(BT_PORT, "r+b", buffering=0) as bt:
            tty.setraw(bt.fileno())
            LOG.info("Bridge ready: %s <-> %s", BT_PORT, STM_PORT)
            pending = b""

            while True:
                readable, _, _ = select.select([bt], [], [], 0.5)
                if not readable:
                    continue

                data = os.read(bt.fileno(), 256)
                if not data:
                    return

                LOG.info("BT raw in: %r", data)
                pending += data

                while b"\r" in pending or b"\n" in pending:
                    endings = [
                        i
                        for i in (pending.find(b"\r"), pending.find(b"\n"))
                        if i >= 0
                    ]
                    end = min(endings)
                    raw_command = pending[:end]
                    pending = pending[end + 1:].lstrip(b"\r\n")

                    command = raw_command.decode("utf-8", errors="replace").strip().upper()
                    if not command:
                        continue

                    stm_command = (command + "\r\n").encode("utf-8")
                    LOG.info("Parsed Android command: %r", command)
                    LOG.info("STM raw out: %r", stm_command)

                    stm.reset_input_buffer()
                    stm.write(stm_command)
                    stm.flush()

                    reply = read_stm_reply(stm)
                    LOG.info("STM -> Android: %s", reply)
                    bt_write_line(bt.fileno(), reply)


if __name__ == "__main__":
    LOG.info("Bridge process started")

    while True:
        try:
            main()
        except KeyboardInterrupt:
            LOG.info("Bridge stopped by keyboard interrupt")
            sys.exit(0)
        except Exception as error:
            LOG.warning("Bridge unavailable: %s", error)

        time.sleep(RETRY_DELAY)
