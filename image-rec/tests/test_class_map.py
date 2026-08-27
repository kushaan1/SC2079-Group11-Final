import pytest

from vision.class_map import classify_model_label, label_for_competition_id


@pytest.mark.parametrize(
    "label, expected_id",
    [
        ("Number 1", 11),
        ("9", 19),
        ("Alphabet A", 20),
        ("H", 27),
        ("Alphabet S", 28),
        ("Z", 35),
        ("Up Arrow", 36),
        ("arrow_left", 39),
        ("Stop sign", 40),
    ],
)
def test_target_aliases(label, expected_id):
    kind, competition_id, canonical = classify_model_label(label)
    assert kind == "target"
    assert competition_id == expected_id
    assert canonical == label_for_competition_id(expected_id)


@pytest.mark.parametrize("label, class_id", [("Bullseye", None), ("anything", 41), ("marker", 45)])
def test_bullseye_is_not_a_competition_target(label, class_id):
    assert classify_model_label(label, class_id) == ("bullseye", None, "Bullseye")


def test_unknown_model_label_is_preserved():
    assert classify_model_label("new-class") == ("unknown", None, "new-class")
