"""Every tunable the program reads, with RPI_* environment overrides.

Read once at import. No other module reads the environment. Spec §5.1.
"""

import os
from typing import Dict, Optional


def _text(name: str, default: str) -> str:
    return os.environ.get("RPI_" + name, default)


def _number(name: str, default: float) -> float:
    raw = os.environ.get("RPI_" + name)
    return float(raw) if raw not in (None, "") else default


def _optional_int(name: str, default: Optional[int]) -> Optional[int]:
    raw = os.environ.get("RPI_" + name)
    if raw is None:
        return default
    if raw.strip() == "":
        return None
    return int(raw)


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get("RPI_" + name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _radii() -> Dict[str, int]:
    # The planner's config.TURN_RADIUS_CM, which these must track (spec §3.3).
    defaults = {"FORWARD_LEFT": 39, "FORWARD_RIGHT": 40, "BACKWARD_LEFT": 37, "BACKWARD_RIGHT": 39}
    return {kind: int(_number("TURN_RADIUS_" + kind, value)) for kind, value in defaults.items()}


# --- links ------------------------------------------------------------------
BT_PORT = _text("BT_PORT", "/dev/rfcomm0")
STM_PORT = _text("STM_PORT", "/dev/ttyACM0")
STM_BAUD = int(_number("STM_BAUD", 115200))
RETRY_DELAY_S = _number("RETRY_DELAY_S", 3.0)       # before reopening a lost device

# --- servers on the laptop; no defaults, they change every session ----------
PLANNER_URL = _text("PLANNER_URL", "").rstrip("/")
VISION_URL = _text("VISION_URL", "").rstrip("/")
PLANNER_TIMEOUT_S = _number("PLANNER_TIMEOUT_S", 5.0)
VISION_TIMEOUT_S = _number("VISION_TIMEOUT_S", 10.0)   # per frame
VISION_DRAIN_TIMEOUT_S = _number("VISION_DRAIN_TIMEOUT_S", 15.0)
ALLOW_STUB_PLANNER = _flag("ALLOW_STUB_PLANNER", False)
STRATEGY_FALLBACK = _text("STRATEGY_FALLBACK", "optimal")   # what turnInPlace maps to

# --- STM ----------------------------------------------------------------------
# "DONE": ACK arrives on receipt and a DONE,<verb> line when the motion ends - what the
# STM firmware does (spec §3.2 S3, confirmed 2026-09-17).
# "ACK": the ACK line itself arrives when the motion ends; kept for an older firmware.
STM_COMPLETION = _text("STM_COMPLETION", "DONE").upper()
STM_ACK_DEADLINE_S = _number("STM_ACK_DEADLINE_S", 1.0)
STM_TURN_DEADLINE_S = _number("STM_TURN_DEADLINE_S", 10.0)
STM_PING_DEADLINE_S = _number("STM_PING_DEADLINE_S", 2.0)
STM_STOP_DRAIN_S = _number("STM_STOP_DRAIN_S", 0.5)
# Mirror every serial line both ways to the tablet as "STM> ..." / "STM< ..." lines. The
# app shows them only in its raw Bluetooth log (they decode as Unknown); off with 0.
STM_TO_TABLET = _flag("STM_TO_TABLET", True)
MANUAL_TURN_DEG = int(_number("MANUAL_TURN_DEG", 45))
MOTOR_A_PCT = _optional_int("MOTOR_A_PCT", None)     # None = do not send at startup
MOTOR_B_PCT = _optional_int("MOTOR_B_PCT", None)
STEER_STEPS = _optional_int("STEER_STEPS", None)


def stm_straight_deadline_s(cm: int) -> float:
    """How long to wait for a straight of `cm` to be acknowledged (spec §5.1)."""
    return cm / 10.0 + 5.0


# --- driving ------------------------------------------------------------------
TURN_RADIUS_CM = _radii()

# --- camera -------------------------------------------------------------------
CAPTURE_SETTLE_S = _number("CAPTURE_SETTLE_S", 0.3)
CAPTURE_FRAMES = int(_number("CAPTURE_FRAMES", 3))
CAMERA_WIDTH = int(_number("CAMERA_WIDTH", 640))
CAMERA_HEIGHT = int(_number("CAMERA_HEIGHT", 480))
CAMERA_ROTATION = int(_number("CAMERA_ROTATION", 0))

# --- logging ------------------------------------------------------------------
LOG_FILE = _text("LOG_FILE", "/home/pi/rpi.log")
LOG_MAX_BYTES = 512 * 1024
LOG_BACKUP_COUNT = 3
