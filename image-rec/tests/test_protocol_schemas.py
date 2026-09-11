import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from rpi.comms.android_bt import make_status_message


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "docs" / "protocols" / "schemas"


def load_schema(name):
    with (SCHEMA_DIR / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def test_stm_command_schema_is_valid_and_accepts_task2_macro():
    schema = load_schema("stm-command-v1.schema.json")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(
        {
            "version": "1.0",
            "message_id": "route-1",
            "action": "execute_right_route",
        }
    )


def test_android_status_message_matches_schema():
    schema = load_schema("status-message-v1.schema.json")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(
        make_status_message(
            "detection",
            {"object_id": "obstacle-1", "status": "target", "competition_id": 38},
        )
    )


@pytest.mark.parametrize(
    "command",
    [
        {"version": "1.0", "message_id": "x", "action": "stop", "speed": 1},
        {"version": "1.0", "message_id": "x", "action": "move", "distance_cm": 1},
        {
            "version": "1.0",
            "message_id": "x",
            "action": "turn_left",
            "distance_cm": 1,
            "angle_deg": 90,
            "speed": 1,
        },
    ],
)
def test_stm_command_schema_rejects_action_parameter_mismatches(command):
    validator = Draft202012Validator(load_schema("stm-command-v1.schema.json"))
    with pytest.raises(ValidationError):
        validator.validate(command)
