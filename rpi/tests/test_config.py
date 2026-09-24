import importlib

import rpi.config as config


def _reload(monkeypatch, **env):
    for name, value in env.items():
        monkeypatch.setenv("RPI_" + name, value)
    return importlib.reload(config)


def test_defaults():
    cfg = importlib.reload(config)
    assert cfg.BT_PORT == "/dev/rfcomm0"
    assert cfg.STM_PORT == "/dev/ttyACM0"
    assert cfg.STM_BAUD == 115200
    assert cfg.PLANNER_URL == ""
    assert cfg.VISION_URL == ""
    assert cfg.STM_COMPLETION == "DONE"
    assert cfg.STM_TO_TABLET is True
    assert cfg.STM_STRAIGHT_CM_PER_S == 10.0
    assert cfg.MOTOR_A_PCT is None
    assert cfg.MANUAL_TURN_DEG == 45
    assert cfg.CAPTURE_FRAMES == 3
    assert cfg.TURN_RADIUS_CM == {
        "FORWARD_LEFT": 42, "FORWARD_RIGHT": 56, "BACKWARD_LEFT": 41, "BACKWARD_RIGHT": 55,
    }
    assert (cfg.STM_SEEK_DEADLINE_S, cfg.STM_ROUTE_DEADLINE_S, cfg.STM_HOME_DEADLINE_S) == (20.0, 25.0, 40.0)
    assert cfg.ARROW_SOURCE == "tflite"
    assert cfg.ARROW_HTTP_TIMEOUT_S == 2.0
    assert cfg.ARROW_MODEL_PATH.replace("\\", "/").endswith("rpi/models/best_arrows.tflite")
    assert cfg.ARROW_LABELS_PATH.replace("\\", "/").endswith("rpi/models/arrow-labels.json")
    assert cfg.ARROW_MIN_CONFIDENCE == 0.75
    assert (cfg.ARROW_REQUIRED, cfg.ARROW_WINDOW) == (3, 5)
    assert (cfg.ARROW_ATTEMPT_S, cfg.ARROW_BUDGET_S) == (8.0, 45.0)
    assert cfg.ARROW_NUDGE_CM == 10
    assert (cfg.T2_STOP1_CM, cfg.T2_STOP2_CM) == (30, 30)
    assert cfg.T2_OBSTACLE2_LENGTH_CM is None


def test_environment_overrides(monkeypatch):
    cfg = _reload(
        monkeypatch,
        PLANNER_URL="http://10.0.0.2:5000/",
        STM_COMPLETION="ack",
        MOTOR_A_PCT="55",
        TURN_RADIUS_FORWARD_LEFT="31",
        ALLOW_STUB_PLANNER="true",
        STM_TO_TABLET="0",
        ARROW_SOURCE="HTTP",
        ARROW_REQUIRED="2",
        T2_STOP2_CM="35",
    )
    assert cfg.PLANNER_URL == "http://10.0.0.2:5000"      # trailing slash stripped
    assert cfg.STM_COMPLETION == "ACK"                     # upper-cased
    assert cfg.MOTOR_A_PCT == 55
    assert cfg.TURN_RADIUS_CM["FORWARD_LEFT"] == 31
    assert cfg.TURN_RADIUS_CM["FORWARD_RIGHT"] == 56
    assert cfg.ALLOW_STUB_PLANNER is True
    assert cfg.STM_TO_TABLET is False
    assert cfg.ARROW_SOURCE == "http"                       # lower-cased; overrides the tflite default
    assert cfg.ARROW_REQUIRED == 2
    assert cfg.T2_STOP2_CM == 35


def test_straight_deadline_scales_with_distance():
    assert config.stm_straight_deadline_s(30) == 8.0
    assert config.stm_straight_deadline_s(100) == 15.0


def test_straight_deadline_stretches_for_a_slower_straight(monkeypatch):
    cfg = _reload(monkeypatch, STM_STRAIGHT_CM_PER_S="5")
    assert cfg.stm_straight_deadline_s(100) == 25.0     # 20 s of driving plus the 5 s slack
    assert cfg.stm_straight_deadline_s(30) == 11.0
