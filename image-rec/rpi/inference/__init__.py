"""Lightweight local inference components."""

from .arrow_consensus import ArrowConsensus
from .tflite_detector import TFLiteYoloDetector

__all__ = ["ArrowConsensus", "TFLiteYoloDetector"]
