"""Create the mandatory Task 1 verification sheet from persisted raw captures."""

import argparse
import math
from pathlib import Path
from typing import Iterable, List


def stitch_images(image_paths: Iterable[Path], output_path: Path, columns: int = 3) -> Path:
    import cv2
    import numpy as np

    paths = list(image_paths)
    if not paths:
        raise ValueError("no images were supplied for stitching")
    if columns <= 0:
        raise ValueError("columns must be positive")

    images: List[object] = []
    for path in paths:
        image = cv2.imread(str(path))
        if image is None:
            raise ValueError("could not read {}".format(path))
        images.append(image)

    cell_width = max(image.shape[1] for image in images)
    cell_height = max(image.shape[0] for image in images)
    rows = int(math.ceil(len(images) / float(columns)))
    canvas = np.zeros((rows * cell_height, columns * cell_width, 3), dtype=np.uint8)
    for index, image in enumerate(images):
        row, column = divmod(index, columns)
        scale = min(cell_width / float(image.shape[1]), cell_height / float(image.shape[0]))
        resized = cv2.resize(
            image,
            (int(image.shape[1] * scale), int(image.shape[0] * scale)),
        )
        y_offset = row * cell_height + (cell_height - resized.shape[0]) // 2
        x_offset = column * cell_width + (cell_width - resized.shape[1]) // 2
        canvas[
            y_offset : y_offset + resized.shape[0],
            x_offset : x_offset + resized.shape[1],
        ] = resized

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), canvas):
        raise OSError("failed to write stitched image to {}".format(output_path))
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="directory containing raw JPGs")
    parser.add_argument("--output", type=Path, required=True, help="stitched JPG path")
    parser.add_argument("--columns", type=int, default=3)
    args = parser.parse_args()
    paths = sorted(args.input.glob("*.jpg"))
    stitch_images(paths, args.output, args.columns)
    print(args.output)


if __name__ == "__main__":
    main()
