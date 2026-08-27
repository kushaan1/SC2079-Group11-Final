"""Resolve training hardware in DirectML -> MPS -> CPU preference order."""

import importlib
import platform
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple


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
    preference: Sequence[str],
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
        "directml": _probe_directml,
        "mps": _probe_mps,
        "cpu": _probe_cpu,
    }


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
        "directml": ("directml", "privateuse", "device", "operator", "not implemented", "memory"),
        "mps": ("mps", "metal", "device", "operator", "not implemented", "memory"),
        "cpu": (),
    }[backend_name]
    return any(token in message for token in tokens)
