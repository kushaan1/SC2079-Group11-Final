"""Shared contracts and configuration for the SC2079 vision subsystem."""

from .contracts import BoundingBox, Detection, DetectionResult

__all__ = ["BoundingBox", "Detection", "DetectionResult"]
__version__ = "0.1.0"
