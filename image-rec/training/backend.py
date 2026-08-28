"""Resolve training hardware in CUDA -> ROCm -> DirectML -> MPS -> CPU order."""

import importlib
import platform
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple


SUPPORTED_BACKENDS = ("cuda", "rocm", "directml", "mps", "cpu")
DEFAULT_BACKEND_PREFERENCE = SUPPORTED_BACKENDS


@dataclass(frozen=True)
class BackendChoice:
    name: str
    device: Any
    detail: str


@dataclass(frozen=True)
class BackendProbe:
    name: str
    available: bool
    detail: str
    choice: Optional[BackendChoice] = None


def resolve_backends(
    preference: Sequence[str] = DEFAULT_BACKEND_PREFERENCE,
    probes: Optional[Mapping[str, Callable[[], BackendChoice]]] = None,
) -> Tuple[Tuple[BackendChoice, ...], Tuple[BackendProbe, ...]]:
    """Return available backends in preference order and a complete probe report."""

    implementations = dict(probes or _default_probes())
    choices: List[BackendChoice] = []
    report: List[BackendProbe] = []
    for name in preference:
        probe = implementations[name]
        try:
            choice = probe()
        except Exception as error:
            report.append(BackendProbe(name, False, "{}: {}".format(type(error).__name__, error)))
        else:
            choices.append(choice)
            report.append(BackendProbe(name, True, choice.detail, choice))
    if not choices:
        raise RuntimeError("no requested training backend is available")
    return tuple(choices), tuple(report)


def _default_probes() -> Dict[str, Callable[[], BackendChoice]]:
    return {
        "cuda": _probe_cuda,
        "rocm": _probe_rocm,
        "directml": _probe_directml,
        "mps": _probe_mps,
        "cpu": _probe_cpu,
    }


def _probe_cuda() -> BackendChoice:
    """Probe a native NVIDIA CUDA PyTorch build.

    PyTorch exposes ROCm through the same ``torch.cuda`` namespace as CUDA.  Check the
    build marker first so an AMD/ROCm installation is reported as ``rocm`` and can be
    selected at the next priority level instead of being mislabeled as CUDA.
    """

    torch = importlib.import_module("torch")
    hip_version = getattr(getattr(torch, "version", None), "hip", None)
    if hip_version:
        raise RuntimeError("PyTorch HIP/ROCm build detected; use the ROCm backend")
    return _probe_torch_cuda_backend(torch, "cuda", "CUDA", "cuda")


def _probe_rocm() -> BackendChoice:
    """Probe AMD ROCm, which PyTorch exposes through ``torch.cuda``."""

    torch = importlib.import_module("torch")
    hip_version = getattr(getattr(torch, "version", None), "hip", None)
    if not hip_version:
        raise RuntimeError("PyTorch ROCm/HIP build is unavailable")
    return _probe_torch_cuda_backend(torch, "rocm", "ROCm/HIP", str(hip_version))


def _probe_torch_cuda_backend(
    torch: Any, backend_name: str, label: str, build_version: str
) -> BackendChoice:
    cuda = getattr(torch, "cuda", None)
    is_available = getattr(cuda, "is_available", None)
    if not callable(is_available) or not is_available():
        raise RuntimeError("PyTorch {} is unavailable".format(label))

    device = "cuda:0"
    try:
        # A real allocation and arithmetic operation catches driver, runtime, and
        # unsupported-kernel problems before Ultralytics starts a long run.
        result = torch.ones(1, device=device) + torch.ones(1, device=device)
        synchronize = getattr(cuda, "synchronize", None)
        if callable(synchronize):
            synchronize()
        value = float(result.cpu().item())
    except Exception as error:
        raise RuntimeError("{} smoke test failed: {}".format(label, error))
    if value != 2.0:
        raise RuntimeError("{} smoke test returned an unexpected result".format(label))

    try:
        device_name = cuda.get_device_name(0)
    except Exception:
        device_name = None
    suffix = " ({})".format(device_name) if device_name else ""
    return BackendChoice(
        backend_name,
        device,
        "PyTorch {} {}{}".format(label, build_version, suffix),
    )


def _probe_directml() -> BackendChoice:
    if platform.system() != "Windows":
        raise RuntimeError("DirectML is enabled only on Windows")
    torch = importlib.import_module("torch")
    torch_directml = importlib.import_module("torch_directml")
    device = torch_directml.device()
    # Exercise allocation and one operator before advertising the backend.
    result = torch.ones(1, device=device) + torch.ones(1, device=device)
    if float(result.cpu().item()) != 2.0:
        raise RuntimeError("DirectML smoke test returned an unexpected result")
    return BackendChoice("directml", device, "torch-directml {}".format(device))


def _probe_mps() -> BackendChoice:
    torch = importlib.import_module("torch")
    mps = getattr(getattr(torch, "backends", None), "mps", None)
    if mps is None or not mps.is_available():
        raise RuntimeError("PyTorch MPS is unavailable")
    result = torch.ones(1, device="mps") + torch.ones(1, device="mps")
    if float(result.cpu().item()) != 2.0:
        raise RuntimeError("MPS smoke test returned an unexpected result")
    return BackendChoice("mps", "mps", "PyTorch Metal Performance Shaders")


def _probe_cpu() -> BackendChoice:
    torch = importlib.import_module("torch")
    result = torch.ones(1, device="cpu") + torch.ones(1, device="cpu")
    if float(result.item()) != 2.0:
        raise RuntimeError("CPU smoke test returned an unexpected result")
    return BackendChoice("cpu", "cpu", "PyTorch CPU")


def backend_error_allows_fallback(error: Exception, backend_name: str) -> bool:
    """Avoid hiding dataset/network/config errors behind an automatic fallback."""

    message = "{}: {}".format(type(error).__name__, error).casefold()
    tokens = {
        "cuda": ("cuda", "cudnn", "device", "operator", "not implemented", "memory"),
        "rocm": (
            "rocm",
            "hip",
            "cuda",
            "miopen",
            "device",
            "operator",
            "not implemented",
            "memory",
        ),
        "directml": ("directml", "privateuse", "device", "operator", "not implemented", "memory"),
        "mps": ("mps", "metal", "device", "operator", "not implemented", "memory"),
        "cpu": (),
    }[backend_name]
    return any(token in message for token in tokens)
