"""Mapping between model labels and the SC2079 competition image IDs."""

import re
from typing import Dict, Optional, Tuple


COMPETITION_LABELS = {
    11: "Number 1",
    12: "Number 2",
    13: "Number 3",
    14: "Number 4",
    15: "Number 5",
    16: "Number 6",
    17: "Number 7",
    18: "Number 8",
    19: "Number 9",
    20: "Alphabet A",
    21: "Alphabet B",
    22: "Alphabet C",
    23: "Alphabet D",
    24: "Alphabet E",
    25: "Alphabet F",
    26: "Alphabet G",
    27: "Alphabet H",
    28: "Alphabet S",
    29: "Alphabet T",
    30: "Alphabet U",
    31: "Alphabet V",
    32: "Alphabet W",
    33: "Alphabet X",
    34: "Alphabet Y",
    35: "Alphabet Z",
    36: "Up Arrow",
    37: "Down Arrow",
    38: "Right Arrow",
    39: "Left Arrow",
    40: "Stop sign",
}

LEGACY_BULLSEYE_CLASS_IDS = frozenset((41, 45))


def _normalise(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", label.strip().lower())


_ALIASES: Dict[str, int] = {}
for _competition_id, _label in COMPETITION_LABELS.items():
    _ALIASES[_normalise(_label)] = _competition_id

for _number in range(1, 10):
    _ALIASES[str(_number)] = 10 + _number
    _ALIASES["number{}".format(_number)] = 10 + _number

for _competition_id, _letter in zip(
    list(range(20, 28)) + list(range(28, 36)),
    "ABCDEFGHSTUVWXYZ",
):
    _ALIASES[_normalise(_letter)] = _competition_id

_ALIASES.update(
    {
        "arrowup": 36,
        "up": 36,
        "arrowdown": 37,
        "down": 37,
        "arrowright": 38,
        "right": 38,
        "arrowleft": 39,
        "left": 39,
        "stop": 40,
        "stopsign": 40,
    }
)

_BULLSEYE_ALIASES = frozenset(
    ("bullseye", "bullseyemarker", "bullseyes", "targetmarker", "marker")
)


def classify_model_label(
    label: str, model_class_id: Optional[int] = None
) -> Tuple[str, Optional[int], str]:
    """Return ``(kind, competition_id, canonical_label)`` for a model class.

    ``kind`` is one of ``target``, ``bullseye`` or ``unknown``. Legacy model
    class IDs 41 and 45 are treated as bull's-eyes but are never exposed as
    competition target IDs.
    """

    key = _normalise(label)
    if model_class_id in LEGACY_BULLSEYE_CLASS_IDS or key in _BULLSEYE_ALIASES:
        return "bullseye", None, "Bullseye"

    competition_id = _ALIASES.get(key)
    if competition_id is None:
        return "unknown", None, label.strip() or "Unknown"
    return "target", competition_id, COMPETITION_LABELS[competition_id]


def label_for_competition_id(competition_id: int) -> str:
    """Look up a canonical label, raising ``KeyError`` for invalid IDs."""

    return COMPETITION_LABELS[competition_id]
