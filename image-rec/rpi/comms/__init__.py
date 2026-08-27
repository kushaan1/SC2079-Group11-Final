"""Narrow communication adapters used by the Raspberry Pi runners."""

from .pc_client import PCDetectionClient
from .stm_serial import SerialJsonTransport

__all__ = ["PCDetectionClient", "SerialJsonTransport"]
