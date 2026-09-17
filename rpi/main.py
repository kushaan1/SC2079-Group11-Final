"""Wiring and the Bluetooth loop. The only module that knows about every other."""

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler
from types import SimpleNamespace
from typing import List, Optional

from rpi import config, protocol
from rpi.bt_link import BluetoothLink
from rpi.camera import Camera, CameraError, FakeCamera, PiCameraLegacy
from rpi.dispatcher import Dispatcher
from rpi.planner_client import PlannerClient
from rpi.protocol import ImageRec
from rpi.run import RunController, RunState, Task1Run
from rpi.stm_driver import FakeStmDriver, SerialStmDriver, StmDriver, StmUnavailable
from rpi.vision_client import VisionClient
from rpi.vision_worker import VisionWorker

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


def make_stm(fake: bool, on_link_change=None) -> StmDriver:
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
        on_link_change=on_link_change,
    )


def make_camera(fake: bool) -> Camera:
    if fake:
        return FakeCamera()
    return PiCameraLegacy(config.CAMERA_WIDTH, config.CAMERA_HEIGHT, config.CAMERA_ROTATION)


def replay(send, vision: VisionWorker, state: RunState, controller: RunController) -> None:
    """After a Bluetooth reconnect: every target so far, the latest pose, then a note (spec §6.1 step 8)."""
    for result in vision.results():
        if result.status == "target" and result.competition_id is not None:
            send(protocol.target(result.obstacle_id, result.competition_id))
    if state.last_robot_line:
        send(state.last_robot_line)
    send(protocol.msg("Reconnected - run in progress" if controller.active() else "Reconnected"))


def build(fake_stm: bool, fake_camera: bool) -> SimpleNamespace:
    """Construct everything. Opens nothing: links open in start()/run_forever()."""
    state = RunState()
    wiring = SimpleNamespace(state=state)

    link = BluetoothLink(
        config.BT_PORT,
        on_line=lambda line: wiring.dispatcher.handle(line),
        on_reconnect=lambda: replay(link.send, wiring.vision, state, wiring.controller),
        retry_delay_s=config.RETRY_DELAY_S,
    )
    stm = make_stm(fake_stm, on_link_change=lambda up: link.send(
        protocol.msg("STM connected" if up else "STM disconnected")))
    camera = make_camera(fake_camera)
    planner = PlannerClient(config.PLANNER_URL, config.PLANNER_TIMEOUT_S, allow_stub=config.ALLOW_STUB_PLANNER)
    wiring.stm, wiring.camera, wiring.planner = stm, camera, planner

    vision = VisionWorker(VisionClient(config.VISION_URL, config.VISION_TIMEOUT_S), link.send, config.CAPTURE_FRAMES)
    controller = RunController(stm, link.send)

    def driving():
        return dict(stm=stm, camera=camera, vision=vision, send=link.send, state=state,
                    radii=config.TURN_RADIUS_CM, settle_s=config.CAPTURE_SETTLE_S, frames=config.CAPTURE_FRAMES)

    def task1_factory(message):
        return Task1Run(message, planner, config.VISION_DRAIN_TIMEOUT_S, config.STRATEGY_FALLBACK, **driving())

    dispatcher = Dispatcher(link.send, stm, controller, task1_factory=task1_factory)

    wiring.link = link
    wiring.vision = vision
    wiring.controller = controller
    wiring.dispatcher = dispatcher
    wiring.driving = driving
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
    wiring.vision.start()
    try:
        wiring.camera.start()
    except CameraError as error:
        LOG.warning("camera not ready (%s); captures will be reported as failed", error)
    try:
        wiring.link.run_forever()
    except KeyboardInterrupt:
        LOG.info("interrupted")
        wiring.controller.stop()
        wiring.stm.stop()
    finally:
        wiring.link.close()
        wiring.vision.close()
        wiring.camera.close()
        wiring.stm.close()
    return 0
