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
    Pin every test to the planner the service ships - four headings, no pivots - unless it
    asks for one of the experiments by marker.

    Both experimental primitives change every route, so without this the suite would stop
    characterising the planner we actually deploy. `test_diagonals.py` marks itself
    `@pytest.mark.diagonals` and `test_pivot.py` marks itself `@pytest.mark.pivots`; each gets
    its own flag switched on and no others. Pinning BOTH flags for every unmarked test is what
    turns the rest of the suite into the evidence that pivots are additive: it is only evidence
    if those tests provably ran with `PIVOT_TURNS` off, rather than with whatever `config.py`
    happened to default to on the day.
    """
    monkeypatch.setattr(config, "DIAGONAL_HEADINGS", "diagonals" in request.keywords)
    monkeypatch.setattr(config, "PIVOT_TURNS", "pivots" in request.keywords)
