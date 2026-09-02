"""Extract the 31 glyph tiles from the SC2079 target reference sheet.

This utility is intentionally tied to the layout of the 1280 x 720 reference
image supplied with the project. It crops only the square target areas (not the
captions), maps them in reading order to IDs 11 through 41, and exports each
tile as a 640 x 640 PNG.

Example:
    python image-rec/misc/extract_target.py path/to/reference-sheet.jpg
"""

import argparse
from pathlib import Path
from typing import List, Sequence, Tuple

import cv2
import numpy as np


REFERENCE_SIZE = (1280, 720)
OUTPUT_SIZE = (640, 640)

# Pixel coordinates measured from the supplied 1280 x 720 reference image.
# Each crop is kept inside the striped square so the caption below is excluded.
COLUMN_X = (9, 168, 327, 486, 645, 804, 963, 1122)
ROW_Y = (9, 186, 363, 540)
CELL_SIZE = (150, 150)
ROW_LENGTHS = (8, 8, 8, 7)

DEFAULT_OUTPUT_DIR = (
    Path(__file__).resolve().parent / "resources" / "glyphs"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract IDs 11-41 from the fixed SC2079 target-sheet layout."
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Path to the 1280x720 target-sheet image.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Destination directory (default: image-rec/misc/resources/glyphs).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing ID.png files. Without this flag, extraction stops safely.",
    )
    return parser.parse_args()


def load_image(path: Path) -> np.ndarray:
    if not path.is_file():
        raise ValueError("Source image does not exist or is not a file: {}".format(path))

    # imdecode handles non-ASCII Windows paths more reliably than cv2.imread.
    encoded = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("OpenCV could not decode the source image: {}".format(path))
    return image


def validate_layout(image: np.ndarray) -> None:
    height, width = image.shape[:2]
    reference_width, reference_height = REFERENCE_SIZE
    source_ratio = width / float(height)
    reference_ratio = reference_width / float(reference_height)

    if abs(source_ratio - reference_ratio) > 0.01:
        raise ValueError(
            "Expected the fixed 16:9 target-sheet layout, but received {}x{}.".format(
                width, height
            )
        )


def crop_boxes(image_width: int, image_height: int) -> Sequence[Tuple[int, int, int, int]]:
    reference_width, reference_height = REFERENCE_SIZE
    cell_width, cell_height = CELL_SIZE
    scale_x = image_width / float(reference_width)
    scale_y = image_height / float(reference_height)
    boxes = []

    for row_index, row_length in enumerate(ROW_LENGTHS):
        y1 = round(ROW_Y[row_index] * scale_y)
        y2 = round((ROW_Y[row_index] + cell_height) * scale_y)
        for column_index in range(row_length):
            x1 = round(COLUMN_X[column_index] * scale_x)
            x2 = round((COLUMN_X[column_index] + cell_width) * scale_x)
            boxes.append((x1, y1, x2, y2))

    if len(boxes) != 31:
        raise RuntimeError("Internal layout error: expected 31 crop boxes.")
    return boxes


def save_png(path: Path, image: np.ndarray) -> None:
    success, encoded = cv2.imencode(
        ".png", image, (cv2.IMWRITE_PNG_COMPRESSION, 3)
    )
    if not success:
        raise OSError("OpenCV failed to encode {}".format(path))
    encoded.tofile(str(path))


def extract_targets(
    image: np.ndarray, output_dir: Path, overwrite: bool = False
) -> List[Path]:
    output_paths = [output_dir / "{}.png".format(target_id) for target_id in range(11, 42)]
    existing = [path for path in output_paths if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "Refusing to overwrite existing files: {}. Use --overwrite to replace them.".format(
                ", ".join(str(path) for path in existing)
            )
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    height, width = image.shape[:2]
    boxes = crop_boxes(width, height)

    for output_path, (x1, y1, x2, y2) in zip(output_paths, boxes):
        crop = image[y1:y2, x1:x2]
        if crop.size == 0:
            raise ValueError("Crop for {} is empty.".format(output_path.name))

        resized = cv2.resize(crop, OUTPUT_SIZE, interpolation=cv2.INTER_CUBIC)
        save_png(output_path, resized)

    return output_paths


def main() -> None:
    args = parse_args()
    try:
        image = load_image(args.source)
        validate_layout(image)
        output_paths = extract_targets(image, args.output_dir, args.overwrite)
    except (FileExistsError, OSError, ValueError) as error:
        raise SystemExit("Error: {}".format(error))

    print("Exported {} targets to {}".format(len(output_paths), args.output_dir.resolve()))


if __name__ == "__main__":
    main()
