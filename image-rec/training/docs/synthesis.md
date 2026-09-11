# Task 1 synthetic data

[Back to model training](../README.md). Run commands from `image-rec/` in the training environment.

The current Task 1 loop composites one to three photographed stand cutouts onto each stand-free
background. Every stand uses one of three fixed orientations—front, left, or right—and only its
Number 1 card is replaced. The photographed bull's-eye remains part of the stand and is annotated
for recovery training.

The complete loop is:

1. Collect three transparent RGBA stand templates and stand-free background photographs.
2. Extract and visually audit the 30 black glyph masks.
3. Register the replaceable card and baked bull's-eye surfaces on each stand orientation.
4. Calibrate perspective for each background with two floor-contact clicks.
5. Generate 90 balanced images from every background recipe.
6. Audit the rendered images, labels, placement, and provenance.
7. Validate Task 1 annotations.
8. Prepare grouped train, validation, and test splits.

Do not start training until all eight steps pass.

### Inputs and generated outputs

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

### Step 1: collect source assets

Prepare exactly three tightly cropped stand images named `front.png`, `left.png`, and `right.png`.
They must have genuine alpha transparency and clean edges. Crop to the visible stand; excess
transparent canvas is trimmed automatically, but a tight source makes visual review easier.

Background images must contain no stands. For the initial dataset, iPhone photos are acceptable.
Capture them from approximately the deployed camera height and leave a clear lower floor region for
placement. Vary location, lighting, floor, clutter, and people. Avoid using many adjacent video
frames as independent environments.

Assign a `source_group` for each capture session or environment family. Related photos and every
synthetic derivative of them must use the same group so they cannot leak across dataset splits.

For a robust first dataset, target 60–100 distinct environments across at least 12 capture groups.
Keep a separate set of real photographs containing physically printed fuzzed glyphs for final
acceptance testing.

See [source groups and provenance](dataset.md#source-groups) for grouping examples and metadata.

### Step 2: build and audit glyph masks

The existing glyph tiles for IDs 11–40 contain a diagonal-stripe background. Extract only their
black antialiased silhouettes:

```sh
python -m training.synthesize build-masks
```

This writes the ignored masks and `training/.generated/synthesis/glyph-mask-audit.jpg`. Inspect all
30 entries, especially holes in `8`, `A`, and `B`, arrow edges, and the stop symbol. Do not generate
training data from a mask audit with missing strokes, filled holes, or background remnants.

### Step 3: register the three stand orientations

Run each command once. In the OpenCV window, click the Number 1 card corners in this order:
top-left, top-right, bottom-right, bottom-left. For the oblique templates, repeat that order for the
single visible bull's-eye surface.

```sh
python -m training.synthesize configure-orientation --orientation front --image training/synthesis/stand-templates/front.png --output training/annotations/synthesis/front-template.json

python -m training.synthesize configure-orientation --orientation left --image training/synthesis/stand-templates/left.png --output training/annotations/synthesis/left-template.json --bullseyes 1

python -m training.synthesize configure-orientation --orientation right --image training/synthesis/stand-templates/right.png --output training/annotations/synthesis/right-template.json --bullseyes 1
```

The bull's-eye remains black and white. It is not assigned a fuzzing pattern.

### Step 4: configure every background

Create one `*-auto.json` recipe per stand-free background. The OpenCV window needs two clicks:

1. a representative **far** floor-contact point;
2. a representative **near** floor-contact point.

Separate the points vertically by at least 10% of the image height. Keep the near point at least 2%
above the lower edge so a slightly rolled stand can remain inside the frame.

```sh
python -m training.synthesize configure-auto --background training/synthesis/backgrounds/hallway-01.jpg --output training/annotations/synthesis/hallway-01-auto.json --recipe-id hallway-01-auto --source-group hallway-session-a --front training/annotations/synthesis/front-template.json --left training/annotations/synthesis/left-template.json --right training/annotations/synthesis/right-template.json
```

Use `--overwrite` only for the specific recipe being deliberately recalibrated. Existing recipes
without the required perspective calibration are rejected.

### Step 5: generate all configured backgrounds

Choose either the single-recipe command or the all-recipes loop below. Do not run both on the same outputs; existing outputs are refused.

**Bash (Linux/macOS):**

```bash
python -m training.synthesize generate \
  --recipe training/annotations/synthesis/hallway-01-auto.json

for recipe in training/annotations/synthesis/*-auto.json; do
  python -m training.synthesize generate \
    --recipe "$recipe"
done
```

**PowerShell (Windows):**

```powershell
python -m training.synthesize generate `
  --recipe training/annotations/synthesis/hallway-01-auto.json

Get-ChildItem training/annotations/synthesis/*-auto.json | ForEach-Object {
  python -m training.synthesize generate `
    --recipe $_.FullName
}
```

Each recipe deterministically creates 90 images:

- every target ID 11–40 is the primary target three times;
- each target appears once at a far, medium, and near primary distance;
- each target appears once in each primary orientation: front, left, and right;
- each target appears once with one, two, and three total stands;
- distractor glyphs and fuzzing patterns rotate independently of the primary;
- the primary is always the largest and is rendered nearest;
- primary apparent heights are split equally between far (30–44%), medium (44–54%), and near
  (54–65%) bands, while distractors occupy 18–42%;
- the calibrated perspective curve uses a 2.2 exponent, increasing the scale falloff for distant
  stands;
- 27 images per recipe contain one lateral edge crop with 75–90% of that stand visible;
- remaining stands stay fully in frame, with at most three degrees of roll and soft contact shadows.

Automatic placement retains a maximum overlap of 0.45. If the greedy placement of one stand reaches
a dead end, the generator deterministically retries the complete layout, including the earlier stand
positions, instead of relaxing that ceiling. All 90 variants are staged before they are published.
If any variants still fail, the command checks the remaining variants, reports every failed sample
and target ID together, and leaves the recipe's existing output set untouched rather than publishing
a partial scene directory.

Whole-frame camera-shake blur is enabled by default in all three recipe modes, including existing
recipes without a `shake_blur` setting. Exactly 27 of the 90 variants receive a short, centred linear
motion blur at a random angle; the other 63 remain sharp. Selection and motion parameters are
reproducible from the recipe ID, seed, and variant index, independently of placement and textures.
Blur runs after compositing, so backgrounds, targets, stands, and bull's-eyes share the same motion.
Geometric labels remain unchanged. The default streak spans 3–5 pixels when the longest frame side
is 640 pixels, scaling with source resolution. These are initial augmentation settings, not a
measurement of the Pi camera; assess robustness on held-out real Pi captures after retraining.

To opt out, add `"shake_blur": {"enabled": false}` at the top level of the recipe JSON.
To tune the effect, use any subset of these settings (omitted keys retain their defaults):

```json
"shake_blur": {
  "enabled": true,
  "fraction": 0.30,
  "length_range_px": [3.0, 5.0],
  "reference_size_px": 640
}
```

`fraction` is rounded to a whole-image count out of 90. Each `.meta.json` records the effective
settings, whether blur was applied, and the sampled length and angle when applied. Synthetic
validation/test splits also inherit this mix because generation precedes grouped splitting.
Existing outputs are not updated automatically: deliberately regenerate the relevant recipe with
`--overwrite` to apply the new default, then audit, validate, prepare, and retrain. Editing recipe
settings changes the scene hash; follow the old-scene cleanup guidance below in that case.

The eight built-in pattern families are stripes, checks, dots, scales, diamonds, camouflage,
marble/noise, and weave. Their scale, angle, phase, intensity, and restrained colour vary with the
recipe seed. Pattern assignment rotates independently of class. Every built-in or custom texture
receives a deterministic 0.55–0.80 exposure multiplier so the black glyph has less contrast against
the fuzzing pattern. The post-transform background luma floor is 24 on the 0–255 scale, permitting
much darker card regions while preventing them from collapsing completely to black.

Optional custom patterns must be pattern-only images that decode, tile cleanly, contain sufficient
variation, and have no source pixel below the same luma floor. Every generated image has a mirrored
YOLO `.txt` label and `.meta.json` provenance record containing its recipe hash, `source_group`,
objects, primary distance band, pattern exposure, contrast floor, and generation parameters.
Existing outputs are refused unless the specific generation command includes `--overwrite`.

Changing a recipe changes its `scene-<hash>` output directory. Before regenerating a changed recipe,
move or remove its old scene directory from both `training/training_set/synthetic/` and
`training/annotations/task1/synthetic/`; otherwise validation will include both the old and new
variants. Keep the two trees in sync, then run generation, audit, validation, and preparation again.

When `training/synthesis/custom-patterns/` exists and contains reviewed textures, add
`--custom-patterns training/synthesis/custom-patterns` to each `generate` command.

### Step 6: audit generated images and annotations

Create a contact sheet after every generation batch:

```sh
python -m training.synthesize audit --images training/training_set/synthetic --annotations training/annotations/task1/synthetic --output training/.generated/synthesis/dataset-audit.jpg
```

Reject and correct scenes with floating stands, impossible perspective, intersecting stands,
incorrect z-order, detached shadows, unreadable primary cards, bad glyph masks, or incorrect boxes.
Every visible target and baked bull's-eye must have a full-card box. The primary role is provenance,
not a different YOLO class.

### Step 7: validate and prepare

Return to [Validate and prepare](../README.md#3-validate-and-prepare). Both validation and split coverage must pass before training.
