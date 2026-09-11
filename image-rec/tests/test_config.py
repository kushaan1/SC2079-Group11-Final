import pytest

from vision.config import PCConfig, RPiConfig


def test_pc_config_reads_environment_mapping():
    config = PCConfig.from_env(
        {
            "VISION_PC_PORT": "4100",
            "VISION_PC_CONFIDENCE": "0.7",
            "VISION_NEAREST_HEIGHT_TOLERANCE": "0.15",
        }
    )
    assert config.port == 4100
    assert config.confidence_threshold == 0.7
    assert config.nearest_height_tolerance == 0.15


def test_rpi_consensus_must_fit_window():
    with pytest.raises(ValueError, match="consensus"):
        RPiConfig.from_env(
            {"VISION_CONSENSUS_REQUIRED": "4", "VISION_CONSENSUS_WINDOW": "3"}
        )


@pytest.mark.parametrize(
    "key",
    ["VISION_HTTP_TIMEOUT_SECONDS", "VISION_SERIAL_BAUD", "VISION_SERIAL_TIMEOUT_SECONDS"],
)
def test_rpi_transport_values_must_be_positive(key):
    with pytest.raises(ValueError, match="positive"):
        RPiConfig.from_env({key: "0"})
