import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from training.synthesis import (
    PATTERN_FAMILIES,
    SynthesisError,
    discover_custom_patterns,
    distractor_ids,
    extract_glyph_mask,
    file_sha256,
    generate_recipe,
    render_pattern_card,
    render_recipe_variant,
    select_pattern,
)


def write_image(path, image):
    path.parent.mkdir(parents=True, exist_ok=True)
    assert cv2.imwrite(str(path), image)


def glyph_masks():
    masks = {}
    for target_id in range(11, 41):
        mask = np.zeros((64, 64), dtype=np.uint8)
        cv2.rectangle(mask, (18, 10), (45, 53), 255, -1)
        cv2.circle(mask, (32, 32), 8, 0, -1)
        masks[target_id] = mask
    return masks


def bullseye_tile():
    tile = np.zeros((64, 64, 3), dtype=np.uint8)
    for size in (52, 34, 16):
        cv2.rectangle(tile, ((64 - size) // 2, (64 - size) // 2), ((64 + size) // 2, (64 + size) // 2), (230, 230, 230), 3)
    return tile


def test_extracts_glyph_without_filling_internal_holes():
    tile = np.full((160, 160, 3), 220, dtype=np.uint8)
    for offset in range(-160, 320, 20):
        cv2.line(tile, (offset, 0), (offset + 160, 160), (160, 160, 160), 7)
    cv2.circle(tile, (80, 80), 48, (0, 0, 0), -1)
    cv2.circle(tile, (80, 80), 20, (220, 220, 220), -1)
    mask = extract_glyph_mask(tile)
    assert mask[80, 80] == 0
    assert mask[80, 42] > 240
    assert mask[5, 5] == 0


@pytest.mark.parametrize("family", PATTERN_FAMILIES)
def test_procedural_patterns_are_deterministic_and_keep_the_glyph_black(family):
    mask = glyph_masks()[11]
    first = render_pattern_card(mask, family, 123, size=96)
    second = render_pattern_card(mask, family, 123, size=96)
    assert np.array_equal(first.image, second.image)
    assert float(first.image.std()) > 5.0
    assert int(first.image[30:65, 30:65].min()) == 0


def test_pattern_schedule_and_distractors_are_balanced_and_distinct():
    names = PATTERN_FAMILIES
    selected = [select_pattern(names, "scene-a", index, 0) for index in range(len(names))]
    assert set(selected) == set(names)
    distractors = distractor_ids(11, 8, "scene-a", 0)
    assert len(distractors) == len(set(distractors))
    assert 11 not in distractors


def test_custom_patterns_are_validated_and_rendered(tmp_path):
    texture = np.full((40, 60, 3), 210, dtype=np.uint8)
    texture[:, ::8] = 130
    texture_path = tmp_path / "custom" / "grid.png"
    write_image(texture_path, texture)
    patterns = discover_custom_patterns(texture_path.parent)
    card = render_pattern_card(glyph_masks()[11], "custom:grid", 5, size=96, custom_patterns=patterns)
    assert card.family == "custom:grid"
    assert len(card.source_sha256) == 64


def test_in_scene_replacement_labels_target_and_bullseye(tmp_path):
    image_path = tmp_path / "base.jpg"
    base = np.full((160, 240, 3), 90, dtype=np.uint8)
    cv2.rectangle(base, (60, 30), (150, 125), (255, 255, 255), -1)
    write_image(image_path, base)
    recipe = {
        "schema_version": "1.0",
        "mode": "in_scene",
        "recipe_id": "in-scene-test",
        "source_group": "capture-a",
        "seed": 7,
        "source_image": "base.jpg",
        "source_sha256": file_sha256(image_path),
        "target_quad": [[0.25, 0.19], [0.625, 0.19], [0.625, 0.78], [0.25, 0.78]],
        "bullseye_quads": [[[0.67, 0.28], [0.86, 0.34], [0.86, 0.67], [0.67, 0.72]]],
    }
    rendered = render_recipe_variant(recipe, tmp_path, glyph_masks(), bullseye_tile(), 0)
    assert {row[0] for row in rendered.annotations} == {0, 30}
    assert not np.array_equal(rendered.image[30:125, 60:150], base[30:125, 60:150])


def template_fixture(tmp_path):
    image_path = tmp_path / "stand.png"
    image = np.zeros((120, 90, 4), dtype=np.uint8)
    image[5:115, 5:85, :3] = 20
    image[5:115, 5:85, 3] = 255
    write_image(image_path, image)
    template_path = tmp_path / "stand-template.json"
    template_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "kind": "stand_template",
                "image": "stand.png",
                "image_sha256": file_sha256(image_path),
                "target_quad": [[0.2, 0.1], [0.8, 0.1], [0.8, 0.55], [0.2, 0.55]],
                "bullseye_quads": [[[0.25, 0.62], [0.75, 0.62], [0.75, 0.9], [0.25, 0.9]]],
            }
        ),
        encoding="utf-8",
    )
    return template_path


def test_separated_scene_renders_and_labels_multiple_stands(tmp_path):
    background_path = tmp_path / "background.jpg"
    write_image(background_path, np.full((240, 360, 3), 180, dtype=np.uint8))
    template_path = template_fixture(tmp_path)
    recipe = {
        "schema_version": "1.0",
        "mode": "separated",
        "recipe_id": "multi-stand",
        "source_group": "hallway-session",
        "seed": 9,
        "background_image": "background.jpg",
        "background_sha256": file_sha256(background_path),
        "stands": [
            {
                "instance_id": "far",
                "role": "distractor",
                "z_index": 0,
                "template": template_path.name,
                "destination_quad": [[0.05, 0.18], [0.32, 0.18], [0.32, 0.67], [0.05, 0.67]],
            },
            {
                "instance_id": "near",
                "role": "primary",
                "z_index": 1,
                "template": template_path.name,
                "destination_quad": [[0.48, 0.12], [0.87, 0.12], [0.87, 0.88], [0.48, 0.88]],
            },
        ],
    }
    rendered = render_recipe_variant(recipe, tmp_path, glyph_masks(), bullseye_tile(), 3)
    included = [item for item in rendered.objects if item["included"]]
    assert {item["stand_id"] for item in included} == {"far", "near"}
    assert sum(item["kind"] == "target" for item in included) == 2
    assert sum(item["kind"] == "bullseye" for item in included) == 2
    target_ids = [item["competition_id"] for item in included if item["kind"] == "target"]
    assert len(target_ids) == len(set(target_ids))


def test_separated_recipe_rejects_multiple_primary_stands(tmp_path):
    background_path = tmp_path / "background.jpg"
    write_image(background_path, np.full((100, 100, 3), 180, dtype=np.uint8))
    template_path = template_fixture(tmp_path)
    stand = {
        "instance_id": "one",
        "role": "primary",
        "z_index": 0,
        "template": template_path.name,
        "destination_quad": [[0.1, 0.1], [0.4, 0.1], [0.4, 0.8], [0.1, 0.8]],
    }
    recipe = {
        "schema_version": "1.0",
        "mode": "separated",
        "recipe_id": "invalid",
        "source_group": "group",
        "background_image": background_path.name,
        "background_sha256": file_sha256(background_path),
        "stands": [stand, dict(stand, instance_id="two", z_index=1)],
    }
    with pytest.raises(SynthesisError, match="exactly one primary"):
        render_recipe_variant(recipe, tmp_path, glyph_masks(), bullseye_tile(), 0)


def test_generate_writes_thirty_mirrored_labels_and_provenance(tmp_path):
    image_path = tmp_path / "base.jpg"
    write_image(image_path, np.full((100, 140, 3), 170, dtype=np.uint8))
    recipe_path = tmp_path / "recipe.json"
    recipe_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "mode": "in_scene",
                "recipe_id": "generation-test",
                "source_group": "capture-z",
                "source_image": str(image_path),
                "source_sha256": file_sha256(image_path),
                "target_quad": [[0.2, 0.15], [0.8, 0.15], [0.8, 0.85], [0.2, 0.85]],
                "bullseye_quads": [],
                "seed": 2079,
            }
        ),
        encoding="utf-8",
    )
    module_root = Path(__file__).resolve().parents[1]
    images = generate_recipe(
        recipe_path,
        module_root,
        module_root / "misc/resources/glyphs",
        tmp_path / "images",
        tmp_path / "labels",
    )
    assert len(images) == 30
    label = next((tmp_path / "labels").rglob("sample-000.txt"))
    metadata = json.loads(label.with_suffix(".meta.json").read_text(encoding="utf-8"))
    assert label.read_text(encoding="utf-8").startswith("0 ")
    assert metadata["source_group"] == "capture-z"
    assert metadata["primary_competition_id"] == 11
    with pytest.raises(SynthesisError, match="refusing to overwrite"):
        generate_recipe(
            recipe_path,
            module_root,
            module_root / "misc/resources/glyphs",
            tmp_path / "images",
            tmp_path / "labels",
        )
