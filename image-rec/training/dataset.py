"""YOLO annotation discovery and fail-fast dataset validation."""

import hashlib
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

from .config import TaskConfig


IMAGE_SUFFIXES = frozenset((".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"))
PLACEHOLDER_TEXT = """TODO: replace this file with a YOLO annotation named {label_name}

Each object is one line with five space-separated values:
<class_index> <x_center> <y_center> <width> <height>

Coordinates and dimensions are normalized to 0..1. Delete this .txt.todo file only after creating
and checking the corresponding .txt annotation. Class indices come from {classes_path}.
"""


@dataclass(frozen=True)
class DatasetIssue:
    code: str
    path: Path
    message: str


@dataclass(frozen=True)
class Sample:
    image_path: Path
    label_path: Path
    relative_path: Path
    class_ids: Tuple[int, ...]
    image_sha256: str
    label_sha256: str
    width: int
    height: int


@dataclass(frozen=True)
class ValidationReport:
    samples: Tuple[Sample, ...]
    issues: Tuple[DatasetIssue, ...]
    class_image_counts: Mapping[int, int]
    class_box_counts: Mapping[int, int]

    @property
    def valid(self) -> bool:
        return not self.issues

    def raise_for_errors(self) -> None:
        if self.issues:
            detail = "\n".join(
                "- [{}] {}: {}".format(issue.code, issue.path, issue.message)
                for issue in self.issues
            )
            raise DatasetValidationError("dataset validation failed:\n{}".format(detail))


class DatasetValidationError(ValueError):
    pass


def discover_images(source: Path) -> Tuple[Path, ...]:
    if not source.is_dir():
        return tuple()
    return tuple(
        sorted(
            (path for path in source.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES),
            key=lambda path: path.relative_to(source).as_posix().casefold(),
        )
    )


def annotation_paths(config: TaskConfig, image_path: Path) -> Tuple[Path, Path]:
    relative = image_path.relative_to(config.dataset.source_images)
    label = (config.dataset.annotations / relative).with_suffix(".txt")
    placeholder = label.with_suffix(".txt.todo")
    return label, placeholder


def create_placeholders(config: TaskConfig) -> Tuple[Path, ...]:
    """Create non-trainable TODO files for images that have no real label."""

    created: List[Path] = []
    for image_path in discover_images(config.dataset.source_images):
        label, placeholder = annotation_paths(config, image_path)
        if label.exists() or placeholder.exists():
            continue
        placeholder.parent.mkdir(parents=True, exist_ok=True)
        placeholder.write_text(
            PLACEHOLDER_TEXT.format(
                label_name=label.name,
                classes_path=config.classes_path.relative_to(config.root).as_posix(),
            ),
            encoding="utf-8",
        )
        created.append(placeholder)
    return tuple(created)


def validate_dataset(config: TaskConfig) -> ValidationReport:
    import cv2

    images = discover_images(config.dataset.source_images)
    issues: List[DatasetIssue] = []
    samples: List[Sample] = []
    class_image_counts: Counter = Counter()
    class_box_counts: Counter = Counter()
    hashes: Dict[str, List[Path]] = defaultdict(list)

    if not images:
        issues.append(
            DatasetIssue("no_images", config.dataset.source_images, "no supported image files found")
        )

    for image_path in images:
        label_path, placeholder_path = annotation_paths(config, image_path)
        if not label_path.is_file():
            code = "placeholder_annotation" if placeholder_path.is_file() else "missing_annotation"
            message = (
                "replace the .txt.todo file with a reviewed YOLO .txt label"
                if placeholder_path.is_file()
                else "create the corresponding YOLO .txt label"
            )
            issues.append(DatasetIssue(code, image_path, message))
            continue

        image = cv2.imread(str(image_path))
        if image is None:
            issues.append(DatasetIssue("invalid_image", image_path, "OpenCV could not decode image"))
            continue
        height, width = image.shape[:2]
        image_hash = _sha256(image_path)
        hashes[image_hash].append(image_path)
        parsed, label_issues = _parse_label(label_path, len(config.classes), config.dataset.allow_empty_labels)
        issues.extend(label_issues)
        if label_issues:
            continue

        class_ids = tuple(sorted({item[0] for item in parsed}))
        for class_id in class_ids:
            class_image_counts[class_id] += 1
        for class_id, _, _, _, _ in parsed:
            class_box_counts[class_id] += 1
        samples.append(
            Sample(
                image_path=image_path,
                label_path=label_path,
                relative_path=image_path.relative_to(config.dataset.source_images),
                class_ids=class_ids,
                image_sha256=image_hash,
                label_sha256=_sha256(label_path),
                width=width,
                height=height,
            )
        )

    for digest, duplicate_paths in hashes.items():
        if len(duplicate_paths) > 1:
            for path in duplicate_paths:
                others = [str(item) for item in duplicate_paths if item != path]
                issues.append(
                    DatasetIssue(
                        "duplicate_image",
                        path,
                        "same SHA-256 as {} ({})".format(", ".join(others), digest[:12]),
                    )
                )

    for class_definition in config.classes:
        if class_image_counts[class_definition.index] == 0:
            issues.append(
                DatasetIssue(
                    "missing_class",
                    config.classes_path,
                    "class {} ({}) has no labelled image".format(
                        class_definition.index, class_definition.name
                    ),
                )
            )

    return ValidationReport(
        samples=tuple(samples),
        issues=tuple(issues),
        class_image_counts=dict(class_image_counts),
        class_box_counts=dict(class_box_counts),
    )


def _parse_label(
    path: Path,
    class_count: int,
    allow_empty: bool,
) -> Tuple[List[Tuple[int, float, float, float, float]], List[DatasetIssue]]:
    rows: List[Tuple[int, float, float, float, float]] = []
    issues: List[DatasetIssue] = []
    text = path.read_text(encoding="utf-8-sig")
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            issues.append(
                DatasetIssue(
                    "invalid_annotation",
                    path,
                    "line {} must contain exactly 5 values".format(line_number),
                )
            )
            continue
        try:
            class_value = float(parts[0])
            coordinates = tuple(float(value) for value in parts[1:])
        except ValueError:
            issues.append(
                DatasetIssue("invalid_annotation", path, "line {} contains non-numeric data".format(line_number))
            )
            continue
        if not class_value.is_integer() or not 0 <= int(class_value) < class_count:
            issues.append(
                DatasetIssue(
                    "invalid_class",
                    path,
                    "line {} class index is outside 0..{}".format(line_number, class_count - 1),
                )
            )
            continue
        if not all(math.isfinite(value) for value in coordinates):
            issues.append(
                DatasetIssue("invalid_box", path, "line {} has a non-finite coordinate".format(line_number))
            )
            continue
        x_center, y_center, box_width, box_height = coordinates
        if not (0.0 <= x_center <= 1.0 and 0.0 <= y_center <= 1.0):
            issues.append(
                DatasetIssue("invalid_box", path, "line {} centre must be inside 0..1".format(line_number))
            )
            continue
        if not (0.0 < box_width <= 1.0 and 0.0 < box_height <= 1.0):
            issues.append(
                DatasetIssue("invalid_box", path, "line {} width/height must be in (0, 1]".format(line_number))
            )
            continue
        tolerance = 1e-6
        if (
            x_center - box_width / 2.0 < -tolerance
            or x_center + box_width / 2.0 > 1.0 + tolerance
            or y_center - box_height / 2.0 < -tolerance
            or y_center + box_height / 2.0 > 1.0 + tolerance
        ):
            issues.append(
                DatasetIssue("invalid_box", path, "line {} box extends outside the image".format(line_number))
            )
            continue
        rows.append((int(class_value), x_center, y_center, box_width, box_height))

    if not rows and not issues and not allow_empty:
        issues.append(
            DatasetIssue(
                "empty_annotation",
                path,
                "empty labels are disabled to prevent accidental negative examples",
            )
        )
    return rows, issues


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
