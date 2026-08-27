import json

from training.config import load_task_config
from vision.class_map import COMPETITION_LABELS


def test_task1_registry_covers_targets_and_bullseye_without_reordering_ids():
    config = load_task_config("task1")
    targets = [item for item in config.classes if item.competition_id is not None]
    bullseyes = [item for item in config.classes if item.competition_id is None]
    assert [item.competition_id for item in targets] == list(range(11, 41))
    assert [item.name for item in targets] == [COMPETITION_LABELS[index] for index in range(11, 41)]
    assert [item.name for item in bullseyes] == ["Bullseye"]


def test_task_datasets_are_separate_and_task2_labels_match_pi_metadata():
    task1 = load_task_config("task1")
    task2 = load_task_config("task2")
    assert task1.dataset.source_images != task2.dataset.source_images
    with (task2.root / "rpi/models/arrow-labels.json").open("r", encoding="utf-8") as handle:
        deployed_labels = json.load(handle)
    assert deployed_labels == list(task2.class_names)
