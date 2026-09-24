import importlib
import os

import pytest

import rpi.config


@pytest.fixture(autouse=True)
def clean_config(monkeypatch):
    for name in list(os.environ):
        if name.startswith("RPI_"):
            monkeypatch.delenv(name)
    yield
    monkeypatch.undo()                # restore the environment first...
    importlib.reload(rpi.config)      # ...then the module, so no test leaks into the next
