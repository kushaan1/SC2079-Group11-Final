from test1_runner_rpi import android_detection_payload


def test_android_detection_payload_flattens_pc_result():
    result = {
        "schema_version": "1.0",
        "object_id": "obstacle-3",
        "status": "target",
        "detection": {"competition_id": 39, "label": "Left Arrow"},
        "detections": [],
    }

    assert android_detection_payload(result) == {
        "object_id": "obstacle-3",
        "status": "target",
        "competition_id": 39,
    }


def test_android_detection_payload_uses_null_id_for_no_detection():
    assert android_detection_payload(
        {"object_id": "obstacle-1", "status": "no_detection", "detection": None}
    ) == {
        "object_id": "obstacle-1",
        "status": "no_detection",
        "competition_id": None,
    }
