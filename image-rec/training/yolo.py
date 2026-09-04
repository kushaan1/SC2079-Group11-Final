"""Shared YOLO annotation serialization contract."""

from typing import Sequence


YOLO_COORDINATE_DECIMALS = 8
YOLO_COORDINATE_TOLERANCE = 10.0 ** -YOLO_COORDINATE_DECIMALS


def format_yolo_row(row: Sequence[float]) -> str:
    """Serialize one class-and-box row using the dataset's fixed precision."""

    if len(row) != 5:
        raise ValueError("a YOLO row must contain a class index and four coordinates")
    coordinates = " ".join(
        format(float(value), ".{}f".format(YOLO_COORDINATE_DECIMALS))
        for value in row[1:]
    )
    return "{} {}\n".format(int(row[0]), coordinates)
