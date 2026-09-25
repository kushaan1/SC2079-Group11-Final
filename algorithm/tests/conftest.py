"""Puts algorithm/ on sys.path so `import config` and `from pathfinding...` resolve under pytest."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import config


def pytest_configure(config):  # noqa: A002 - pytest fixes this name
    config.addinivalue_line(
        "markers", "diagonals: run with the experimental diagonal headings switched on"
    )
    config.addinivalue_line(
        "markers", "pivots: run with the experimental turn-on-the-spot pivots switched on"
    )


@pytest.fixture(autouse=True)
def four_headings(monkeypatch, request):
    """
    Pin every test to four headings and no pivots, unless it asks for an experiment by marker.

    The pin is for reproducibility and speed, NOT because the service ships that planner:
    `config.py` has shipped `DIAGONAL_HEADINGS = True` since 2026-09-18. Both experimental
    primitives change every route, so an unmarked test must not move with whatever `config.py`
    defaults to on the day, and four headings plan about three times quicker (0.94 s against
    2.93 s for shortest-time on testdata 05, measured 2026-09-25). The `diagonals` and `pivots`
    marks each switch their own experiment on, and a test may carry both: `test_poses.py`'s
    eight+pivots mode does. `test_diagonals.py` and `test_pivot.py` mark themselves whole.
    Figures pinned by unmarked tests - orders, times, a longest straight - are therefore
    four-heading figures, not what a request to the running service gets.

    Pinning BOTH flags for every unmarked test is also what turns the rest of the suite into the
    evidence that pivots are additive: it is only evidence if those tests provably ran with
    `PIVOT_TURNS` off, rather than with whatever `config.py` happened to default to on the day.
    """
    monkeypatch.setattr(config, "DIAGONAL_HEADINGS", "diagonals" in request.keywords)
    monkeypatch.setattr(config, "PIVOT_TURNS", "pivots" in request.keywords)
