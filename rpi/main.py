"""Wiring and the Bluetooth loop. The only module that knows about every other."""

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler
from types import SimpleNamespace
from typing import List, Optional

from rpi import config
from rpi.bt_link import BluetoothLink
from rpi.dispatcher import Dispatcher
from rpi.run import RunController, RunState
from rpi.stm_driver import FakeStmDriver, SerialStmDriver, StmDriver, StmUnavailable

LOG = logging.getLogger("rpi")


def configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s", "%H:%M:%S")
    try:
        file_handler = RotatingFileHandler(
            config.LOG_FILE, maxBytes=config.LOG_MAX_BYTES, backupCount=config.LOG_BACKUP_COUNT,
        )
    except OSError:
        file_handler = RotatingFileHandler(
            "rpi.log", maxBytes=config.LOG_MAX_BYTES, backupCount=config.LOG_BACKUP_COUNT,
        )
    for handler in (file_handler, logging.StreamHandler(sys.stdout)):
        handler.setFormatter(formatter)
        root.addHandler(handler)


def make_stm(fake: bool) -> StmDriver:
    if fake:
        return FakeStmDriver(turn_deg=config.MANUAL_TURN_DEG)
    return SerialStmDriver(
        config.STM_PORT, config.STM_BAUD,
        completion=config.STM_COMPLETION,
        ack_deadline_s=config.STM_ACK_DEADLINE_S,
        turn_deadline_s=config.STM_TURN_DEADLINE_S,
        straight_deadline=config.stm_straight_deadline_s,
        ping_deadline_s=config.STM_PING_DEADLINE_S,
        stop_drain_s=config.STM_STOP_DRAIN_S,
        retry_delay_s=config.RETRY_DELAY_S,
        motor_a=config.MOTOR_A_PCT, motor_b=config.MOTOR_B_PCT, steer_steps=config.STEER_STEPS,
        manual_turn_deg=config.MANUAL_TURN_DEG,
    )


def build(fake_stm: bool, fake_camera: bool) -> SimpleNamespace:
    """Construct everything. Opens nothing: links open in start()/run_forever()."""
    stm = make_stm(fake_stm)
    state = RunState()
    wiring = SimpleNamespace(stm=stm, state=state, fake_camera=fake_camera)

    link = BluetoothLink(config.BT_PORT, on_line=lambda line: wiring.dispatcher.handle(line),
                         retry_delay_s=config.RETRY_DELAY_S)
    controller = RunController(stm, link.send)
    dispatcher = Dispatcher(link.send, stm, controller)

    wiring.link = link
    wiring.controller = controller
    wiring.dispatcher = dispatcher
    return wiring


def parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="rpi", description="Group 11 Raspberry Pi program")
    parser.add_argument("--fake-stm", action="store_true", help="time moves instead of driving the STM")
    parser.add_argument("--fake-camera", action="store_true", help="return a fixture JPEG instead of the camera")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    configure_logging()
    wiring = build(args.fake_stm, args.fake_camera)
    LOG.info("starting; fake_stm=%s fake_camera=%s bt=%s stm=%s",
             args.fake_stm, args.fake_camera, config.BT_PORT, config.STM_PORT)
    try:
        wiring.stm.start()
    except StmUnavailable as error:
        LOG.warning("STM not ready (%s); continuing, the driver keeps retrying", error)
    try:
        wiring.link.run_forever()
    except KeyboardInterrupt:
        LOG.info("interrupted")
        wiring.controller.stop()
        wiring.stm.stop()
    finally:
        wiring.link.close()
        wiring.stm.close()
    return 0
