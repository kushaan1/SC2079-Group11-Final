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
    assert cfg.MOTOR_A_PCT is None
    assert cfg.MANUAL_TURN_DEG == 45
    assert cfg.CAPTURE_FRAMES == 3
    assert cfg.TURN_RADIUS_CM == {
        "FORWARD_LEFT": 39, "FORWARD_RIGHT": 40, "BACKWARD_LEFT": 37, "BACKWARD_RIGHT": 39,
    }


def test_environment_overrides(monkeypatch):
    cfg = _reload(
        monkeypatch,
        PLANNER_URL="http://10.0.0.2:5000/",
        STM_COMPLETION="ack",
        MOTOR_A_PCT="55",
        TURN_RADIUS_FORWARD_LEFT="31",
        ALLOW_STUB_PLANNER="true",
    )
    assert cfg.PLANNER_URL == "http://10.0.0.2:5000"      # trailing slash stripped
    assert cfg.STM_COMPLETION == "ACK"                     # upper-cased
    assert cfg.MOTOR_A_PCT == 55
    assert cfg.TURN_RADIUS_CM["FORWARD_LEFT"] == 31
    assert cfg.TURN_RADIUS_CM["FORWARD_RIGHT"] == 40
    assert cfg.ALLOW_STUB_PLANNER is True


def test_straight_deadline_scales_with_distance():
    assert config.stm_straight_deadline_s(30) == 8.0
    assert config.stm_straight_deadline_s(100) == 15.0
