"""Puts algorithm/ on sys.path so `import config` and `from pathfinding...` resolve under pytest."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
