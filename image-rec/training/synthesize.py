"""Configure, generate, and audit synthetic Task 1 training images."""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import cv2
import numpy as np

from .config import IMAGE_REC_ROOT
from .synthesis import (
    IMAGE_SUFFIXES,
    SCHEMA_VERSION,
    SynthesisError,
    create_audit_sheet,
    file_sha256,
    generate_recipe,
    load_image,
    normalized_quad,
    save_glyph_masks,
)


DEFAULT_GLYPH_DIR = IMAGE_REC_ROOT / "misc" / "resources" / "glyphs"
DEFAULT_MASK_DIR = IMAGE_REC_ROOT / "training" / ".generated" / "synthesis" / "glyph-masks"
DEFAULT_SYNTHETIC_IMAGES = IMAGE_REC_ROOT / "training" / "training_set" / "synthetic"
DEFAULT_SYNTHETIC_ANNOTATIONS = IMAGE_REC_ROOT / "training" / "annotations" / "task1" / "synthetic"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    masks = subparsers.add_parser("build-masks", help="extract reusable glyph masks and an audit sheet")
    masks.add_argument("--glyph-dir", type=Path, default=DEFAULT_GLYPH_DIR)
    masks.add_argument("--output-dir", type=Path, default=DEFAULT_MASK_DIR)
    masks.add_argument("--audit", type=Path, default=DEFAULT_MASK_DIR.parent / "glyph-mask-audit.jpg")

    in_scene = subparsers.add_parser("configure-in-scene", help="click card surfaces in a photo containing a stand")
    _add_recipe_arguments(in_scene)
    in_scene.add_argument("--image", type=Path, required=True)
    in_scene.add_argument("--bullseyes", type=int, default=0, help="number of visible bullseye surfaces to register")

    template = subparsers.add_parser("configure-template", help="register surfaces on an RGBA stand cutout")
    template.add_argument("--image", type=Path, required=True)
    template.add_argument("--output", type=Path, required=True)
    template.add_argument("--bullseyes", type=int, default=0)
    template.add_argument("--overwrite", action="store_true")

    scene = subparsers.add_parser("configure-scene", help="place one primary and any number of distractor stands")
    _add_recipe_arguments(scene)
    scene.add_argument("--background", type=Path, required=True)
    scene.add_argument(
        "--stand",
        action="append",
        required=True,
        metavar="ROLE:TEMPLATE_JSON",
        help="stand in far-to-near order; ROLE is primary or distractor",
    )

    generate = subparsers.add_parser("generate", help="generate all 30 primary-target variants")
    generate.add_argument("--recipe", type=Path, required=True)
    generate.add_argument("--glyph-dir", type=Path, default=DEFAULT_GLYPH_DIR)
    generate.add_argument("--custom-patterns", type=Path)
    generate.add_argument("--output-images", type=Path, default=DEFAULT_SYNTHETIC_IMAGES)
    generate.add_argument("--output-annotations", type=Path, default=DEFAULT_SYNTHETIC_ANNOTATIONS)
    generate.add_argument("--jpeg-quality", type=int, default=95)
    generate.add_argument("--overwrite", action="store_true")

    audit = subparsers.add_parser("audit", help="render a labelled contact sheet for generated images")
    audit.add_argument("--images", type=Path, default=DEFAULT_SYNTHETIC_IMAGES)
    audit.add_argument("--annotations", type=Path, default=DEFAULT_SYNTHETIC_ANNOTATIONS)
    audit.add_argument("--output", type=Path, required=True)
    audit.add_argument("--columns", type=int, default=4)
    return parser.parse_args()


def _add_recipe_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--recipe-id", required=True)
    parser.add_argument("--source-group", required=True)
    parser.add_argument("--seed", type=int, default=2079)
    parser.add_argument("--overwrite", action="store_true")


def _relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(IMAGE_REC_ROOT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _write_json(path: Path, payload: Dict[str, Any], overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise SynthesisError("refusing to overwrite {}".format(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _display_image(image: np.ndarray) -> np.ndarray:
    if image.ndim == 3 and image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2RGBA)
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def _click_quad(image: np.ndarray, title: str) -> List[List[float]]:
    try:
        import matplotlib.pyplot as plt
    except ImportError as error:
        raise SynthesisError("interactive configuration requires matplotlib on a desktop host") from error
    figure, axis = plt.subplots()
    axis.imshow(_display_image(image))
    axis.set_title(title + "\nClick top-left, top-right, bottom-right, bottom-left")
    points = plt.ginput(4, timeout=-1, show_clicks=True)
    plt.close(figure)
    if len(points) != 4:
        raise SynthesisError("surface configuration was cancelled before four corners were selected")
    return normalized_quad(points, image.shape[1], image.shape[0])


def _surface_quads(image: np.ndarray, bullseye_count: int) -> Tuple[List[List[float]], List[List[List[float]]]]:
    if bullseye_count < 0:
        raise SynthesisError("bullseye count cannot be negative")
    target = _click_quad(image, "Target card")
    bullseyes = [_click_quad(image, "Bullseye surface {}".format(index + 1)) for index in range(bullseye_count)]
    return target, bullseyes


def _configure_in_scene(args: argparse.Namespace) -> None:
    image = load_image(args.image)
    target, bullseyes = _surface_quads(image, args.bullseyes)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "mode": "in_scene",
        "recipe_id": args.recipe_id,
        "source_group": args.source_group,
        "seed": args.seed,
        "source_image": _relative(args.image),
        "source_sha256": file_sha256(args.image),
        "target_quad": target,
        "bullseye_quads": bullseyes,
    }
    _write_json(args.output, payload, args.overwrite)


def _configure_template(args: argparse.Namespace) -> None:
    image = load_image(args.image, unchanged=True)
    if (
        image.ndim != 3
        or image.shape[2] != 4
        or not np.any(image[:, :, 3] < 255)
        or not np.any(image[:, :, 3] > 0)
    ):
        raise SynthesisError("stand templates must be RGBA PNGs with a real transparency mask")
    target, bullseyes = _surface_quads(image, args.bullseyes)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "kind": "stand_template",
        "image": _relative(args.image),
        "image_sha256": file_sha256(args.image),
        "target_quad": target,
        "bullseye_quads": bullseyes,
    }
    _write_json(args.output, payload, args.overwrite)


def _parse_stand(value: str) -> Tuple[str, Path]:
    role, separator, raw_path = value.partition(":")
    if separator != ":" or role not in ("primary", "distractor") or not raw_path:
        raise SynthesisError("--stand must be primary:TEMPLATE_JSON or distractor:TEMPLATE_JSON")
    return role, Path(raw_path)


def _configure_scene(args: argparse.Namespace) -> None:
    background = load_image(args.background)
    parsed = [_parse_stand(value) for value in args.stand]
    if sum(1 for role, _ in parsed if role == "primary") != 1:
        raise SynthesisError("configure-scene requires exactly one primary stand")
    stands: List[Dict[str, Any]] = []
    for index, (role, template_path) in enumerate(parsed):
        destination = _click_quad(background, "Place {} stand {} (far-to-near order)".format(role, index + 1))
        stands.append(
            {
                "instance_id": "stand-{:02d}".format(index + 1),
                "role": role,
                "z_index": index,
                "template": _relative(template_path),
                "destination_quad": destination,
            }
        )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "mode": "separated",
        "recipe_id": args.recipe_id,
        "source_group": args.source_group,
        "seed": args.seed,
        "background_image": _relative(args.background),
        "background_sha256": file_sha256(args.background),
        "stands": stands,
    }
    _write_json(args.output, payload, args.overwrite)


def _discover_images(directory: Path) -> Tuple[Path, ...]:
    if not directory.is_dir():
        raise SynthesisError("image directory does not exist: {}".format(directory))
    return tuple(sorted((path for path in directory.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES), key=lambda path: path.as_posix().casefold()))


def main() -> None:
    args = parse_args()
    try:
        if args.command == "build-masks":
            paths = save_glyph_masks(args.glyph_dir, args.output_dir, args.audit)
            print("wrote {} glyph masks and {}".format(len(paths), args.audit))
        elif args.command == "configure-in-scene":
            _configure_in_scene(args)
            print(args.output)
        elif args.command == "configure-template":
            _configure_template(args)
            print(args.output)
        elif args.command == "configure-scene":
            _configure_scene(args)
            print(args.output)
        elif args.command == "generate":
            if not 1 <= args.jpeg_quality <= 100:
                raise SynthesisError("jpeg quality must be in 1..100")
            paths = generate_recipe(
                args.recipe,
                IMAGE_REC_ROOT,
                args.glyph_dir,
                args.output_images,
                args.output_annotations,
                args.custom_patterns,
                args.overwrite,
                args.jpeg_quality,
            )
            print("generated {} images under {}".format(len(paths), args.output_images))
        elif args.command == "audit":
            if args.columns <= 0:
                raise SynthesisError("columns must be positive")
            images = _discover_images(args.images)
            print(create_audit_sheet(images, args.annotations, args.output, args.columns, args.images))
    except (OSError, SynthesisError, json.JSONDecodeError) as error:
        raise SystemExit("Error: {}".format(error))


if __name__ == "__main__":
    main()
