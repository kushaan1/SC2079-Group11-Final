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


@pytest.fixture(autouse=True)
def four_headings(monkeypatch, request):
    """
    Pin every test to the four-heading planner unless it asks for the diagonals.

    The diagonal headings are experimental and change every route, so without this the suite
    would stop characterising the planner the service actually ships. `test_diagonals.py`
    marks itself `@pytest.mark.diagonals` and gets them switched on. Neither depends on what
    `config.DIAGONAL_HEADINGS` happens to be set to.
    """
    monkeypatch.setattr(config, "DIAGONAL_HEADINGS", "diagonals" in request.keywords)
