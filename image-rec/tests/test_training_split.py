import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from training.config import load_config_path
from training.dataset import DatasetValidationError, Sample
from training.prepare import allocate_splits, prepare_dataset


def sample(index, class_ids):
    name = Path("{}.jpg".format(index))
    return Sample(name, name.with_suffix(".txt"), name, tuple(class_ids), str(index), str(index), 10, 10)


def test_split_is_deterministic_and_covers_every_class_in_every_split():
    samples = []
    for class_id in range(3):
        samples.extend(sample("{}-{}".format(class_id, copy), (class_id,)) for copy in range(5))
    first = allocate_splits(
        samples,
        class_count=3,
        ratios={"train": 0.7, "val": 0.2, "test": 0.1},
        required_class_splits=("train", "val", "test"),
        seed=2079,
    )
    second = allocate_splits(
        samples,
        class_count=3,
        ratios={"train": 0.7, "val": 0.2, "test": 0.1},
        required_class_splits=("train", "val", "test"),
        seed=2079,
    )
    assert first == second
    for class_id in range(3):
        assert {
            first[index] for index, item in enumerate(samples) if class_id in item.class_ids
        } == {"train", "val", "test"}


def test_split_fails_when_a_class_cannot_cover_required_pools():
    samples = [sample(0, (0,)), sample(1, (0,))]
    with pytest.raises(DatasetValidationError, match="3 distinct images"):
        allocate_splits(
            samples,
            1,
            {"train": 0.7, "val": 0.2, "test": 0.1},
            ("train", "val", "test"),
            1,
        )


def build_config(tmp_path):
    classes_path = tmp_path / "training/classes/test.json"
    classes_path.parent.mkdir(parents=True)
    classes_path.write_text(
        json.dumps({"schema_version": "1.0", "classes": ["arrow"]}),
        encoding="utf-8",
    )
    raw = {
        "schema_version": "1.0",
        "task": "task2",
        "classes": "training/classes/test.json",
        "dataset": {
            "source_images": "training/images",
            "annotations": "training/annotations",
            "workspace": "training/.generated/test",
            "manifest": "training/manifests/test.json",
            "ratios": {"train": 0.7, "val": 0.2, "test": 0.1},
            "seed": 9,
            "required_class_splits": ["train", "val", "test"],
            "allow_empty_labels": False,
        },
        "training": {
            "checkpoint": "yolov8n.pt",
            "epochs": 1,
            "image_size": 32,
            "batch_size": 1,
            "patience": 1,
            "workers": 0,
            "project": "training/runs/test",
            "run_name": "test",
            "backend_preference": ["cpu"],
        },
        "export": {"enabled": True, "image_size": 32, "calibration_fraction": 1.0},
    }
    config_path = tmp_path / "training/configs/test.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    return load_config_path(config_path, root=tmp_path)


def test_prepare_materializes_dataset_and_replay_manifest(tmp_path):
    config = build_config(tmp_path)
    config.dataset.source_images.mkdir(parents=True)
    config.dataset.annotations.mkdir(parents=True)
    for index, value in enumerate((10, 20, 30, 40)):
        image_path = config.dataset.source_images / "{}.jpg".format(index)
        assert cv2.imwrite(str(image_path), np.full((10, 12, 3), value, dtype=np.uint8))
        (config.dataset.annotations / "{}.txt".format(index)).write_text(
            "0 0.5 0.5 0.5 0.5\n", encoding="utf-8"
        )

    data_path = prepare_dataset(config)
    data = json.loads(data_path.read_text(encoding="utf-8"))
    manifest = json.loads(config.dataset.manifest.read_text(encoding="utf-8"))
    assert data["names"] == {"0": "arrow"}
    assert len(manifest["samples"]) == 4
    assert {item["split"] for item in manifest["samples"]} == {"train", "val", "test"}
    for item in manifest["samples"]:
        assert (config.dataset.workspace / "images" / item["split"] / item["image"]).is_file()
