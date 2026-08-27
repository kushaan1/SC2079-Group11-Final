import pytest

from rpi.comms.pc_client import PCDetectionClient


def test_accepts_versioned_recovery_statuses():
    PCDetectionClient._validate_payload(
        {
            "schema_version": "1.0",
            "status": "bullseye",
            "detection": {"competition_id": None},
        }
    )


def test_rejects_wrong_schema_or_target_id():
    with pytest.raises(ValueError, match="schema version"):
        PCDetectionClient._validate_payload({"schema_version": "2.0", "status": "target"})
    with pytest.raises(ValueError, match="11-40"):
        PCDetectionClient._validate_payload(
            {
                "schema_version": "1.0",
                "status": "target",
                "detection": {"competition_id": 45},
            }
        )


def test_rejects_inconsistent_status_and_detection():
    with pytest.raises(ValueError, match="requires a detection"):
        PCDetectionClient._validate_payload(
            {"schema_version": "1.0", "status": "target", "detection": None}
        )
    with pytest.raises(ValueError, match="cannot contain"):
        PCDetectionClient._validate_payload(
            {
                "schema_version": "1.0",
                "status": "bullseye",
                "detection": {"competition_id": 39},
            }
        )
