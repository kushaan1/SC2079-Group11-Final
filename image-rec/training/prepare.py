"""Validate, stratify, and materialize deterministic Ultralytics datasets."""

import argparse
import json
import os
import random
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, MutableMapping, Sequence, Set, Tuple

from .config import SPLIT_NAMES, TaskConfig, load_task_config
from .dataset import DatasetValidationError, Sample, validate_dataset


def allocate_splits(
    samples: Sequence[Sample],
    class_count: int,
    ratios: Mapping[str, float],
    required_class_splits: Sequence[str],
    seed: int,
) -> Dict[int, str]:
    """Assign sample indices while guaranteeing configured per-class coverage."""

    if not samples:
        raise DatasetValidationError("cannot split an empty dataset")
    required = tuple(required_class_splits)
    class_to_indices: Dict[int, Set[int]] = {
        class_id: {index for index, sample in enumerate(samples) if class_id in sample.class_ids}
        for class_id in range(class_count)
    }
    for class_id, indices in class_to_indices.items():
        if len(indices) < len(required):
            raise DatasetValidationError(
                "class {} has {} labelled image(s), but {} distinct images are required to cover {}".format(
                    class_id,
                    len(indices),
                    len(required),
                    ", ".join(required),
                )
            )

    rng = random.Random(seed)
    tie_break = {index: rng.random() for index in range(len(samples))}
    split_tie = {name: rng.random() for name in SPLIT_NAMES}
    assignments: Dict[int, str] = {}
    covered: Dict[int, Set[str]] = {class_id: set() for class_id in range(class_count)}

    while True:
        missing = [
            (class_id, split)
            for class_id in range(class_count)
            for split in required
            if split not in covered[class_id]
        ]
        if not missing:
            break
        missing.sort(
            key=lambda pair: (
                len(class_to_indices[pair[0]] - set(assignments)),
                ratios[pair[1]],
                pair[0],
                pair[1],
            )
        )
        class_id, split = missing[0]
        candidates = class_to_indices[class_id] - set(assignments)
        viable = [
            index
            for index in candidates
            if _coverage_remains_feasible(
                index,
                split,
                samples,
                assignments,
                class_to_indices,
                covered,
                required,
            )
        ]
        if not viable:
            raise DatasetValidationError(
                "could not allocate class {} to {} without breaking another class constraint; "
                "add more independently captured images".format(class_id, split)
            )
        chosen = max(
            viable,
            key=lambda index: (
                sum(
                    1
                    for candidate_class in samples[index].class_ids
                    if split not in covered[candidate_class]
                ),
                sum(1.0 / len(class_to_indices[item]) for item in samples[index].class_ids),
                tie_break[index],
            ),
        )
        assignments[chosen] = split
        for candidate_class in samples[chosen].class_ids:
            covered[candidate_class].add(split)

    reserved_counts = Counter(assignments.values())
    target_counts = _target_split_counts(len(samples), ratios, reserved_counts)
    class_totals = {class_id: len(indices) for class_id, indices in class_to_indices.items()}
    split_class_counts: Dict[str, Counter] = {name: Counter() for name in SPLIT_NAMES}
    for index, split in assignments.items():
        split_class_counts[split].update(samples[index].class_ids)

    remaining = [index for index in range(len(samples)) if index not in assignments]
    remaining.sort(
        key=lambda index: (
            -sum(1.0 / class_totals[class_id] for class_id in samples[index].class_ids),
            tie_break[index],
        )
    )
    split_counts = Counter(assignments.values())
    for index in remaining:
        available = [name for name in SPLIT_NAMES if split_counts[name] < target_counts[name]]
        if not available:
            raise AssertionError("split allocator exhausted all capacities")

        def score(split: str) -> Tuple[float, float, float]:
            class_deficit = sum(
                max(
                    0.0,
                    class_totals[class_id] * ratios[split] - split_class_counts[split][class_id],
                )
                / class_totals[class_id]
                for class_id in samples[index].class_ids
            )
            capacity = (target_counts[split] - split_counts[split]) / float(target_counts[split])
            return class_deficit, capacity, split_tie[split]

        selected = max(available, key=score)
        assignments[index] = selected
        split_counts[selected] += 1
        split_class_counts[selected].update(samples[index].class_ids)

    _assert_coverage(samples, assignments, class_count, required)
    return assignments


def _coverage_remains_feasible(
    candidate: int,
    split: str,
    samples: Sequence[Sample],
    assignments: Mapping[int, str],
    class_to_indices: Mapping[int, Set[int]],
    covered: Mapping[int, Set[str]],
    required: Sequence[str],
) -> bool:
    assigned_after = set(assignments)
    assigned_after.add(candidate)
    candidate_classes = set(samples[candidate].class_ids)
    for class_id, indices in class_to_indices.items():
        covered_after = set(covered[class_id])
        if class_id in candidate_classes:
            covered_after.add(split)
        missing_count = len(set(required) - covered_after)
        remaining_count = len(indices - assigned_after)
        if remaining_count < missing_count:
            return False
    return True


def _target_split_counts(
    sample_count: int,
    ratios: Mapping[str, float],
    reserved: Mapping[str, int],
) -> Dict[str, int]:
    raw = {name: sample_count * ratios[name] for name in SPLIT_NAMES}
    targets = {name: int(raw[name]) for name in SPLIT_NAMES}
    remainder = sample_count - sum(targets.values())
    for name in sorted(SPLIT_NAMES, key=lambda item: (raw[item] - targets[item], item), reverse=True):
        if remainder <= 0:
            break
        targets[name] += 1
        remainder -= 1
    targets = {name: max(targets[name], int(reserved.get(name, 0))) for name in SPLIT_NAMES}

    while sum(targets.values()) > sample_count:
        reducible = [name for name in SPLIT_NAMES if targets[name] > int(reserved.get(name, 0))]
        if not reducible:
            raise DatasetValidationError("required class coverage consumes more images than available")
        selected = max(reducible, key=lambda name: (targets[name] - raw[name], targets[name]))
        targets[selected] -= 1
    while sum(targets.values()) < sample_count:
        selected = max(SPLIT_NAMES, key=lambda name: (raw[name] - targets[name], ratios[name]))
        targets[selected] += 1
    return targets


def _assert_coverage(
    samples: Sequence[Sample],
    assignments: Mapping[int, str],
    class_count: int,
    required: Sequence[str],
) -> None:
    coverage: Dict[int, Set[str]] = defaultdict(set)
    for index, split in assignments.items():
        for class_id in samples[index].class_ids:
            coverage[class_id].add(split)
    missing = [
        "class {} missing from {}".format(class_id, split)
        for class_id in range(class_count)
        for split in required
        if split not in coverage[class_id]
    ]
    if missing:
        raise AssertionError("split coverage invariant failed: {}".format(", ".join(missing)))


def prepare_dataset(config: TaskConfig) -> Path:
    """Validate source data, materialize split files, and write a replay manifest."""

    report = validate_dataset(config)
    report.raise_for_errors()
    assignments = allocate_splits(
        report.samples,
        len(config.classes),
        config.dataset.ratios,
        config.dataset.required_class_splits,
        config.dataset.seed,
    )
    _reset_workspace(config)
    manifest_samples: List[Dict[str, object]] = []
    for index, sample in enumerate(report.samples):
        split = assignments[index]
        image_destination = config.dataset.workspace / "images" / split / sample.relative_path
        label_destination = (
            config.dataset.workspace / "labels" / split / sample.relative_path
        ).with_suffix(".txt")
        _hardlink_or_copy(sample.image_path, image_destination)
        label_destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(sample.label_path), str(label_destination))
        manifest_samples.append(
            {
                "image": sample.relative_path.as_posix(),
                "label": sample.label_path.relative_to(config.dataset.annotations).as_posix(),
                "split": split,
                "class_indices": list(sample.class_ids),
                "width": sample.width,
                "height": sample.height,
                "image_sha256": sample.image_sha256,
                "label_sha256": sample.label_sha256,
            }
        )

    data_path = config.dataset.workspace / "data.yaml"
    data_contract = {
        "path": str(config.dataset.workspace),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "names": {str(item.index): item.name for item in config.classes},
    }
    data_path.write_text(json.dumps(data_contract, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": "1.0",
        "task": config.task,
        "seed": config.dataset.seed,
        "ratios": dict(config.dataset.ratios),
        "required_class_splits": list(config.dataset.required_class_splits),
        "classes": [
            {
                "index": item.index,
                "name": item.name,
                "competition_id": item.competition_id,
            }
            for item in config.classes
        ],
        "samples": manifest_samples,
    }
    config.dataset.manifest.parent.mkdir(parents=True, exist_ok=True)
    config.dataset.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return data_path


def _reset_workspace(config: TaskConfig) -> None:
    workspace = config.dataset.workspace.resolve()
    generated_root = (config.root / "training" / ".generated").resolve()
    if generated_root not in workspace.parents:
        raise ValueError("refusing to reset workspace outside training/.generated")
    if workspace.exists():
        shutil.rmtree(str(workspace))
    workspace.mkdir(parents=True)


def _hardlink_or_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(str(source), str(destination))
    except OSError:
        shutil.copy2(str(source), str(destination))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=("task1", "task2"), required=True)
    args = parser.parse_args()
    config = load_task_config(args.task)
    data_path = prepare_dataset(config)
    print(data_path)
    print(config.dataset.manifest)


if __name__ == "__main__":
    main()
