"""Export the trained Task 2 detector as a raw-output INT8 TFLite model."""

import argparse
import json
import shutil
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from .config import TaskConfig, load_task_config
from .metadata import environment_metadata, file_sha256, write_metadata
from .prepare import prepare_dataset


def export_int8(
    config: TaskConfig,
    weights: Path,
    publish: bool = False,
    yolo_factory: Optional[Callable[[str], Any]] = None,
    prepare: Callable[[TaskConfig], Path] = prepare_dataset,
) -> Path:
    if config.task != "task2" or not config.export.enabled:
        raise ValueError("INT8 deployment export is enabled only for Task 2")
    weights = weights.resolve()
    if not weights.is_file():
        raise FileNotFoundError("trained weights not found: {}".format(weights))
    data_path = prepare(config)
    if yolo_factory is None:
        from ultralytics import YOLO

        yolo_factory = YOLO
    model = yolo_factory(str(weights))
    export_arguments = {
        "format": "tflite",
        "int8": True,
        "data": str(data_path),
        "fraction": config.export.calibration_fraction,
        "imgsz": config.export.image_size,
        "batch": 1,
        "nms": False,
        "device": "cpu",
    }
    exported = model.export(**export_arguments)
    source = locate_tflite(exported, weights.parent)
    output_dir = config.root / "training" / "exports" / config.task
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / config.export.output_name
    shutil.copy2(str(source), str(output))
    labels = [item.name for item in config.classes]
    labels_path = output.with_suffix(".labels.json")
    labels_path.write_text(json.dumps(labels, indent=2) + "\n", encoding="utf-8")
    write_metadata(
        output.with_suffix(".metadata.json"),
        {
            "schema_version": "1.0",
            "task": config.task,
            "weights": str(weights),
            "weights_sha256": file_sha256(weights),
            "exported_model": str(output),
            "exported_model_sha256": file_sha256(output),
            "class_names": labels,
            "export_arguments": export_arguments,
            "config_sha256": file_sha256(config.source_path),
            "classes_sha256": file_sha256(config.classes_path),
            "environment": environment_metadata(),
            "pi_validation_required": True,
        },
    )
    if publish:
        publish_dir = config.root / "rpi" / "models"
        publish_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(output), str(publish_dir / config.export.output_name))
        (publish_dir / "arrow-labels.json").write_text(
            json.dumps(labels, indent=2) + "\n", encoding="utf-8"
        )
    return output


def locate_tflite(exported: Any, fallback_directory: Path) -> Path:
    candidates = []
    if isinstance(exported, (str, Path)):
        exported_path = Path(exported)
        if exported_path.is_file() and exported_path.suffix.lower() == ".tflite":
            return exported_path.resolve()
        if exported_path.is_dir():
            candidates.extend(exported_path.rglob("*.tflite"))
        elif exported_path.parent.is_dir():
            candidates.extend(exported_path.parent.rglob("*.tflite"))
    if fallback_directory.is_dir():
        candidates.extend(fallback_directory.rglob("*.tflite"))
    unique = sorted({path.resolve() for path in candidates if path.is_file()})
    if not unique:
        raise FileNotFoundError("Ultralytics export did not produce a .tflite file")
    preferred = [
        path
        for path in unique
        if "int8" in path.name.casefold() or "integer_quant" in path.name.casefold()
    ]
    selected = preferred or unique
    if len(selected) != 1:
        raise RuntimeError(
            "multiple candidate TFLite files found; remove stale exports: {}".format(
                ", ".join(str(path) for path in selected)
            )
        )
    return selected[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--publish", action="store_true", help="copy model and labels into rpi/models")
    args = parser.parse_args()
    output = export_int8(load_task_config("task2"), args.weights, args.publish)
    print(output)


if __name__ == "__main__":
    main()
