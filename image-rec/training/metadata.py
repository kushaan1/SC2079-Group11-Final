"""Capture enough environment detail to explain and replay a training run."""

import hashlib
import json
import platform
import sys
from importlib import metadata
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping


TRACKED_PACKAGES = (
    "ultralytics",
    "torch",
    "torch-directml",
    "numpy",
    "opencv-python-headless",
    "matplotlib",
)


def environment_metadata() -> Dict[str, Any]:
    packages: Dict[str, str] = {}
    for package in TRACKED_PACKAGES:
        try:
            packages[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            packages[package] = "not-installed"
    return {
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "packages": packages,
    }


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_metadata(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, default=str) + "\n", encoding="utf-8")
