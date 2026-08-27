import json
from pathlib import Path

import cv2
import numpy as np

from training.config import load_config_path
from training.dataset import create_placeholders, validate_dataset


def build_config(tmp_path, classes=("left", "right")):
    (tmp_path / "training/classes").mkdir(parents=True)
    (tmp_path / "training/configs").mkdir(parents=True)
    classes_path = tmp_path / "training/classes/test.json"
    classes_path.write_text(
        json.dumps({"schema_version": "1.0", "classes": list(classes)}),
        encoding="utf-8",
    )
    config = {
        "schema_version": "1.0",
        "task": "task2",
        "classes": "training/classes/test.json",
        "dataset": {
            "source_images": "training/images",
            "annotations": "training/annotations",
            "workspace": "training/.generated/test",
            "manifest": "training/manifests/test.json",
            "ratios": {"train": 0.7, "val": 0.2, "test": 0.1},
            "seed": 42,
            "required_class_splits": ["test"],
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
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return load_config_path(config_path, root=tmp_path)


def write_image(path, value=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    assert cv2.imwrite(str(path), np.full((20, 30, 3), value, dtype=np.uint8))


def test_creates_non_trainable_placeholder_without_overwriting_label(tmp_path):
    config = build_config(tmp_path, classes=("left",))
    image = config.dataset.source_images / "one.jpg"
    write_image(image)
    created = create_placeholders(config)
    assert created == (config.dataset.annotations / "one.txt.todo",)
    assert not (config.dataset.annotations / "one.txt").exists()
    assert create_placeholders(config) == ()


def test_placeholder_and_missing_classes_fail_validation(tmp_path):
    config = build_config(tmp_path)
    write_image(config.dataset.source_images / "one.jpg")
    create_placeholders(config)
    report = validate_dataset(config)
    assert not report.valid
    assert {issue.code for issue in report.issues} == {"placeholder_annotation", "missing_class"}


def test_validates_yolo_boxes_and_class_counts(tmp_path):
    config = build_config(tmp_path)
    write_image(config.dataset.source_images / "left.jpg", 10)
    write_image(config.dataset.source_images / "right.jpg", 20)
    config.dataset.annotations.mkdir(parents=True)
    (config.dataset.annotations / "left.txt").write_text("0 0.5 0.5 0.4 0.4\n", encoding="utf-8")
    (config.dataset.annotations / "right.txt").write_text("1 0.5 0.5 0.4 0.4\n", encoding="utf-8")
    report = validate_dataset(config)
    assert report.valid
    assert report.class_image_counts == {0: 1, 1: 1}
    assert report.class_box_counts == {0: 1, 1: 1}


def test_rejects_duplicate_images_and_out_of_bounds_box(tmp_path):
    config = build_config(tmp_path, classes=("left",))
    write_image(config.dataset.source_images / "a.jpg", 50)
    write_image(config.dataset.source_images / "b.jpg", 50)
    config.dataset.annotations.mkdir(parents=True)
    for name in ("a.txt", "b.txt"):
        (config.dataset.annotations / name).write_text("0 0.1 0.5 0.4 0.4\n", encoding="utf-8")
    report = validate_dataset(config)
    codes = [issue.code for issue in report.issues]
    assert codes.count("duplicate_image") == 2
    assert codes.count("invalid_box") == 2
