# Dataset and provenance reference

[Back to model training](../README.md). Run commands from `image-rec/` in the training environment.

## File layout

```text
training/
|-- synthesis/
|   |-- stand-templates/       front.png, left.png, and right.png (RGBA)
|   |-- backgrounds/           stand-free source photographs
|   `-- custom-patterns/       optional pattern-only texture images
|-- annotations/
|   |-- synthesis/             tracked template and background recipes
|   `-- task1/synthetic/       tracked YOLO labels and provenance
|-- training_set/synthetic/    generated Task 1 images (ignored)
|-- classes/                   ordered class registries
|-- configs/                   split and model settings
|-- manifests/                 tracked split/checksum records
|-- .generated/                prepared datasets and audit images (ignored)
|-- runs/                      training outputs (ignored)
`-- exports/                   local model exports (ignored)
```

Git retains recipes, labels, provenance, class registries, configs, and manifests. Source photos,
generated images, weights, prepared datasets, run directories, and model exports remain ignored.
The three approved stand-template PNGs are retained as explicit exceptions to the image ignore rule.

Task 2 keeps images in `training/task2_training_set/` and labels in `training/annotations/task2/`.
Preserve each image's relative path in its annotation tree.

## Manual annotations

Place photographs in the task-specific image directory, create `.txt.todo` placeholders, and
replace each placeholder with a manually reviewed YOLO `.txt` file in the mirrored annotation
directory. Use this workflow for Task 2 and for real Task 1 photographs.

For example:

```text
training/training_set/session-3/frame-004.jpg
training/annotations/task1/session-3/frame-004.txt
```

Generate placeholders with:

```sh
python -m training.create_placeholders --task task1
python -m training.create_placeholders --task task2
```

A `.txt.todo` file is intentionally invalid and must never be renamed without annotation review.
CVAT, Label Studio, or another tool may be used if its export is Ultralytics YOLO detection format
and follows the exact class order in the task registry.

## YOLO annotation contract

Task 1 maps glyph IDs 11–40 to class indices 0–29 and bull's-eye ID 41 to class index 30. Each image
has a same-stem `.txt` file containing one row per visible object:

```text
<class_index> <x_center> <y_center> <width> <height>
```

Coordinates are normalized to image width and height. Empty labels are rejected because generated
competition scenes must contain at least one visible target or bull's-eye.

Task 2 uses its own [ordered registry](../classes/task2.json): indices 0, 1, 2, and 3 mean
Up, Down, Right, and Left Arrow respectively. Do not reuse Task 1 class indices.

## Source groups

A source group is the smallest collection of samples that must stay in one dataset split. The
splitter assigns the complete group to train, validation, or test; it never divides a group between
them. This makes validation and test results more honest by preventing the model from seeing a
near-duplicate of an evaluation scene during training.

Use the same `source_group` for:

- photos from the same capture session with substantially the same location, camera setup, and
  surroundings;
- adjacent frames or burst photos, even when their framing or lighting differs slightly;
- crops, augmentations, or other derivatives of the same original image; and
- every synthetic scene generated from backgrounds belonging to that capture group.

Start a new group when the images were captured independently—for example, in another location, on
another visit, or after a meaningful change to the camera setup or environment. Group by shared
visual origin, not by class, recipe, filename, or desired split. Do not create a different group for
each generated sample, because that would allow variants of the same background into multiple
splits.

Use short, stable, descriptive names such as `hallway-session-a`, `lab-daylight-b`, or
`canteen-evening-c`. Choose the group before configuring synthesis and pass it with
`--source-group`; generation copies that value into every sample's `.meta.json` provenance record.
If a manually labelled real image has no `.meta.json`, it is treated as its own independent group.
For related real images, add same-stem provenance files and give them the same non-empty group:

```json
{
  "schema_version": "1.0",
  "source_group": "hallway-session-a"
}
```

Because Task 1 requires every class in train, validation, and test, each class must occur in at
least three independent source groups. More than three is strongly preferred: group atomicity may
move the final sample counts away from the nominal 70/20/10 ratios, and extra groups give the
splitter more freedom to balance them.

Place each `.meta.json` beside its annotation (for example,
`training/annotations/task1/session-3/frame-004.meta.json`). Both tasks currently require
every class in all three splits. Never rename groups just to satisfy coverage.

## Validation and split records

Validation rejects missing, TODO, or empty labels; malformed or out-of-frame boxes; invalid class
indices; undecodable images; duplicate image contents; and classes with no examples. Synthetic
provenance objects must match YOLO labels one-to-one by class and box. Coordinate differences up to
the shared eight-decimal YOLO serialization tolerance (`1e-8`) are accepted; larger differences are
rejected.

```sh
python -m training.validate --task task1
python -m training.prepare --task task1
```

Preparation repeats validation and creates `training/.generated/task1/data.yaml` plus the tracked
`training/manifests/task1-split.json`. The default split is 70% train, 20% validation, and 10% test
with seed `2079`.

Complete `source_group` values are assigned atomically. Before balancing remaining examples, the
splitter reserves independent groups so every class appears in train, validation, and test. Each
class therefore needs at least three source groups. Test may exceed exactly 10% when class coverage
or group atomicity requires it. Review and commit the manifest whenever approved images or labels
change.

Use `--task task2` for the separate Task 2 dataset and manifest.

## Regenerating changed recipes

Changing a recipe, including its `source_group`, changes the `scene-<hash>` output path.
Move superseded scene directories outside both input trees, or remove the specific old directories
from `training/training_set/synthetic/` and `training/annotations/task1/synthetic/`.
Keep images and annotations in sync; then regenerate, visually audit, validate, and prepare.
`--overwrite` alone does not remove outputs under an old hash.
