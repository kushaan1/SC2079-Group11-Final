"""Prepare and train either Ultralytics YOLOv8 detection model."""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

from .backend import (
    SUPPORTED_BACKENDS,
    BackendChoice,
    backend_error_allows_fallback,
    resolve_backends,
)
from .config import TaskConfig, load_task_config
from .metadata import environment_metadata, file_sha256, write_metadata
from .prepare import prepare_dataset


@dataclass(frozen=True)
class TrainingOutcome:
    backend: str
    save_dir: Path
    result: Any


def train_task(
    config: TaskConfig,
    backend_override: str = "auto",
    epochs: Optional[int] = None,
    batch_size: Optional[int] = None,
    image_size: Optional[int] = None,
    yolo_factory: Optional[Callable[[str], Any]] = None,
    prepare: Callable[[TaskConfig], Path] = prepare_dataset,
    backend_choices: Optional[Sequence[BackendChoice]] = None,
) -> TrainingOutcome:
    data_path = prepare(config)
    if yolo_factory is None:
        from ultralytics import YOLO

        yolo_factory = YOLO

    preference = (
        (backend_override,)
        if backend_override != "auto"
        else config.training.backend_preference
    )
    probe_report = ()
    if backend_choices is None:
        choices, probe_report = resolve_backends(preference)
    else:
        choices = tuple(
            item for item in backend_choices if backend_override == "auto" or item.name == backend_override
        )
        if not choices:
            raise RuntimeError("requested backend is not available")

    train_arguments: Dict[str, Any] = {
        "data": str(data_path),
        "epochs": epochs or config.training.epochs,
        "imgsz": image_size or config.training.image_size,
        "batch": batch_size or config.training.batch_size,
        "patience": config.training.patience,
        "workers": config.training.workers,
        "project": str(config.training.project),
        "name": config.training.run_name,
        "seed": config.dataset.seed,
        "deterministic": True,
        "val": True,
        "plots": True,
        "save": True,
        "exist_ok": False,
    }
    failures = []
    for choice in choices:
        model = yolo_factory(config.training.checkpoint)
        try:
            result = model.train(device=choice.device, **train_arguments)
        except Exception as error:
            failures.append(
                {"backend": choice.name, "error": "{}: {}".format(type(error).__name__, error)}
            )
            if choice.name == "cpu" or not backend_error_allows_fallback(error, choice.name):
                raise
            print(
                "{} training backend failed; trying next configured backend: {}".format(
                    choice.name, error
                ),
                file=sys.stderr,
            )
            continue

        save_dir = Path(getattr(result, "save_dir", config.training.project / config.training.run_name))
        metadata_payload = {
            "schema_version": "1.0",
            "task": config.task,
            "backend": {"name": choice.name, "device": str(choice.device), "detail": choice.detail},
            "backend_probes": [
                {"name": item.name, "available": item.available, "detail": item.detail}
                for item in probe_report
            ],
            "previous_backend_failures": failures,
            "training_arguments": train_arguments,
            "checkpoint": config.training.checkpoint,
            "config": str(config.source_path),
            "config_sha256": file_sha256(config.source_path),
            "classes": str(config.classes_path),
            "classes_sha256": file_sha256(config.classes_path),
            "split_manifest": str(config.dataset.manifest),
            "split_manifest_sha256": file_sha256(config.dataset.manifest),
            "environment": environment_metadata(),
        }
        write_metadata(save_dir / "run-metadata.json", metadata_payload)
        return TrainingOutcome(choice.name, save_dir, result)
    raise RuntimeError("every available training backend failed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=("task1", "task2"), required=True)
    parser.add_argument(
        "--backend", choices=("auto",) + SUPPORTED_BACKENDS, default="auto"
    )
    parser.add_argument("--epochs", type=int)
    parser.add_argument("--batch-size", type=int)
    parser.add_argument("--image-size", type=int)
    args = parser.parse_args()
    outcome = train_task(
        load_task_config(args.task),
        backend_override=args.backend,
        epochs=args.epochs,
        batch_size=args.batch_size,
        image_size=args.image_size,
    )
    print("backend={}".format(outcome.backend))
    print(outcome.save_dir)


if __name__ == "__main__":
    main()
