import ast
import sys
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[1]


def test_rpi_sources_parse_as_python37():
    paths = list((MODULE_ROOT / "rpi").rglob("*.py"))
    paths.extend((MODULE_ROOT / name) for name in ("test1_runner_rpi.py", "test2_runner_rpi.py"))
    assert paths
    for path in paths:
        source = path.read_text(encoding="utf-8")
        if sys.version_info >= (3, 8):
            ast.parse(source, filename=str(path), feature_version=(3, 7))
        else:
            ast.parse(source, filename=str(path))


def test_rpi_sources_do_not_import_heavy_or_modern_camera_stacks():
    forbidden = ("import ultralytics", "import torch", "import tensorflow", "picamera2", "libcamera")
    for path in (MODULE_ROOT / "rpi").rglob("*.py"):
        source = path.read_text(encoding="utf-8").lower()
        assert not any(token in source for token in forbidden), "forbidden Pi dependency in {}".format(
            path
        )
