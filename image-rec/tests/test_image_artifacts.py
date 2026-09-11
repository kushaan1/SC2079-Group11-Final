from pathlib import Path

import cv2
import numpy as np

from pc_server.stitch import stitch_images
from pc_server.storage import AsyncImageStore
from vision.contracts import BoundingBox, Detection, DetectionResult


def test_async_store_persists_raw_and_obstacle_id_annotation(tmp_path):
    image = np.zeros((40, 50, 3), dtype=np.uint8)
    result = DetectionResult(
        object_id="obstacle-2",
        status="target",
        detections=(
            Detection("Right Arrow", 0.9, BoundingBox(5, 5, 30, 30), "target", 38),
        ),
    )
    store = AsyncImageStore(tmp_path, workers=1)
    raw_name, annotated_name = store.schedule(image, result)
    store.flush()
    store.close()

    raw = cv2.imread(raw_name)
    annotated = cv2.imread(annotated_name)
    assert raw is not None and annotated is not None
    assert int(raw.sum()) == 0
    assert int(annotated.sum()) > 0


def test_stitcher_builds_grid_in_timestamp_filename_order(tmp_path):
    input_dir = tmp_path / "raw"
    input_dir.mkdir()
    paths = []
    for index, value in enumerate((30, 90, 150)):
        path = input_dir / "{}.jpg".format(index)
        cv2.imwrite(str(path), np.full((10, 20, 3), value, dtype=np.uint8))
        paths.append(path)

    output = stitch_images(paths, tmp_path / "stitched" / "task1.jpg", columns=2)
    stitched = cv2.imread(str(output))
    assert Path(output).is_file()
    assert stitched.shape == (20, 40, 3)
