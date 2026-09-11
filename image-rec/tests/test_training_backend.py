from types import SimpleNamespace

import pytest

import training.backend as backend
from training.backend import (
    DEFAULT_BACKEND_PREFERENCE,
    BackendChoice,
    backend_error_allows_fallback,
    resolve_backends,
)


def test_default_backend_priority_prefers_cuda_then_rocm():
    assert DEFAULT_BACKEND_PREFERENCE == ("cuda", "rocm", "directml", "mps", "cpu")


def test_resolve_backends_uses_the_default_priority_when_unspecified():
    probes = {
        name: (lambda name=name: BackendChoice(name, name, "available"))
        for name in DEFAULT_BACKEND_PREFERENCE
    }
    choices, _ = resolve_backends(probes=probes)
    assert [item.name for item in choices] == list(DEFAULT_BACKEND_PREFERENCE)


def test_resolves_requested_backends_in_order_and_reports_failures():
    def unavailable():
        raise RuntimeError("not installed")

    probes = {
        "cuda": unavailable,
        "rocm": lambda: BackendChoice("rocm", "cuda:0", "available"),
        "directml": unavailable,
        "mps": lambda: BackendChoice("mps", "mps", "available"),
        "cpu": lambda: BackendChoice("cpu", "cpu", "available"),
    }
    choices, report = resolve_backends(DEFAULT_BACKEND_PREFERENCE, probes)
    assert [item.name for item in choices] == ["rocm", "mps", "cpu"]
    assert [(item.name, item.available) for item in report] == [
        ("cuda", False),
        ("rocm", True),
        ("directml", False),
        ("mps", True),
        ("cpu", True),
    ]


def test_fallback_filter_does_not_hide_unrelated_failures():
    assert backend_error_allows_fallback(RuntimeError("HIP operator missing"), "rocm")
    assert backend_error_allows_fallback(RuntimeError("CUDA out of memory"), "cuda")
    assert backend_error_allows_fallback(RuntimeError("PrivateUse1 operator missing"), "directml")
    assert not backend_error_allows_fallback(FileNotFoundError("dataset missing"), "directml")
    assert not backend_error_allows_fallback(RuntimeError("anything"), "cpu")


class FakeTensor:
    def __init__(self, value):
        self.value = value

    def __add__(self, other):
        return FakeTensor(self.value + other.value)

    def cpu(self):
        return self

    def item(self):
        return self.value


class FakeCuda:
    def __init__(self, available=True):
        self.available = available

    def is_available(self):
        return self.available

    def get_device_name(self, index):
        assert index == 0
        return "AMD Radeon RX 9070 XT"


def test_rocm_probe_uses_cuda_device_namespace_and_reports_gpu(monkeypatch):
    fake_torch = SimpleNamespace(
        version=SimpleNamespace(hip="7.0.0"),
        cuda=FakeCuda(),
        ones=lambda size, device: FakeTensor(1),
    )
    monkeypatch.setattr(backend.importlib, "import_module", lambda name: fake_torch)

    choice = backend._probe_rocm()

    assert choice.name == "rocm"
    assert choice.device == "cuda:0"
    assert "ROCm/HIP 7.0.0" in choice.detail
    assert "RX 9070 XT" in choice.detail


def test_cuda_probe_does_not_claim_a_rocm_build(monkeypatch):
    fake_torch = SimpleNamespace(version=SimpleNamespace(hip="7.0.0"))
    monkeypatch.setattr(backend.importlib, "import_module", lambda name: fake_torch)

    with pytest.raises(RuntimeError, match="ROCm"):
        backend._probe_cuda()
