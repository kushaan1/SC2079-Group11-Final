"""Typed loading and validation for committed training configuration."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple


IMAGE_REC_ROOT = Path(__file__).resolve().parents[1]
SPLIT_NAMES = ("train", "val", "test")


@dataclass(frozen=True)
class ClassDefinition:
    index: int
    name: str
    competition_id: Optional[int]


@dataclass(frozen=True)
class DatasetSettings:
    source_images: Path
    annotations: Path
    workspace: Path
    manifest: Path
    ratios: Mapping[str, float]
    seed: int
    required_class_splits: Tuple[str, ...]
    allow_empty_labels: bool


@dataclass(frozen=True)
class TrainingSettings:
    checkpoint: str
    epochs: int
    image_size: int
    batch_size: int
    patience: int
    workers: int
    project: Path
    run_name: str
    backend_preference: Tuple[str, ...]


@dataclass(frozen=True)
class ExportSettings:
    enabled: bool
    image_size: int
    calibration_fraction: float
    output_name: str


@dataclass(frozen=True)
class TaskConfig:
    schema_version: str
    task: str
    classes: Tuple[ClassDefinition, ...]
    classes_path: Path
    dataset: DatasetSettings
    training: TrainingSettings
    export: ExportSettings
    source_path: Path
    root: Path

    @property
    def class_names(self) -> Tuple[str, ...]:
        return tuple(item.name for item in self.classes)


def load_task_config(task: str, root: Optional[Path] = None) -> TaskConfig:
    resolved_root = (root or IMAGE_REC_ROOT).resolve()
    return load_config_path(resolved_root / "training" / "configs" / "{}.json".format(task), resolved_root)


def load_config_path(path: Path, root: Optional[Path] = None) -> TaskConfig:
    resolved_root = (root or IMAGE_REC_ROOT).resolve()
    source_path = path.resolve()
    with source_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if raw.get("schema_version") != "1.0":
        raise ValueError("unsupported training config schema_version")

    classes_path = _resolve(resolved_root, raw["classes"])
    classes = _load_classes(classes_path)
    dataset_raw = raw["dataset"]
    ratios = {name: float(dataset_raw["ratios"][name]) for name in SPLIT_NAMES}
    required = tuple(dataset_raw.get("required_class_splits", SPLIT_NAMES))
    dataset = DatasetSettings(
        source_images=_resolve(resolved_root, dataset_raw["source_images"]),
        annotations=_resolve(resolved_root, dataset_raw["annotations"]),
        workspace=_resolve(resolved_root, dataset_raw["workspace"]),
        manifest=_resolve(resolved_root, dataset_raw["manifest"]),
        ratios=ratios,
        seed=int(dataset_raw["seed"]),
        required_class_splits=required,
        allow_empty_labels=bool(dataset_raw.get("allow_empty_labels", False)),
    )
    train_raw = raw["training"]
    training = TrainingSettings(
        checkpoint=str(train_raw["checkpoint"]),
        epochs=int(train_raw["epochs"]),
        image_size=int(train_raw["image_size"]),
        batch_size=int(train_raw["batch_size"]),
        patience=int(train_raw["patience"]),
        workers=int(train_raw["workers"]),
        project=_resolve(resolved_root, train_raw["project"]),
        run_name=str(train_raw["run_name"]),
        backend_preference=tuple(train_raw.get("backend_preference", ("directml", "mps", "cpu"))),
    )
    export_raw = raw.get("export", {})
    export = ExportSettings(
        enabled=bool(export_raw.get("enabled", False)),
        image_size=int(export_raw.get("image_size", training.image_size)),
        calibration_fraction=float(export_raw.get("calibration_fraction", 1.0)),
        output_name=str(export_raw.get("output_name", "model-int8.tflite")),
    )
    config = TaskConfig(
        schema_version="1.0",
        task=str(raw["task"]),
        classes=classes,
        classes_path=classes_path,
        dataset=dataset,
        training=training,
        export=export,
        source_path=source_path,
        root=resolved_root,
    )
    _validate(config)
    return config


def _load_classes(path: Path) -> Tuple[ClassDefinition, ...]:
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if raw.get("schema_version") != "1.0" or not isinstance(raw.get("classes"), list):
        raise ValueError("invalid class registry: {}".format(path))
    classes: List[ClassDefinition] = []
    for index, item in enumerate(raw["classes"]):
        if isinstance(item, str):
            name, competition_id = item, None
        elif isinstance(item, dict):
            name = str(item["name"])
            competition_id = item.get("competition_id")
            competition_id = int(competition_id) if competition_id is not None else None
        else:
            raise ValueError("class entry {} is not a string or object".format(index))
        if not name.strip():
            raise ValueError("class {} has an empty name".format(index))
        classes.append(ClassDefinition(index, name.strip(), competition_id))
    if not classes:
        raise ValueError("at least one class is required")
    if len({item.name.casefold() for item in classes}) != len(classes):
        raise ValueError("class names must be unique")
    return tuple(classes)


def _resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _validate(config: TaskConfig) -> None:
    if config.task not in ("task1", "task2"):
        raise ValueError("task must be task1 or task2")
    if set(config.dataset.ratios) != set(SPLIT_NAMES):
        raise ValueError("dataset ratios must contain train, val, and test")
    if any(value <= 0.0 for value in config.dataset.ratios.values()):
        raise ValueError("every dataset split ratio must be positive")
    if abs(sum(config.dataset.ratios.values()) - 1.0) > 1e-9:
        raise ValueError("dataset split ratios must sum to 1.0")
    if not config.dataset.required_class_splits:
        raise ValueError("required_class_splits cannot be empty")
    if any(name not in SPLIT_NAMES for name in config.dataset.required_class_splits):
        raise ValueError("required_class_splits contains an unknown split")
    if min(
        config.training.epochs,
        config.training.image_size,
        config.training.batch_size,
        config.training.patience,
    ) <= 0:
        raise ValueError("training counts and dimensions must be positive")
    if config.training.workers < 0:
        raise ValueError("training workers cannot be negative")
    if not config.training.backend_preference or any(
        item not in ("directml", "mps", "cpu") for item in config.training.backend_preference
    ):
        raise ValueError("backend_preference may contain only directml, mps, and cpu")
    if not 0.0 < config.export.calibration_fraction <= 1.0:
        raise ValueError("export calibration_fraction must be in (0, 1]")
    generated_root = (config.root / "training" / ".generated").resolve()
    if generated_root not in config.dataset.workspace.parents:
        raise ValueError("dataset workspace must be inside training/.generated")
