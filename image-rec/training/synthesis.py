"""Deterministic synthetic Task 1 card and multi-stand compositing.

The module deliberately keeps glyph shape, card texture, stand appearance, and
environment separate.  It contains no GUI code so the renderer is testable on
headless training hosts; the interactive CLI lives in :mod:`training.synthesize`.
"""

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import cv2
import numpy as np


SCHEMA_VERSION = "1.0"
TARGET_IDS = tuple(range(11, 41))
BULLSEYE_ID = 41
PATTERN_FAMILIES = (
    "stripes",
    "checks",
    "dots",
    "scales",
    "diamonds",
    "camo",
    "marble",
    "weave",
)
STAND_ORIENTATIONS = ("front", "left", "right")
IMAGE_SUFFIXES = frozenset((".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"))
DEFAULT_CARD_SIZE = 640
DEFAULT_MIN_VISIBLE_FRACTION = 0.20
DEFAULT_MIN_PRIMARY_FRACTION = 0.50
MIN_GLYPH_BACKGROUND_LUMA = 48
DEFAULT_AUTO_PLACEMENT = {
    "minimum_stands": 1,
    "maximum_stands": 3,
    "far_stand_height": 0.25,
    "near_stand_height": 0.65,
    "primary_height_range": [0.45, 0.65],
    "distractor_height_range": [0.25, 0.50],
    "minimum_depth_gap": 0.025,
    "edge_crop_fraction": 0.30,
    "edge_visible_fraction_range": [0.75, 0.90],
    "maximum_roll_degrees": 3.0,
    "maximum_overlap": 0.45,
    "placement_attempts": 80,
}
DEFAULT_CONTACT_SHADOW = {
    "enabled": True,
    "opacity": 0.24,
    "width_fraction": 0.82,
    "height_fraction": 0.10,
    "blur_fraction": 0.035,
}


class SynthesisError(ValueError):
    """Raised when a recipe or synthesis input is unsafe or inconsistent."""


@dataclass(frozen=True)
class PatternCard:
    image: np.ndarray
    family: str
    parameters: Mapping[str, Any]
    source_sha256: Optional[str] = None


@dataclass
class VisibleObject:
    class_index: int
    competition_id: Optional[int]
    stand_id: str
    role: str
    kind: str
    orientation: Optional[str]
    full_mask: np.ndarray
    visible_mask: np.ndarray
    pattern: Optional[Mapping[str, Any]]


@dataclass(frozen=True)
class RenderedSample:
    image: np.ndarray
    annotations: Tuple[Tuple[int, float, float, float, float], ...]
    objects: Tuple[Mapping[str, Any], ...]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_seed(*parts: object) -> int:
    payload = "\x1f".join(str(item) for item in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def load_image(path: Path, unchanged: bool = False) -> np.ndarray:
    if not path.is_file():
        raise SynthesisError("image does not exist: {}".format(path))
    flags = cv2.IMREAD_UNCHANGED if unchanged else cv2.IMREAD_COLOR
    encoded = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(encoded, flags)
    if image is None:
        raise SynthesisError("OpenCV could not decode {}".format(path))
    return image


def normalized_quad(points: Sequence[Sequence[float]], width: int, height: int) -> List[List[float]]:
    array = np.asarray(points, dtype=np.float32)
    validate_pixel_quad(array, width, height)
    return [[float(x) / width, float(y) / height] for x, y in array]


def pixel_quad(
    points: Sequence[Sequence[float]],
    width: int,
    height: int,
    allowed_outside_fraction: float = 0.0,
) -> np.ndarray:
    array = np.asarray(points, dtype=np.float32)
    if array.shape != (4, 2) or not np.isfinite(array).all():
        raise SynthesisError("quadrilateral must contain four finite [x, y] points")
    if (
        float(array.max()) <= 1.0 + allowed_outside_fraction
        and float(array.min()) >= -allowed_outside_fraction
    ):
        array = array * np.asarray((width, height), dtype=np.float32)
    validate_pixel_quad(array, width, height, allowed_outside_fraction)
    return array.astype(np.float32)


def validate_pixel_quad(
    quad: np.ndarray,
    width: int,
    height: int,
    allowed_outside_fraction: float = 0.0,
) -> None:
    if quad.shape != (4, 2) or not np.isfinite(quad).all():
        raise SynthesisError("quadrilateral must contain four finite [x, y] points")
    if width <= 0 or height <= 0:
        raise SynthesisError("image dimensions must be positive")
    if not 0.0 <= allowed_outside_fraction <= 0.5:
        raise SynthesisError("allowed outside fraction must be between 0 and 0.5")
    tolerance = 1e-4
    if (
        np.any(quad[:, 0] < -width * allowed_outside_fraction - tolerance)
        or np.any(quad[:, 0] > width * (1.0 + allowed_outside_fraction) + tolerance)
        or np.any(quad[:, 1] < -height * allowed_outside_fraction - tolerance)
        or np.any(quad[:, 1] > height * (1.0 + allowed_outside_fraction) + tolerance)
    ):
        raise SynthesisError("quadrilateral extends outside the image")
    contour = quad.reshape((-1, 1, 2))
    if not cv2.isContourConvex(contour.astype(np.float32)):
        raise SynthesisError("quadrilateral must be convex and ordered around its perimeter")
    if abs(float(cv2.contourArea(contour))) < 16.0:
        raise SynthesisError("quadrilateral is too small")


def extract_glyph_mask(tile: np.ndarray) -> np.ndarray:
    """Extract an antialiased foreground mask from a light patterned glyph tile."""

    if tile is None or tile.ndim != 3 or tile.shape[2] < 3:
        raise SynthesisError("glyph tile must be a colour image")
    gray = cv2.cvtColor(tile[:, :, :3], cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    if component_count <= 1:
        raise SynthesisError("could not separate a glyph from its patterned background")
    candidates = sorted(range(1, component_count), key=lambda index: int(stats[index, cv2.CC_STAT_AREA]), reverse=True)
    keep = np.zeros_like(binary)
    largest_area = int(stats[candidates[0], cv2.CC_STAT_AREA])
    for component in candidates:
        area = int(stats[component, cv2.CC_STAT_AREA])
        if area >= max(16, int(largest_area * 0.04)):
            keep[labels == component] = 255
    expanded = cv2.dilate(keep, np.ones((3, 3), dtype=np.uint8), iterations=1)
    alpha = cv2.GaussianBlur(binary, (3, 3), 0.7).astype(np.float32) / 255.0
    alpha *= expanded.astype(np.float32) / 255.0
    area_fraction = float((alpha > 0.5).mean())
    if not 0.015 <= area_fraction <= 0.70:
        raise SynthesisError("extracted glyph area {:.3f} is implausible".format(area_fraction))
    return np.rint(alpha * 255.0).astype(np.uint8)


def load_glyph_masks(glyph_dir: Path) -> Dict[int, np.ndarray]:
    masks: Dict[int, np.ndarray] = {}
    for target_id in TARGET_IDS:
        tile = load_image(glyph_dir / "{}.png".format(target_id))
        masks[target_id] = extract_glyph_mask(tile)
    return masks


def save_glyph_masks(glyph_dir: Path, output_dir: Path, audit_path: Optional[Path] = None) -> Tuple[Path, ...]:
    masks = load_glyph_masks(glyph_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: List[Path] = []
    cells: List[np.ndarray] = []
    for target_id in TARGET_IDS:
        path = output_dir / "{}.png".format(target_id)
        _write_image(path, masks[target_id])
        paths.append(path)
        cell = cv2.cvtColor(masks[target_id], cv2.COLOR_GRAY2BGR)
        cv2.putText(cell, str(target_id), (12, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2, cv2.LINE_AA)
        cells.append(cell)
    if audit_path is not None:
        _write_image(audit_path, contact_sheet(cells, columns=6, cell_size=180))
    return tuple(paths)


def discover_custom_patterns(directory: Optional[Path]) -> Tuple[Path, ...]:
    if directory is None:
        return tuple()
    if not directory.is_dir():
        raise SynthesisError("custom pattern directory does not exist: {}".format(directory))
    paths = tuple(sorted((p for p in directory.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES), key=lambda p: p.as_posix().casefold()))
    if len({path.stem.casefold() for path in paths}) != len(paths):
        raise SynthesisError("custom pattern filenames must have unique stems")
    for path in paths:
        image = load_image(path)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if image.shape[0] < 16 or image.shape[1] < 16:
            raise SynthesisError("custom pattern is too small: {}".format(path))
        if float(gray.std()) < 6.0:
            raise SynthesisError("custom pattern has insufficient variation: {}".format(path))
        if int(gray.min()) < MIN_GLYPH_BACKGROUND_LUMA:
            raise SynthesisError(
                "custom pattern falls below the minimum black-glyph contrast of {} luma: {}".format(
                    MIN_GLYPH_BACKGROUND_LUMA, path
                )
            )
    return paths


def available_pattern_names(custom_patterns: Sequence[Path]) -> Tuple[str, ...]:
    return PATTERN_FAMILIES + tuple("custom:{}".format(path.stem) for path in custom_patterns)


def render_pattern_card(
    glyph_mask: np.ndarray,
    family: str,
    seed: int,
    size: int = DEFAULT_CARD_SIZE,
    custom_patterns: Sequence[Path] = (),
) -> PatternCard:
    rng = np.random.default_rng(seed)
    custom_by_name = {"custom:{}".format(path.stem): path for path in custom_patterns}
    if family in custom_by_name:
        source = custom_by_name[family]
        pattern, parameters = _tile_texture(load_image(source), size, seed)
        source_hash = file_sha256(source)
    elif family in PATTERN_FAMILIES:
        pattern, parameters = _procedural_pattern(family, size, rng)
        parameters = dict(parameters)
        parameters["seed"] = seed
        source_hash = None
    else:
        raise SynthesisError("unknown fuzz pattern family: {}".format(family))
    transform_rng = np.random.default_rng(seed ^ 0x2079A5)
    rotation = float(transform_rng.uniform(-12.0, 12.0))
    matrix = cv2.getRotationMatrix2D((size / 2.0, size / 2.0), rotation, 1.0)
    pattern = cv2.warpAffine(
        pattern,
        matrix,
        (size, size),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT_101,
    )
    parameters = dict(parameters)
    parameters["rotation_degrees"] = rotation
    pattern = _enforce_minimum_luma(pattern, MIN_GLYPH_BACKGROUND_LUMA)
    parameters["minimum_background_luma"] = MIN_GLYPH_BACKGROUND_LUMA
    parameters["observed_minimum_background_luma"] = int(
        cv2.cvtColor(pattern, cv2.COLOR_BGR2GRAY).min()
    )
    mask = cv2.resize(glyph_mask, (size, size), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    card = pattern.astype(np.float32)
    card *= (1.0 - mask[:, :, None])
    return PatternCard(np.clip(card, 0, 255).astype(np.uint8), family, parameters, source_hash)


def _procedural_pattern(family: str, size: int, rng: np.random.Generator) -> Tuple[np.ndarray, Dict[str, Any]]:
    oversample = 2
    dimension = size * oversample
    yy, xx = np.mgrid[0:dimension, 0:dimension].astype(np.float32)
    period = int(rng.integers(max(18, dimension // 24), max(30, dimension // 10)))
    phase = float(rng.uniform(0.0, period))
    dark_level = float(rng.uniform(50.0, 105.0))
    light_level = float(rng.uniform(140.0, 215.0))
    accent_level = float(rng.uniform(75.0, 165.0))
    dark = np.full(3, dark_level, dtype=np.float32) + rng.uniform(-14, 14, 3)
    light = np.full(3, light_level, dtype=np.float32) + rng.uniform(-12, 12, 3)
    accent = np.full(3, accent_level, dtype=np.float32) + rng.uniform(-18, 18, 3)
    canvas = np.empty((dimension, dimension, 3), dtype=np.float32)
    params: Dict[str, Any] = {
        "period": period / oversample,
        "phase": phase / oversample,
        "dark_bgr": [round(float(value), 3) for value in dark],
        "light_bgr": [round(float(value), 3) for value in light],
        "accent_bgr": [round(float(value), 3) for value in accent],
    }

    if family == "stripes":
        angle = float(rng.uniform(25.0, 65.0))
        coordinate = xx * math.cos(math.radians(angle)) + yy * math.sin(math.radians(angle)) + phase
        selector = (np.mod(coordinate, period) < period * 0.45)[:, :, None]
        canvas = np.where(selector, dark, light)
        params["angle_degrees"] = angle
    elif family == "checks":
        selector = ((np.floor((xx + phase) / period) + np.floor((yy + phase) / period)) % 2 == 0)[:, :, None]
        canvas = np.where(selector, dark, light)
    elif family == "dots":
        canvas[:] = light
        radius = max(3, int(period * rng.uniform(0.16, 0.28)))
        for cy in range(-period, dimension + period, period):
            for cx in range(-period, dimension + period, period):
                cv2.circle(canvas, (int(cx + phase), int(cy + phase)), radius, tuple(float(v) for v in dark), -1, cv2.LINE_AA)
        params["radius"] = radius / oversample
    elif family == "scales":
        canvas[:] = light
        radius = max(6, period // 2)
        for row, cy in enumerate(range(0, dimension + period, radius)):
            offset = 0 if row % 2 == 0 else radius
            for cx in range(-period, dimension + period, period):
                cv2.ellipse(canvas, (cx + offset, cy), (radius, radius), 0, 180, 360, tuple(float(v) for v in dark), max(2, radius // 4), cv2.LINE_AA)
    elif family == "diamonds":
        coordinate_a = np.mod(xx + yy + phase, period)
        coordinate_b = np.mod(xx - yy + phase, period)
        selector = ((coordinate_a < period * 0.32) | (coordinate_b < period * 0.32))[:, :, None]
        canvas = np.where(selector, dark, light)
    elif family == "camo":
        small = rng.random((max(4, dimension // 50), max(4, dimension // 50))).astype(np.float32)
        field = cv2.resize(small, (dimension, dimension), interpolation=cv2.INTER_CUBIC)
        field = cv2.GaussianBlur(field, (0, 0), sigmaX=max(3, dimension / 80.0))
        canvas[:] = light
        canvas[field < 0.42] = dark
        canvas[field > 0.62] = accent
    elif family == "marble":
        noise = rng.normal(0.0, 1.0, (dimension, dimension)).astype(np.float32)
        broad = cv2.GaussianBlur(noise, (0, 0), sigmaX=max(8, dimension / 30.0))
        fine = cv2.GaussianBlur(noise, (0, 0), sigmaX=max(2, dimension / 120.0))
        field = broad * 0.75 + fine * 0.25
        field = cv2.normalize(field, None, 0.0, 1.0, cv2.NORM_MINMAX)
        canvas = light[None, None, :] * (0.65 + 0.35 * field[:, :, None]) + dark[None, None, :] * (0.25 * (1.0 - field[:, :, None]))
    elif family == "weave":
        canvas[:] = light
        thickness = max(2, period // 7)
        for y in range(0, dimension, period):
            cv2.line(canvas, (0, y), (dimension, y), tuple(float(v) for v in dark), thickness, cv2.LINE_AA)
        for x in range(period // 2, dimension, period):
            cv2.line(canvas, (x, 0), (x, dimension), tuple(float(v) for v in accent), thickness, cv2.LINE_AA)
        dash = max(3, period // 4)
        for y in range(period // 2, dimension, period):
            for x in range(0, dimension, period):
                cv2.rectangle(canvas, (x, y - dash), (min(dimension, x + dash), y + dash), tuple(float(v) for v in dark), -1)
    else:
        raise AssertionError(family)

    canvas = cv2.resize(np.clip(canvas, 0, 255).astype(np.uint8), (size, size), interpolation=cv2.INTER_AREA)
    return canvas, params


def _enforce_minimum_luma(image: np.ndarray, minimum_luma: int) -> np.ndarray:
    result = image.astype(np.float32)
    for _ in range(2):
        gray = cv2.cvtColor(np.clip(result, 0, 255).astype(np.uint8), cv2.COLOR_BGR2GRAY)
        adjustment = np.maximum(0.0, minimum_luma - gray.astype(np.float32))
        result = np.minimum(255.0, result + adjustment[:, :, None])
    return np.clip(result, 0, 255).astype(np.uint8)


def _tile_texture(image: np.ndarray, size: int, seed: int) -> Tuple[np.ndarray, Dict[str, Any]]:
    rng = np.random.default_rng(seed)
    scale = float(rng.uniform(0.55, 1.45))
    target_width = max(16, int(image.shape[1] * scale))
    target_height = max(16, int(image.shape[0] * scale))
    resized = cv2.resize(
        image,
        (target_width, target_height),
        interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC,
    )
    repeats_x = int(math.ceil((size + target_width) / float(target_width)))
    repeats_y = int(math.ceil((size + target_height) / float(target_height)))
    tiled = np.tile(resized, (repeats_y, repeats_x, 1))
    x = int(rng.integers(0, target_width))
    y = int(rng.integers(0, target_height))
    return tiled[y : y + size, x : x + size].copy(), {
        "seed": seed,
        "scale": scale,
        "offset": [x, y],
        "source_tile_size": [int(image.shape[1]), int(image.shape[0])],
    }


def select_pattern(pattern_names: Sequence[str], scene_key: str, variant_index: int, stand_index: int) -> str:
    if not pattern_names:
        raise SynthesisError("at least one fuzz pattern is required")
    offset = stable_seed(scene_key) % len(pattern_names)
    return pattern_names[(offset + variant_index + stand_index) % len(pattern_names)]


def distractor_ids(primary_id: int, count: int, scene_key: str, variant_index: int) -> Tuple[int, ...]:
    available = [target_id for target_id in TARGET_IDS if target_id != primary_id]
    start = stable_seed(scene_key, variant_index, "distractors") % len(available)
    ordered = available[start:] + available[:start]
    if count <= len(ordered):
        return tuple(ordered[:count])
    return tuple(ordered[index % len(ordered)] for index in range(count))


def validate_recipe(recipe: Mapping[str, Any], root: Path) -> None:
    if recipe.get("schema_version") != SCHEMA_VERSION:
        raise SynthesisError("unsupported synthesis recipe schema_version")
    if not str(recipe.get("recipe_id", "")).strip():
        raise SynthesisError("recipe_id is required")
    if not str(recipe.get("source_group", "")).strip():
        raise SynthesisError("source_group is required")
    mode = recipe.get("mode")
    if mode == "in_scene":
        image_path = resolve_resource(root, recipe.get("source_image"))
        image = load_image(image_path)
        _validate_source_hash(image_path, recipe.get("source_sha256"))
        height, width = image.shape[:2]
        pixel_quad(recipe.get("target_quad", ()), width, height)
        for quad in recipe.get("bullseye_quads", []):
            pixel_quad(quad, width, height)
    elif mode in ("separated", "auto_background"):
        background_path = resolve_resource(root, recipe.get("background_image"))
        background = load_image(background_path)
        _validate_source_hash(background_path, recipe.get("background_sha256"))
        height, width = background.shape[:2]
        if mode == "auto_background":
            templates = recipe.get("templates")
            if not isinstance(templates, dict) or set(templates) != set(STAND_ORIENTATIONS):
                raise SynthesisError("auto_background requires front, left, and right templates")
            for orientation in STAND_ORIENTATIONS:
                template = load_template(resolve_resource(root, templates[orientation]), root)
                if template.get("orientation") != orientation:
                    raise SynthesisError("{} template does not declare orientation {}".format(orientation, orientation))
                if template.get("bullseye_mode") != "baked":
                    raise SynthesisError("automatic orientation templates require baked bullseyes")
            placement = recipe.get("placement", DEFAULT_AUTO_PLACEMENT)
            _validate_auto_placement(placement)
            _validate_perspective(recipe.get("perspective"), placement)
            _validate_contact_shadow(recipe.get("contact_shadow", DEFAULT_CONTACT_SHADOW))
            return
        stands = recipe.get("stands")
        if not isinstance(stands, list) or not stands:
            raise SynthesisError("a separated recipe needs at least one stand")
        primary_count = sum(1 for stand in stands if stand.get("role") == "primary")
        if primary_count != 1:
            raise SynthesisError("a separated recipe must contain exactly one primary stand")
        ids = [str(stand.get("instance_id", "")) for stand in stands]
        if any(not value for value in ids) or len(ids) != len(set(ids)):
            raise SynthesisError("stand instance_id values must be present and unique")
        z_values = [int(stand.get("z_index", index)) for index, stand in enumerate(stands)]
        if len(z_values) != len(set(z_values)):
            raise SynthesisError("stand z_index values must be unique")
        for stand in stands:
            if stand.get("role") not in ("primary", "distractor"):
                raise SynthesisError("stand role must be primary or distractor")
            try:
                allowed_outside = float(stand.get("allowed_outside_fraction", 0.0))
            except (TypeError, ValueError) as error:
                raise SynthesisError("stand allowed_outside_fraction is invalid") from error
            pixel_quad(
                stand.get("destination_quad", ()),
                width,
                height,
                allowed_outside,
            )
            load_template(resolve_resource(root, stand.get("template")), root)
    else:
        raise SynthesisError(
            "recipe mode must be in_scene, separated, or auto_background"
        )


def load_template(path: Path, root: Path) -> Mapping[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION or data.get("kind") != "stand_template":
        raise SynthesisError("invalid stand template recipe: {}".format(path))
    image_path = resolve_resource(root, data.get("image"))
    image = load_image(image_path, unchanged=True)
    if (
        image.ndim != 3
        or image.shape[2] != 4
        or not np.any(image[:, :, 3] < 255)
        or not np.any(image[:, :, 3] > 0)
    ):
        raise SynthesisError("stand template must be an RGBA image with transparency: {}".format(image_path))
    _validate_source_hash(image_path, data.get("image_sha256"))
    if data.get("bullseye_mode", "generated") not in ("generated", "baked"):
        raise SynthesisError("bullseye_mode must be generated or baked")
    if data.get("orientation") is not None and data.get("orientation") not in STAND_ORIENTATIONS:
        raise SynthesisError("stand template orientation must be front, left, or right")
    height, width = image.shape[:2]
    pixel_quad(data.get("target_quad", ()), width, height)
    for quad in data.get("bullseye_quads", []):
        pixel_quad(quad, width, height)
    return data


def _validate_auto_placement(raw: Any) -> None:
    if not isinstance(raw, Mapping):
        raise SynthesisError("placement settings must be an object")
    try:
        minimum = int(raw["minimum_stands"])
        maximum = int(raw["maximum_stands"])
        attempts = int(raw["placement_attempts"])
        roll = float(raw["maximum_roll_degrees"])
        overlap = float(raw["maximum_overlap"])
        far_height = float(raw["far_stand_height"])
        near_height = float(raw["near_stand_height"])
        depth_gap = float(raw["minimum_depth_gap"])
        edge_fraction = float(raw["edge_crop_fraction"])
        ranges = [
            tuple(float(value) for value in raw[name])
            for name in (
                "primary_height_range",
                "distractor_height_range",
                "edge_visible_fraction_range",
            )
        ]
    except (KeyError, TypeError, ValueError) as error:
        raise SynthesisError("placement settings are incomplete or invalid") from error
    if not 1 <= minimum <= maximum <= 3:
        raise SynthesisError("automatic stand count must remain within 1..3")
    if attempts <= 0 or not 0.0 <= roll <= 15.0 or not 0.0 <= overlap < 1.0:
        raise SynthesisError("automatic placement attempts, roll, or overlap are invalid")
    if any(len(values) != 2 or not 0.0 < values[0] <= values[1] <= 1.0 for values in ranges):
        raise SynthesisError("automatic placement ranges must be ordered fractions in (0, 1]")
    primary_range, distractor_range, edge_visible_range = ranges
    if not 0.0 < far_height < near_height <= 1.0:
        raise SynthesisError("far and near stand heights must be increasing fractions")
    if not far_height <= distractor_range[0] <= distractor_range[1] <= near_height:
        raise SynthesisError("distractor heights must fit the calibrated perspective range")
    if not far_height <= primary_range[0] <= primary_range[1] <= near_height:
        raise SynthesisError("primary heights must fit the calibrated perspective range")
    if primary_range[0] <= distractor_range[0]:
        raise SynthesisError("the primary height range must start above the smallest distractor")
    if not 0.0 < depth_gap < 0.25 or not 0.0 <= edge_fraction <= 0.5:
        raise SynthesisError("automatic depth gap or edge crop fraction is invalid")
    if edge_visible_range[0] < 0.5:
        raise SynthesisError("edge-cropped stands must remain at least half visible")


def _validate_perspective(raw: Any, settings: Mapping[str, Any]) -> None:
    if not isinstance(raw, Mapping):
        raise SynthesisError(
            "auto_background requires two-click perspective calibration; rerun configure-auto"
        )
    try:
        far = np.asarray(raw["far_point"], dtype=np.float32)
        near = np.asarray(raw["near_point"], dtype=np.float32)
    except (KeyError, TypeError, ValueError) as error:
        raise SynthesisError("perspective calibration points are invalid") from error
    if far.shape != (2,) or near.shape != (2,) or not np.isfinite((far, near)).all():
        raise SynthesisError("perspective calibration requires two finite [x, y] points")
    if np.any(far < 0.0) or np.any(far > 1.0) or np.any(near < 0.0) or np.any(near > 1.0):
        raise SynthesisError("perspective calibration points must be normalized within the image")
    if float(near[1] - far[1]) < 0.10:
        raise SynthesisError("near floor point must be at least 10% of image height below far point")
    far_height = float(settings["far_stand_height"])
    near_height = float(settings["near_stand_height"])
    if float(far[1]) < far_height + 0.01 or float(near[1]) < near_height + 0.01:
        raise SynthesisError("perspective points are too high to contain the configured stand sizes")
    if float(near[1]) > 0.98:
        raise SynthesisError("near floor point must leave a 2% image-bottom margin")


def _validate_contact_shadow(raw: Any) -> None:
    if not isinstance(raw, Mapping):
        raise SynthesisError("contact_shadow settings must be an object")
    try:
        opacity = float(raw["opacity"])
        width = float(raw["width_fraction"])
        height = float(raw["height_fraction"])
        blur = float(raw["blur_fraction"])
    except (KeyError, TypeError, ValueError) as error:
        raise SynthesisError("contact_shadow settings are incomplete or invalid") from error
    if not 0.0 <= opacity <= 1.0 or min(width, height, blur) <= 0.0:
        raise SynthesisError("contact shadow opacity and dimensions are invalid")


def resolve_resource(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise SynthesisError("recipe resource path is required")
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _validate_source_hash(path: Path, expected: Any) -> None:
    if not isinstance(expected, str) or len(expected) != 64:
        raise SynthesisError("recipe requires a SHA-256 source hash for {}".format(path))
    if expected != file_sha256(path):
        raise SynthesisError("source hash changed for {}".format(path))


def render_recipe_variant(
    recipe: Mapping[str, Any],
    root: Path,
    glyph_masks: Mapping[int, np.ndarray],
    bullseye_tile: np.ndarray,
    variant_index: int,
    custom_patterns: Sequence[Path] = (),
    min_visible_fraction: float = DEFAULT_MIN_VISIBLE_FRACTION,
    min_primary_fraction: float = DEFAULT_MIN_PRIMARY_FRACTION,
) -> RenderedSample:
    validate_recipe(recipe, root)
    if not 0 <= variant_index < len(TARGET_IDS):
        raise SynthesisError("variant_index must be in 0..29")
    if not 0.0 < min_visible_fraction <= 1.0 or not 0.0 < min_primary_fraction <= 1.0:
        raise SynthesisError("visibility fractions must be in (0, 1]")
    primary_id = TARGET_IDS[variant_index]
    scene_key = str(recipe["recipe_id"])
    names = available_pattern_names(custom_patterns)
    seed = int(recipe.get("seed", 2079))
    mode = recipe["mode"]
    if mode == "in_scene":
        base = load_image(resolve_resource(root, recipe["source_image"]))
        height, width = base.shape[:2]
        objects: List[VisibleObject] = []
        pattern_name = select_pattern(names, scene_key, variant_index, 0)
        pattern = render_pattern_card(glyph_masks[primary_id], pattern_name, stable_seed(seed, scene_key, variant_index, 0), custom_patterns=custom_patterns)
        target_quad = pixel_quad(recipe["target_quad"], width, height)
        base, target_mask = warp_opaque_tile(base, pattern.image, target_quad)
        objects.append(_visible_target(primary_id, "primary", "primary", target_mask, pattern))
        for bullseye_index, quad_data in enumerate(recipe.get("bullseye_quads", [])):
            quad = pixel_quad(quad_data, width, height)
            base, mask = warp_opaque_tile(base, bullseye_tile, quad)
            objects.append(_visible_bullseye("primary", "primary", mask, bullseye_index))
    elif mode == "separated":
        base, objects = _render_separated(
            recipe,
            root,
            glyph_masks,
            bullseye_tile,
            primary_id,
            variant_index,
            names,
            custom_patterns,
            seed,
        )
    else:
        separated = _automatic_variant_recipe(recipe, root, variant_index)
        base, objects = _render_separated(
            separated,
            root,
            glyph_masks,
            bullseye_tile,
            primary_id,
            variant_index,
            names,
            custom_patterns,
            seed,
        )
    return _finalize_sample(base, objects, min_visible_fraction, min_primary_fraction)


def _automatic_variant_recipe(
    recipe: Mapping[str, Any],
    root: Path,
    variant_index: int,
) -> Mapping[str, Any]:
    settings = dict(DEFAULT_AUTO_PLACEMENT)
    settings.update(dict(recipe.get("placement", {})))
    recipe_seed = int(recipe.get("seed", 2079))
    rng = np.random.default_rng(
        stable_seed(recipe_seed, recipe["recipe_id"], variant_index, "placement")
    )
    minimum = int(settings["minimum_stands"])
    maximum = int(settings["maximum_stands"])
    stand_count = minimum + ((variant_index + stable_seed(recipe["recipe_id"], "count")) % (maximum - minimum + 1))
    orientation_schedule = np.tile(np.arange(len(STAND_ORIENTATIONS)), 10)
    orientation_rng = np.random.default_rng(stable_seed(recipe["recipe_id"], "orientation"))
    orientation_rng.shuffle(orientation_schedule)
    primary_orientation = STAND_ORIENTATIONS[int(orientation_schedule[variant_index])]

    edge_schedule = np.arange(len(TARGET_IDS))
    edge_rng = np.random.default_rng(stable_seed(recipe["recipe_id"], "edge-crop"))
    edge_rng.shuffle(edge_schedule)
    edge_count = int(round(len(TARGET_IDS) * float(settings["edge_crop_fraction"])))
    edge_variant = variant_index in set(int(value) for value in edge_schedule[:edge_count])
    cropped_distractor = (
        int(rng.integers(0, stand_count - 1)) if edge_variant and stand_count > 1 else None
    )

    primary_range = tuple(settings["primary_height_range"])
    primary_height = float(rng.uniform(float(primary_range[0]), float(primary_range[1])))
    primary_bottom = _perspective_bottom_for_height(
        primary_height, recipe["perspective"], settings
    )
    primary_edge_crop = edge_variant and cropped_distractor is None

    primary_quad = _sample_automatic_quad(
        root,
        resolve_resource(root, recipe["templates"][primary_orientation]),
        primary_height,
        primary_bottom,
        float(settings["maximum_roll_degrees"]),
        float(settings["maximum_overlap"]),
        int(settings["placement_attempts"]),
        (),
        rng,
        primary_edge_crop,
        tuple(settings["edge_visible_fraction_range"]),
    )
    distractor_stands: List[Dict[str, Any]] = []
    occupied: List[np.ndarray] = [np.asarray(primary_quad, dtype=np.float32)]
    distractor_range = tuple(settings["distractor_height_range"])
    depth_height_limit = _perspective_height_for_bottom(
        primary_bottom - float(settings["minimum_depth_gap"]),
        recipe["perspective"],
        settings,
    )
    maximum_distractor_height = min(
        float(distractor_range[1]),
        primary_height - 1e-3,
        depth_height_limit,
    )
    if maximum_distractor_height < float(distractor_range[0]):
        raise SynthesisError("perspective calibration leaves no valid distractor depth")
    for index in range(stand_count - 1):
        orientation = STAND_ORIENTATIONS[int(rng.integers(0, len(STAND_ORIENTATIONS)))]
        height = float(
            rng.uniform(float(distractor_range[0]), maximum_distractor_height)
        )
        bottom = _perspective_bottom_for_height(height, recipe["perspective"], settings)
        edge_crop = edge_variant and cropped_distractor == index
        quad = _sample_automatic_quad(
            root,
            resolve_resource(root, recipe["templates"][orientation]),
            height,
            bottom,
            float(settings["maximum_roll_degrees"]),
            float(settings["maximum_overlap"]),
            int(settings["placement_attempts"]),
            occupied,
            rng,
            edge_crop,
            tuple(settings["edge_visible_fraction_range"]),
        )
        occupied.append(np.asarray(quad, dtype=np.float32))
        distractor_stands.append(
            {
                "role": "distractor",
                "orientation": orientation,
                "template": recipe["templates"][orientation],
                "destination_quad": quad,
                "apparent_height": height,
                "ground_contact_y": bottom,
                "edge_cropped": edge_crop,
                "allowed_outside_fraction": _outside_fraction(quad),
            }
        )
    distractor_stands.sort(key=lambda item: float(item["ground_contact_y"]))
    for index, stand in enumerate(distractor_stands):
        stand["instance_id"] = "distractor-{:02d}".format(index + 1)
        stand["z_index"] = index
    primary = {
        "instance_id": "primary",
        "role": "primary",
        "orientation": primary_orientation,
        "z_index": stand_count - 1,
        "template": recipe["templates"][primary_orientation],
        "destination_quad": primary_quad,
        "apparent_height": primary_height,
        "ground_contact_y": primary_bottom,
        "edge_cropped": primary_edge_crop,
        "allowed_outside_fraction": _outside_fraction(primary_quad),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "separated",
        "recipe_id": recipe["recipe_id"],
        "source_group": recipe["source_group"],
        "seed": recipe_seed,
        "background_image": recipe["background_image"],
        "background_sha256": recipe["background_sha256"],
        "stands": distractor_stands + [primary],
        "contact_shadow": dict(recipe.get("contact_shadow", DEFAULT_CONTACT_SHADOW)),
    }


def _sample_automatic_quad(
    root: Path,
    template_recipe_path: Path,
    height: float,
    bottom: float,
    maximum_roll: float,
    maximum_overlap: float,
    attempts: int,
    occupied: Sequence[np.ndarray],
    rng: np.random.Generator,
    edge_crop: bool,
    edge_visible_range: Sequence[float],
) -> List[List[float]]:
    template_data = load_template(template_recipe_path, root)
    template = load_image(resolve_resource(root, template_data["image"]), unchanged=True)
    aspect_ratio = template.shape[1] / float(template.shape[0])
    width = height * aspect_ratio
    if width >= 0.94:
        raise SynthesisError("stand template is too wide for the requested perspective scale")
    target_centre_x = float(np.asarray(template_data["target_quad"])[:, 0].mean())
    preferred_crop_left = target_centre_x >= 0.5
    for _ in range(attempts):
        if edge_crop:
            visible = float(
                rng.uniform(float(edge_visible_range[0]), float(edge_visible_range[1]))
            )
            crop_left = preferred_crop_left
            if abs(target_centre_x - 0.5) < 0.08:
                crop_left = bool(rng.integers(0, 2))
            centre_x = width * (visible - 0.5) if crop_left else 1.0 - width * (visible - 0.5)
        else:
            centre_x = float(
                rng.uniform(width / 2.0 + 0.02, 1.0 - width / 2.0 - 0.02)
            )
        angle = math.radians(float(rng.uniform(-maximum_roll, maximum_roll)))
        centre = np.asarray((centre_x, bottom - height / 2.0), dtype=np.float32)
        corners = np.asarray(
            ((-width / 2.0, -height / 2.0), (width / 2.0, -height / 2.0), (width / 2.0, height / 2.0), (-width / 2.0, height / 2.0)),
            dtype=np.float32,
        )
        rotation = np.asarray(((math.cos(angle), -math.sin(angle)), (math.sin(angle), math.cos(angle))), dtype=np.float32)
        quad = corners.dot(rotation.T) + centre
        if np.any(quad[:, 1] < 0.01) or np.any(quad[:, 1] > 0.99):
            continue
        if edge_crop and not (float(quad[:, 0].min()) < 0.0 or float(quad[:, 0].max()) > 1.0):
            continue
        if not edge_crop and (np.any(quad[:, 0] < 0.01) or np.any(quad[:, 0] > 0.99)):
            continue
        if all(_quad_overlap(quad, other) <= maximum_overlap for other in occupied):
            return [[float(x), float(y)] for x, y in quad]
    raise SynthesisError("could not place stands in the generic lower region without excessive overlap")


def _perspective_bottom_for_height(
    height: float,
    perspective: Mapping[str, Any],
    settings: Mapping[str, Any],
) -> float:
    far_y = float(perspective["far_point"][1])
    near_y = float(perspective["near_point"][1])
    far_height = float(settings["far_stand_height"])
    near_height = float(settings["near_stand_height"])
    progress = (height - far_height) / (near_height - far_height)
    return far_y + progress * (near_y - far_y)


def _perspective_height_for_bottom(
    bottom: float,
    perspective: Mapping[str, Any],
    settings: Mapping[str, Any],
) -> float:
    far_y = float(perspective["far_point"][1])
    near_y = float(perspective["near_point"][1])
    far_height = float(settings["far_stand_height"])
    near_height = float(settings["near_stand_height"])
    progress = (bottom - far_y) / (near_y - far_y)
    return far_height + progress * (near_height - far_height)


def _outside_fraction(quad: Sequence[Sequence[float]]) -> float:
    array = np.asarray(quad, dtype=np.float32)
    return max(
        0.0,
        -float(array[:, 0].min()),
        float(array[:, 0].max()) - 1.0,
        -float(array[:, 1].min()),
        float(array[:, 1].max()) - 1.0,
    ) + 1e-3


def _quad_overlap(first: np.ndarray, second: np.ndarray) -> float:
    first_x1, first_y1 = np.min(first, axis=0)
    first_x2, first_y2 = np.max(first, axis=0)
    second_x1, second_y1 = np.min(second, axis=0)
    second_x2, second_y2 = np.max(second, axis=0)
    intersection_width = max(0.0, min(float(first_x2), float(second_x2)) - max(float(first_x1), float(second_x1)))
    intersection_height = max(0.0, min(float(first_y2), float(second_y2)) - max(float(first_y1), float(second_y1)))
    intersection = intersection_width * intersection_height
    if intersection <= 0.0:
        return 0.0
    smaller = min(
        max(1e-9, float((first_x2 - first_x1) * (first_y2 - first_y1))),
        max(1e-9, float((second_x2 - second_x1) * (second_y2 - second_y1))),
    )
    return intersection / smaller


def _render_separated(
    recipe: Mapping[str, Any],
    root: Path,
    glyph_masks: Mapping[int, np.ndarray],
    bullseye_tile: np.ndarray,
    primary_id: int,
    variant_index: int,
    pattern_names: Sequence[str],
    custom_patterns: Sequence[Path],
    seed: int,
) -> Tuple[np.ndarray, List[VisibleObject]]:
    base = load_image(resolve_resource(root, recipe["background_image"]))
    scene_key = str(recipe["recipe_id"])
    stands = sorted(recipe["stands"], key=lambda item: int(item.get("z_index", 0)))
    distractors = distractor_ids(primary_id, sum(1 for item in stands if item["role"] == "distractor"), scene_key, variant_index)
    distractor_cursor = 0
    objects: List[VisibleObject] = []
    for stand_index, stand in enumerate(stands):
        target_id = primary_id if stand["role"] == "primary" else distractors[distractor_cursor]
        if stand["role"] == "distractor":
            distractor_cursor += 1
        pattern_name = select_pattern(pattern_names, scene_key, variant_index, stand_index)
        pattern = render_pattern_card(glyph_masks[target_id], pattern_name, stable_seed(seed, scene_key, variant_index, stand_index), custom_patterns=custom_patterns)
        template_data = load_template(resolve_resource(root, stand["template"]), root)
        template = load_image(resolve_resource(root, template_data["image"]), unchanged=True)
        local_bgr = template[:, :, :3].copy()
        local_alpha = template[:, :, 3]
        local_height, local_width = local_bgr.shape[:2]
        local_objects: List[VisibleObject] = []
        local_bgr, target_mask = warp_opaque_tile(local_bgr, pattern.image, pixel_quad(template_data["target_quad"], local_width, local_height))
        target_mask = cv2.bitwise_and(target_mask, local_alpha)
        orientation = stand.get("orientation", template_data.get("orientation"))
        local_objects.append(_visible_target(target_id, str(stand["instance_id"]), str(stand["role"]), target_mask, pattern, orientation))
        for bullseye_index, quad_data in enumerate(template_data.get("bullseye_quads", [])):
            bullseye_quad = pixel_quad(quad_data, local_width, local_height)
            if template_data.get("bullseye_mode", "generated") == "baked":
                mask = polygon_mask((local_height, local_width), bullseye_quad)
            else:
                local_bgr, mask = warp_opaque_tile(local_bgr, bullseye_tile, bullseye_quad)
            mask = cv2.bitwise_and(mask, local_alpha)
            local_objects.append(_visible_bullseye(str(stand["instance_id"]), str(stand["role"]), mask, bullseye_index, orientation))
        rendered_rgba = np.dstack((local_bgr, local_alpha))
        destination = pixel_quad(
            stand["destination_quad"],
            base.shape[1],
            base.shape[0],
            float(stand.get("allowed_outside_fraction", 0.0)),
        )
        warped_rgba, homography = warp_rgba(rendered_rgba, destination, (base.shape[1], base.shape[0]))
        occluder = warped_rgba[:, :, 3]
        for existing in objects:
            existing.visible_mask[occluder > 0] = 0
        shadow_settings = recipe.get("contact_shadow", {})
        if shadow_settings.get("enabled") is True:
            base = apply_contact_shadow(base, occluder, shadow_settings)
        base = alpha_composite(base, warped_rgba)
        for local_object in local_objects:
            warped_mask = cv2.warpPerspective(local_object.full_mask, homography, (base.shape[1], base.shape[0]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
            local_object.full_mask = warped_mask
            local_object.visible_mask = warped_mask.copy()
            objects.append(local_object)
    return base, objects


def _visible_target(
    target_id: int,
    stand_id: str,
    role: str,
    mask: np.ndarray,
    pattern: PatternCard,
    orientation: Optional[str] = None,
) -> VisibleObject:
    return VisibleObject(
        class_index=target_id - 11,
        competition_id=target_id,
        stand_id=stand_id,
        role=role,
        kind="target",
        orientation=orientation,
        full_mask=mask.copy(),
        visible_mask=mask.copy(),
        pattern={"family": pattern.family, "parameters": dict(pattern.parameters), "source_sha256": pattern.source_sha256},
    )


def _visible_bullseye(
    stand_id: str,
    role: str,
    mask: np.ndarray,
    index: int,
    orientation: Optional[str] = None,
) -> VisibleObject:
    return VisibleObject(30, None, stand_id, role, "bullseye", orientation, mask.copy(), mask.copy(), {"surface_index": index})


def warp_opaque_tile(base: np.ndarray, tile: np.ndarray, destination_quad: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    height, width = base.shape[:2]
    source = np.asarray(((0, 0), (tile.shape[1] - 1, 0), (tile.shape[1] - 1, tile.shape[0] - 1), (0, tile.shape[0] - 1)), dtype=np.float32)
    homography = cv2.getPerspectiveTransform(source, destination_quad.astype(np.float32))
    warped = cv2.warpPerspective(tile[:, :, :3], homography, (width, height), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    source_mask = np.full(tile.shape[:2], 255, dtype=np.uint8)
    mask = cv2.warpPerspective(source_mask, homography, (width, height), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    alpha = mask.astype(np.float32)[:, :, None] / 255.0
    result = np.clip(warped.astype(np.float32) * alpha + base.astype(np.float32) * (1.0 - alpha), 0, 255).astype(np.uint8)
    return result, mask


def polygon_mask(shape: Tuple[int, int], quad: np.ndarray) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    cv2.fillConvexPoly(mask, np.rint(quad).astype(np.int32), 255, cv2.LINE_AA)
    return mask


def warp_rgba(image: np.ndarray, destination_quad: np.ndarray, output_size: Tuple[int, int]) -> Tuple[np.ndarray, np.ndarray]:
    source = np.asarray(((0, 0), (image.shape[1] - 1, 0), (image.shape[1] - 1, image.shape[0] - 1), (0, image.shape[0] - 1)), dtype=np.float32)
    homography = cv2.getPerspectiveTransform(source, destination_quad.astype(np.float32))
    warped = cv2.warpPerspective(image, homography, output_size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    return warped, homography


def alpha_composite(base: np.ndarray, overlay: np.ndarray) -> np.ndarray:
    alpha = overlay[:, :, 3].astype(np.float32)[:, :, None] / 255.0
    return np.clip(overlay[:, :, :3].astype(np.float32) * alpha + base.astype(np.float32) * (1.0 - alpha), 0, 255).astype(np.uint8)


def apply_contact_shadow(base: np.ndarray, stand_alpha: np.ndarray, settings: Mapping[str, Any]) -> np.ndarray:
    ys, xs = np.nonzero(stand_alpha > 16)
    if not len(xs):
        return base
    x1, x2 = int(xs.min()), int(xs.max()) + 1
    y1, y2 = int(ys.min()), int(ys.max()) + 1
    stand_width = max(1, x2 - x1)
    stand_height = max(1, y2 - y1)
    centre = ((x1 + x2) // 2, min(base.shape[0] - 1, y2 - 1))
    axes = (
        max(1, int(stand_width * float(settings["width_fraction"]) / 2.0)),
        max(1, int(stand_height * float(settings["height_fraction"]) / 2.0)),
    )
    shadow = np.zeros(base.shape[:2], dtype=np.uint8)
    cv2.ellipse(shadow, centre, axes, 0.0, 0.0, 360.0, 255, -1, cv2.LINE_AA)
    sigma = max(1.0, stand_width * float(settings["blur_fraction"]))
    shadow = cv2.GaussianBlur(shadow, (0, 0), sigmaX=sigma, sigmaY=max(1.0, sigma * 0.45))
    strength = shadow.astype(np.float32)[:, :, None] / 255.0 * float(settings["opacity"])
    return np.clip(base.astype(np.float32) * (1.0 - strength), 0, 255).astype(np.uint8)


def _finalize_sample(
    image: np.ndarray,
    visible_objects: Sequence[VisibleObject],
    min_visible_fraction: float,
    min_primary_fraction: float,
) -> RenderedSample:
    annotations: List[Tuple[int, float, float, float, float]] = []
    metadata: List[Mapping[str, Any]] = []
    primary_seen = False
    for item in visible_objects:
        full_count = int(np.count_nonzero(item.full_mask > 16))
        visible_count = int(np.count_nonzero(item.visible_mask > 16))
        fraction = visible_count / float(full_count) if full_count else 0.0
        required = min_primary_fraction if item.role == "primary" and item.kind == "target" else min_visible_fraction
        included = fraction >= required and visible_count > 0
        box = mask_to_yolo_box(item.visible_mask) if included else None
        if box is not None:
            annotations.append((item.class_index,) + box)
            if item.role == "primary" and item.kind == "target":
                primary_seen = True
        metadata.append(
            {
                "class_index": item.class_index,
                "competition_id": item.competition_id,
                "stand_id": item.stand_id,
                "role": item.role,
                "kind": item.kind,
                "orientation": item.orientation,
                "visible_fraction": fraction,
                "included": box is not None,
                "box": list(box) if box is not None else None,
                "pattern": item.pattern,
            }
        )
    if not primary_seen:
        raise SynthesisError("primary target is insufficiently visible")
    if not annotations:
        raise SynthesisError("rendered sample has no visible annotations")
    return RenderedSample(image, tuple(annotations), tuple(metadata))


def mask_to_yolo_box(mask: np.ndarray) -> Optional[Tuple[float, float, float, float]]:
    ys, xs = np.nonzero(mask > 16)
    if not len(xs):
        return None
    height, width = mask.shape[:2]
    x1, x2 = int(xs.min()), int(xs.max()) + 1
    y1, y2 = int(ys.min()), int(ys.max()) + 1
    return (
        ((x1 + x2) / 2.0) / width,
        ((y1 + y2) / 2.0) / height,
        (x2 - x1) / float(width),
        (y2 - y1) / float(height),
    )


def generate_recipe(
    recipe_path: Path,
    root: Path,
    glyph_dir: Path,
    output_images: Path,
    output_annotations: Path,
    custom_pattern_dir: Optional[Path] = None,
    overwrite: bool = False,
    jpeg_quality: int = 95,
) -> Tuple[Path, ...]:
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    validate_recipe(recipe, root)
    glyph_masks = load_glyph_masks(glyph_dir)
    bullseye = load_image(glyph_dir / "41.png")
    custom_patterns = discover_custom_patterns(custom_pattern_dir)
    scene_hash = hashlib.sha256(json.dumps(recipe, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:12]
    relative_dir = Path("scene-{}".format(scene_hash))
    planned: List[Tuple[Path, Path, Path]] = []
    for variant_index in range(len(TARGET_IDS)):
        stem = "sample-{:03d}".format(variant_index)
        planned.append((output_images / relative_dir / (stem + ".jpg"), output_annotations / relative_dir / (stem + ".txt"), output_annotations / relative_dir / (stem + ".meta.json")))
    existing = [path for trio in planned for path in trio if path.exists()]
    if existing and not overwrite:
        raise SynthesisError("refusing to overwrite {} existing synthesis output(s)".format(len(existing)))
    written: List[Path] = []
    for variant_index, (image_path, label_path, meta_path) in enumerate(planned):
        rendered = render_recipe_variant(recipe, root, glyph_masks, bullseye, variant_index, custom_patterns)
        _write_image(image_path, rendered.image, jpeg_quality)
        label_path.parent.mkdir(parents=True, exist_ok=True)
        label_path.write_text("".join("{} {:.8f} {:.8f} {:.8f} {:.8f}\n".format(*row) for row in rendered.annotations), encoding="utf-8")
        metadata = {
            "schema_version": SCHEMA_VERSION,
            "synthetic": True,
            "recipe": _resource_value(recipe_path, root),
            "recipe_sha256": file_sha256(recipe_path),
            "source_group": str(recipe["source_group"]),
            "recipe_id": str(recipe["recipe_id"]),
            "variant_index": variant_index,
            "primary_competition_id": TARGET_IDS[variant_index],
            "objects": list(rendered.objects),
        }
        meta_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        written.append(image_path)
    return tuple(written)


def create_audit_sheet(
    images: Sequence[Path],
    annotation_root: Path,
    output: Path,
    columns: int = 4,
    image_root: Optional[Path] = None,
) -> Path:
    cells: List[np.ndarray] = []
    relative_root = image_root.resolve() if image_root is not None else _common_parent(images)
    for image_path in images:
        image = load_image(image_path)
        relative = image_path.resolve().relative_to(relative_root)
        label_path = (annotation_root / relative).with_suffix(".txt")
        if not label_path.is_file():
            raise SynthesisError("annotation not found for {}".format(image_path))
        height, width = image.shape[:2]
        for line in label_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            class_id, x, y, box_width, box_height = line.split()
            x, y, box_width, box_height = map(float, (x, y, box_width, box_height))
            x1, y1 = int((x - box_width / 2) * width), int((y - box_height / 2) * height)
            x2, y2 = int((x + box_width / 2) * width), int((y + box_height / 2) * height)
            cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 255), max(2, width // 800))
            cv2.putText(image, class_id, (x1, max(20, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2, cv2.LINE_AA)
        cells.append(image)
    _write_image(output, contact_sheet(cells, columns=columns, cell_size=320))
    return output


def contact_sheet(images: Sequence[np.ndarray], columns: int, cell_size: int) -> np.ndarray:
    if not images:
        raise SynthesisError("cannot create an empty audit sheet")
    rows = int(math.ceil(len(images) / float(columns)))
    sheet = np.full((rows * cell_size, columns * cell_size, 3), 235, dtype=np.uint8)
    for index, image in enumerate(images):
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        scale = min(cell_size / float(image.shape[1]), cell_size / float(image.shape[0]))
        resized = cv2.resize(image[:, :, :3], (max(1, int(image.shape[1] * scale)), max(1, int(image.shape[0] * scale))), interpolation=cv2.INTER_AREA)
        row, column = divmod(index, columns)
        y = row * cell_size + (cell_size - resized.shape[0]) // 2
        x = column * cell_size + (cell_size - resized.shape[1]) // 2
        sheet[y : y + resized.shape[0], x : x + resized.shape[1]] = resized
    return sheet


def _common_parent(paths: Sequence[Path]) -> Path:
    if not paths:
        raise SynthesisError("no image paths supplied")
    parts = [path.resolve().parts for path in paths]
    common: List[str] = []
    for values in zip(*parts):
        if len(set(values)) != 1:
            break
        common.append(values[0])
    return Path(*common) if common else paths[0].parent


def _resource_value(path: Path, root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _write_image(path: Path, image: np.ndarray, jpeg_quality: int = 95) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    parameters: List[int] = []
    if suffix in (".jpg", ".jpeg"):
        parameters = [cv2.IMWRITE_JPEG_QUALITY, int(jpeg_quality)]
    success, encoded = cv2.imencode(suffix, image, parameters)
    if not success:
        raise OSError("OpenCV failed to encode {}".format(path))
    encoded.tofile(str(path))
