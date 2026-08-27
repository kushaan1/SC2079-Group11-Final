from types import SimpleNamespace

import pytest

from training.backend import BackendChoice, backend_error_allows_fallback, resolve_backends


def test_resolves_requested_backends_in_order_and_reports_failures():
    def unavailable():
        raise RuntimeError("not installed")

    probes = {
        "directml": unavailable,
        "mps": lambda: BackendChoice("mps", "mps", "available"),
        "cpu": lambda: BackendChoice("cpu", "cpu", "available"),
    }
    choices, report = resolve_backends(("directml", "mps", "cpu"), probes)
    assert [item.name for item in choices] == ["mps", "cpu"]
    assert [(item.name, item.available) for item in report] == [
        ("directml", False),
        ("mps", True),
        ("cpu", True),
    ]


def test_fallback_filter_does_not_hide_unrelated_failures():
    assert backend_error_allows_fallback(RuntimeError("PrivateUse1 operator missing"), "directml")
    assert not backend_error_allows_fallback(FileNotFoundError("dataset missing"), "directml")
    assert not backend_error_allows_fallback(RuntimeError("anything"), "cpu")
