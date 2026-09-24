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
    # Measured on this chassis 2026-09-18 (algorithm/config.py, same date); only affects the
    # tablet's dead-reckoned ROBOT marker between segments (spec §5.10), since each segment snaps
    # to the planner's real end pose. Was 39/40/37/39 (prior-year placeholders) until 2026-09-25.
    defaults = {"FORWARD_LEFT": 42, "FORWARD_RIGHT": 56, "BACKWARD_LEFT": 41, "BACKWARD_RIGHT": 55}
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
STM_SEEK_DEADLINE_S = _number("STM_SEEK_DEADLINE_S", 20.0)     # Task 2 spec §3.1
STM_ROUTE_DEADLINE_S = _number("STM_ROUTE_DEADLINE_S", 25.0)
STM_HOME_DEADLINE_S = _number("STM_HOME_DEADLINE_S", 40.0)
STM_PING_DEADLINE_S = _number("STM_PING_DEADLINE_S", 2.0)
STM_STOP_DRAIN_S = _number("STM_STOP_DRAIN_S", 0.5)
# Slowest straight speed the STM is expected to manage, for the DONE deadline below. Time an
# `FS 100` in the console and set this a little under 100 / that.
STM_STRAIGHT_CM_PER_S = _number("STM_STRAIGHT_CM_PER_S", 10.0)
# Mirror every serial line both ways to the tablet as "STM> ..." / "STM< ..." lines. The
# app shows them only in its raw Bluetooth log (they decode as Unknown); off with 0.
STM_TO_TABLET = _flag("STM_TO_TABLET", True)
MANUAL_TURN_DEG = int(_number("MANUAL_TURN_DEG", 45))
MOTOR_A_PCT = _optional_int("MOTOR_A_PCT", None)     # None = do not send at startup
MOTOR_B_PCT = _optional_int("MOTOR_B_PCT", None)
STEER_STEPS = _optional_int("STEER_STEPS", None)


def stm_straight_deadline_s(cm: int) -> float:
    """How long to wait for a straight of `cm` to be acknowledged (spec §5.1)."""
    return cm / STM_STRAIGHT_CM_PER_S + 5.0


# --- driving ------------------------------------------------------------------
TURN_RADIUS_CM = _radii()

# --- camera -------------------------------------------------------------------
CAPTURE_SETTLE_S = _number("CAPTURE_SETTLE_S", 0.3)
CAPTURE_FRAMES = int(_number("CAPTURE_FRAMES", 3))
CAMERA_WIDTH = int(_number("CAMERA_WIDTH", 640))
CAMERA_HEIGHT = int(_number("CAMERA_HEIGHT", 480))
CAMERA_ROTATION = int(_number("CAMERA_ROTATION", 0))

# --- Task 2 arrows (Task 2 spec §5.3) -------------------------------------------
_MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
# Defaults to the on-Pi model: Jerick's image-rec architecture (README's diagram,
# training/README's deployment table) builds no PC-server path for Task 2 arrows at all -
# the PC server only ever loads the Task 1 classifier. Confirm this with him alongside
# asking for best_arrows.tflite + arrow-labels.json; "http" remains available as a fallback.
ARROW_SOURCE = _text("ARROW_SOURCE", "tflite").strip().lower()    # http | tflite
ARROW_HTTP_TIMEOUT_S = _number("ARROW_HTTP_TIMEOUT_S", 2.0)     # per frame; the arrow source's own client
ARROW_MODEL_PATH = _text("ARROW_MODEL_PATH", os.path.join(_MODELS_DIR, "best_arrows.tflite"))
ARROW_LABELS_PATH = _text("ARROW_LABELS_PATH", os.path.join(_MODELS_DIR, "arrow-labels.json"))
ARROW_MIN_CONFIDENCE = _number("ARROW_MIN_CONFIDENCE", 0.75)
ARROW_REQUIRED = int(_number("ARROW_REQUIRED", 3))               # the vote: agreeing frames...
ARROW_WINDOW = int(_number("ARROW_WINDOW", 5))                   # ...out of the last N
ARROW_ATTEMPT_S = _number("ARROW_ATTEMPT_S", 8.0)                # one read attempt before a nudge
ARROW_BUDGET_S = _number("ARROW_BUDGET_S", 45.0)                 # all attempts for one arrow
ARROW_NUDGE_CM = int(_number("ARROW_NUDGE_CM", 10))              # the BW (or FW) between attempts
T2_STOP1_CM = int(_number("T2_STOP1_CM", 30))                    # the seek thresholds: where the
T2_STOP2_CM = int(_number("T2_STOP2_CM", 30))                    # arrow is read from
# [RULE DELTA Task 2 spec §0 #1] Obstacle 2's length is disclosed only after the 2-minute prep,
# right before the run - never a value chosen before competition day. Only read if/when the
# STM team's ROUND 2 takes a length argument (spec §3.1, §5.2 open item); unset by default.
T2_OBSTACLE2_LENGTH_CM = _optional_int("T2_OBSTACLE2_LENGTH_CM", None)

# --- logging ------------------------------------------------------------------
LOG_FILE = _text("LOG_FILE", "/home/pi/rpi.log")
LOG_MAX_BYTES = 512 * 1024
LOG_BACKUP_COUNT = 3
