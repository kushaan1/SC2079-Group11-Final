# Model training

This directory contains the reproducible data and training pipeline for two Ultralytics YOLOv8
object detectors:

- **Task 1:** target IDs 11–40 plus a bull's-eye recovery class, trained at 640 px;
- **Task 2:** an arrow-only model, trained and exported at 320 px for Raspberry Pi inference.

Follow this document in order:

1. [Dataset synthesisation](#1-dataset-synthesisation)
2. [Training loop](#2-training-loop)
3. [Testing](#3-testing)
4. [Archive](#4-archive-legacy-dataset-workflows)

The class registries are order-sensitive. Changing their order changes the meaning of every existing
YOLO label, so confirm the semester's target list before producing a large dataset.

## 1. Dataset synthesisation

The current Task 1 loop composites one to three photographed stand cutouts onto each stand-free
background. Every stand uses one of three fixed orientations—front, left, or right—and only its
Number 1 card is replaced. The photographed bull's-eye remains part of the stand and is annotated
for recovery training.

The complete loop is:

1. Collect three transparent RGBA stand templates and stand-free background photographs.
2. Extract and visually audit the 30 black glyph masks.
3. Register the replaceable card and baked bull's-eye surfaces on each stand orientation.
4. Calibrate perspective for each background with two floor-contact clicks.
5. Generate 30 balanced images from every background recipe.
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

### Step 2: build and audit glyph masks

The existing glyph tiles for IDs 11–40 contain a diagonal-stripe background. Extract only their
black antialiased silhouettes:

**Bash (Linux/macOS):**

```bash
cd image-rec
python -m training.synthesize build-masks
```

**PowerShell (Windows):**

```powershell
Set-Location image-rec
python -m training.synthesize build-masks
```

This writes the ignored masks and `training/.generated/synthesis/glyph-mask-audit.jpg`. Inspect all
30 entries, especially holes in `8`, `A`, and `B`, arrow edges, and the stop symbol. Do not generate
training data from a mask audit with missing strokes, filled holes, or background remnants.

### Step 3: register the three stand orientations

Run each command once. In the OpenCV window, click the Number 1 card corners in this order:
top-left, top-right, bottom-right, bottom-left. For the oblique templates, repeat that order for the
single visible bull's-eye surface.

**Bash (Linux/macOS):**

```bash
python -m training.synthesize configure-orientation \
  --orientation front \
  --image training/synthesis/stand-templates/front.png \
  --output training/annotations/synthesis/front-template.json

python -m training.synthesize configure-orientation \
  --orientation left \
  --image training/synthesis/stand-templates/left.png \
  --output training/annotations/synthesis/left-template.json \
  --bullseyes 1

python -m training.synthesize configure-orientation \
  --orientation right \
  --image training/synthesis/stand-templates/right.png \
  --output training/annotations/synthesis/right-template.json \
  --bullseyes 1
```

**PowerShell (Windows):**

```powershell
python -m training.synthesize configure-orientation `
  --orientation front `
  --image training/synthesis/stand-templates/front.png `
  --output training/annotations/synthesis/front-template.json

python -m training.synthesize configure-orientation `
  --orientation left `
  --image training/synthesis/stand-templates/left.png `
  --output training/annotations/synthesis/left-template.json `
  --bullseyes 1

python -m training.synthesize configure-orientation `
  --orientation right `
  --image training/synthesis/stand-templates/right.png `
  --output training/annotations/synthesis/right-template.json `
  --bullseyes 1
```

The bull's-eye remains black and white. It is not assigned a fuzzing pattern.

### Step 4: configure every background

Create one `*-auto.json` recipe per stand-free background. The OpenCV window needs two clicks:

1. a representative **far** floor-contact point;
2. a representative **near** floor-contact point.

Separate the points vertically by at least 10% of the image height. Keep the near point at least 2%
above the lower edge so a slightly rolled stand can remain inside the frame.

**Bash (Linux/macOS):**

```bash
python -m training.synthesize configure-auto \
  --background training/synthesis/backgrounds/hallway-01.jpg \
  --output training/annotations/synthesis/hallway-01-auto.json \
  --recipe-id hallway-01-auto \
  --source-group hallway-session-a \
  --front training/annotations/synthesis/front-template.json \
  --left training/annotations/synthesis/left-template.json \
  --right training/annotations/synthesis/right-template.json
```

**PowerShell (Windows):**

```powershell
python -m training.synthesize configure-auto `
  --background training/synthesis/backgrounds/hallway-01.jpg `
  --output training/annotations/synthesis/hallway-01-auto.json `
  --recipe-id hallway-01-auto `
  --source-group hallway-session-a `
  --front training/annotations/synthesis/front-template.json `
  --left training/annotations/synthesis/left-template.json `
  --right training/annotations/synthesis/right-template.json
```

Use `--overwrite` only for the specific recipe being deliberately recalibrated. Existing recipes
without the required perspective calibration are rejected.

### Step 5: generate all configured backgrounds

Generate one recipe while tuning or all recipes for a dataset build.

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

Each recipe deterministically creates 30 images:

- every target ID 11–40 is the primary target once;
- primary orientations are balanced at ten front, ten left, and ten right;
- stand counts are balanced at ten images each with one, two, and three stands;
- distractor glyphs and fuzzing patterns rotate independently of the primary;
- the primary is always the largest and is rendered nearest;
- primary stands occupy 45–65% of image height and distractors 18–42%;
- the calibrated perspective curve uses a 1.7 exponent, shrinking distant stands more quickly;
- nine images per recipe contain one lateral edge crop with 75–90% of that stand visible;
- remaining stands stay fully in frame, with at most three degrees of roll and soft contact shadows.

Automatic placement retains a maximum overlap of 0.45. If the greedy placement of one stand reaches
a dead end, the generator deterministically retries the complete layout, including the earlier stand
positions, instead of relaxing that ceiling. All 30 variants are staged before they are published.
If any variants still fail, the command checks the remaining variants, reports every failed sample
and target ID together, and leaves the recipe's existing output set untouched rather than publishing
a partial scene directory.

The eight built-in pattern families are stripes, checks, dots, scales, diamonds, camouflage,
marble/noise, and weave. Their scale, angle, phase, intensity, and restrained colour vary with the
recipe seed. Pattern assignment is balanced independently of class. Darker patterns are allowed,
but their background luma must remain at least 48 on the 0–255 scale so a black glyph retains a
minimum usable contrast.

Optional custom patterns must be pattern-only images that decode, tile cleanly, contain sufficient
variation, and have no pixel below the same luma floor. Every generated image has a mirrored YOLO
`.txt` label and `.meta.json` provenance record containing its recipe hash, `source_group`, objects,
patterns, contrast floor, and generation parameters. Existing outputs are refused unless the
specific generation command includes `--overwrite`.

When `training/synthesis/custom-patterns/` exists and contains reviewed textures, add
`--custom-patterns training/synthesis/custom-patterns` to each `generate` command.

### Step 6: audit generated images and annotations

Create a contact sheet after every generation batch:

**Bash (Linux/macOS):**

```bash
python -m training.synthesize audit \
  --images training/training_set/synthetic \
  --annotations training/annotations/task1/synthetic \
  --output training/.generated/synthesis/dataset-audit.jpg
```

**PowerShell (Windows):**

```powershell
python -m training.synthesize audit `
  --images training/training_set/synthetic `
  --annotations training/annotations/task1/synthetic `
  --output training/.generated/synthesis/dataset-audit.jpg
```

Reject and correct scenes with floating stands, impossible perspective, intersecting stands,
incorrect z-order, detached shadows, unreadable primary cards, bad glyph masks, or incorrect boxes.
Every visible target and baked bull's-eye must have a full-card box. The primary role is provenance,
not a different YOLO class.

### Step 7: validate and prepare the grouped dataset

Validation rejects missing, TODO, or empty labels; malformed or out-of-frame boxes; invalid class
indices; undecodable images; duplicate image contents; and classes with no examples.

**Bash (Linux/macOS):**

```bash
python -m training.validate --task task1
python -m training.prepare --task task1
```

**PowerShell (Windows):**

```powershell
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

### YOLO annotation contract

Task 1 maps glyph IDs 11–40 to class indices 0–29 and bull's-eye ID 41 to class index 30. Each image
has a same-stem `.txt` file containing one row per visible object:

```text
<class_index> <x_center> <y_center> <width> <height>
```

Coordinates are normalized to image width and height. Empty labels are rejected because generated
competition scenes must contain at least one visible target or bull's-eye.

## 2. Training loop

### Set up the training environment

Use Python 3.10. Install the accelerator-specific PyTorch build before the remaining packages. Run
all following commands from `image-rec/`.

**Bash (Linux/macOS):**

```bash
python3.10 -m venv .venv-training
source .venv-training/bin/activate
python -m pip install --upgrade pip
```

**PowerShell (Windows):**

```powershell
py -3.10 -m venv .venv-training
.\.venv-training\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

For a supported Linux ROCm installation, first install the PyTorch build specified by
[AMD's ROCm PyTorch guide](https://rocm.docs.amd.com/projects/ai-ecosystem/en/latest/frameworks/pytorch/install.html),
then install the ROCm profile:

**Bash (Linux with ROCm):**

```bash
python -m pip install -r requirements-training-rocm.txt
```

For CUDA, DirectML, MPS, or CPU development environments, use the standard profile:

**Bash (Linux/macOS):**

```bash
python -m pip install -r requirements-training.txt
```

**PowerShell (Windows):**

```powershell
python -m pip install -r requirements-training.txt
```

Verify a CUDA or ROCm device before a long run:

**Bash (Linux CUDA/ROCm host):**

```bash
python -c 'import torch; print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0)); print(torch.version.hip)'
```

**PowerShell (Windows):**

```powershell
python -c "import torch; print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0)); print(torch.version.hip)"
```

ROCm is exposed through `torch.cuda` and uses `cuda:0`; `torch.version.hip` distinguishes it from
CUDA. Automatic backend preference is **CUDA → ROCm → DirectML → MPS → CPU**, with a real tensor
operation used to probe each candidate. Dataset and configuration errors do not trigger device
fallback.

### Train Task 1 and Task 2

`training.train` validates and prepares the selected task again before invoking Ultralytics.

**Bash (Linux/macOS):**

```bash
python -m training.train --task task1
python -m training.train --task task2
```

**PowerShell (Windows):**

```powershell
python -m training.train --task task1
python -m training.train --task task2
```

Use short controlled runs to verify a backend or changed pipeline before a full experiment:

**Bash (Linux/macOS):**

```bash
python -m training.train --task task1 --backend rocm --epochs 5 --batch-size 4
```

**PowerShell (Windows):**

```powershell
python -m training.train --task task1 --backend rocm --epochs 5 --batch-size 4
```

Defaults live in `training/configs/task1.json` and `training/configs/task2.json`. Do not hardcode
experiment values in `train.py`. Every successful run records the selected device, failed backend
attempts, effective arguments, seed, environment versions, and hashes of the task config, class
registry, and split manifest in `run-metadata.json`.

### Dataset improvement loop

After each training run:

1. Evaluate the untouched test split and independent real-photo set.
2. Review false positives, false negatives, class confusion, and nearest-target mistakes.
3. Add new **source groups** that represent the failure conditions; do not copy test images into
   training or tune directly on the test set.
4. Regenerate only the affected recipes, audit the results, then rerun validation and preparation.
5. Commit the updated recipes, labels, provenance, and manifest before retraining.
6. Record the experiment and compare it against the previous checkpoint using the same acceptance
   set.

## 3. Testing

Testing has three layers: pipeline tests, held-out YOLO evaluation, and deployment-like real photos.

### Test the data and training code

Install development dependencies and run the complete test suite:

**Bash (Linux/macOS):**

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

**PowerShell (Windows):**

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

### Evaluate the untouched test splits

Evaluate only after selecting a checkpoint using validation results. Do not use test metrics to
choose epochs or tune hyperparameters.

**Bash (Linux/macOS):**

```bash
yolo detect val \
  model=training/runs/task1/yolov8n-targets/weights/best.pt \
  data=training/.generated/task1/data.yaml \
  split=test \
  imgsz=640

yolo detect val \
  model=training/runs/task2/yolov8n-arrows/weights/best.pt \
  data=training/.generated/task2/data.yaml \
  split=test \
  imgsz=320
```

**PowerShell (Windows):**

```powershell
yolo detect val `
  model=training/runs/task1/yolov8n-targets/weights/best.pt `
  data=training/.generated/task1/data.yaml `
  split=test `
  imgsz=640

yolo detect val `
  model=training/runs/task2/yolov8n-arrows/weights/best.pt `
  data=training/.generated/task2/data.yaml `
  split=test `
  imgsz=320
```

Inspect per-class precision, recall, confusion, and saved prediction images—not only aggregate mAP.
For Task 1, also verify that all visible stands are detected and that downstream selection chooses
the largest target box as the nearest target. When similarly sized detections are plausible, the
runtime may return the highest-confidence detection first and retain the next-highest candidate.

### Test on independent real photographs

Place independent, manually reviewed photographs in `training/evaluation/task1/`. They should include
physically printed fuzzed targets, front and oblique stands, one to three stands, bull's-eyes,
partial edge crops, darker patterns, varied depths, and locations not used as synthesis backgrounds.

**Bash (Linux/macOS):**

```bash
mkdir -p training/evaluation/task1
yolo detect predict \
  model=training/runs/task1/yolov8n-targets/weights/best.pt \
  source=training/evaluation/task1 \
  imgsz=640 \
  save=True save_txt=True save_conf=True
```

**PowerShell (Windows):**

```powershell
New-Item -ItemType Directory -Force training/evaluation/task1
yolo detect predict `
  model=training/runs/task1/yolov8n-targets/weights/best.pt `
  source=training/evaluation/task1 `
  imgsz=640 `
  save=True save_txt=True save_conf=True
```

Synthetic results alone are not an acceptance test. Record missed glyphs, bull's-eye recovery
behavior, false positives, and whether nearest-target selection agrees with the intended stand.

### Promote Task 1 and export Task 2

After Task 1 passes the held-out and real-photo checks, copy its selected weights into the ignored
runtime location:

**Bash (Linux/macOS):**

```bash
cp training/runs/task1/yolov8n-targets/weights/best.pt pc_server/models/best.pt
```

**PowerShell (Windows):**

```powershell
Copy-Item training/runs/task1/yolov8n-targets/weights/best.pt pc_server/models/best.pt
```

Export the selected Task 2 checkpoint as full INT8 TFLite:

**Bash (Linux/macOS):**

```bash
python -m training.export_int8 \
  --weights training/runs/task2/yolov8n-arrows/weights/best.pt \
  --publish
```

**PowerShell (Windows):**

```powershell
python -m training.export_int8 `
  --weights training/runs/task2/yolov8n-arrows/weights/best.pt `
  --publish
```

The export uses all prepared calibration images, batch size 1, 320×320 input, and `nms=False` for
`rpi/inference/tflite_detector.py`. `--publish` copies `best_arrows.tflite` into the ignored
`rpi/models/` directory and regenerates its tracked label file from the training class order.

An export is not deployed until it loads and invokes successfully under the target Pi runtime.
Record model checksum, tensor shapes, dtypes, quantization scales, and latency in
`docs/calibration.md`.

### Release gates and failure behavior

- No training starts while annotation validation or split coverage fails.
- Placeholder annotations are never treated as empty/background images.
- Duplicate images, synthetic derivatives, and related captures cannot cross splits.
- A generated image must contain at least one visible labelled target or bull's-eye.
- Backend fallback occurs only for device failures, not dataset or configuration failures.
- Task 1 weights are not promoted until held-out and real-photo testing passes.
- Task 2 exports are not published when output selection is ambiguous or stale.
- Source images, generated workspaces, weights, and exports remain uncommitted.

## 4. Archive: legacy dataset workflows

The workflows below are retained for reproducing or repairing older datasets. They are not part of
the current three-orientation automatic dataset loop.

### Archive A: replace a card directly in a photographed scene

This legacy mode keeps the photographed stand in its original environment and replaces its card in
place. Click each target or bull's-eye surface top-left, top-right, bottom-right, bottom-left.

**Bash (Linux/macOS):**

```bash
python -m training.synthesize configure-in-scene \
  --image training/synthesis/in-scene/hallway-01.jpg \
  --output training/annotations/synthesis/hallway-01.json \
  --recipe-id hallway-01 \
  --source-group hallway-session-a \
  --bullseyes 1

python -m training.synthesize generate \
  --recipe training/annotations/synthesis/hallway-01.json
```

**PowerShell (Windows):**

```powershell
python -m training.synthesize configure-in-scene `
  --image training/synthesis/in-scene/hallway-01.jpg `
  --output training/annotations/synthesis/hallway-01.json `
  --recipe-id hallway-01 `
  --source-group hallway-session-a `
  --bullseyes 1

python -m training.synthesize generate `
  --recipe training/annotations/synthesis/hallway-01.json
```

Use zero bull's-eyes only when no adjacent face is meaningfully visible.

### Archive B: manually compose stand instances

This legacy mode registers arbitrary RGBA templates and manually places an ordered list of stands.
Templates require genuine alpha transparency. Supply scene instances from farthest to nearest, with
exactly one `primary` and any remaining instances marked `distractor`.

**Bash (Linux/macOS):**

```bash
python -m training.synthesize configure-template \
  --image training/synthesis/stand-templates/right-facing.png \
  --output training/annotations/synthesis/right-facing-template.json \
  --bullseyes 1

python -m training.synthesize configure-scene \
  --background training/synthesis/backgrounds/lab-03.jpg \
  --output training/annotations/synthesis/lab-03-multi.json \
  --recipe-id lab-03-multi \
  --source-group lab-session-b \
  --stand distractor:training/annotations/synthesis/right-facing-template.json \
  --stand primary:training/annotations/synthesis/front-template.json

python -m training.synthesize generate \
  --recipe training/annotations/synthesis/lab-03-multi.json
```

**PowerShell (Windows):**

```powershell
python -m training.synthesize configure-template `
  --image training/synthesis/stand-templates/right-facing.png `
  --output training/annotations/synthesis/right-facing-template.json `
  --bullseyes 1

python -m training.synthesize configure-scene `
  --background training/synthesis/backgrounds/lab-03.jpg `
  --output training/annotations/synthesis/lab-03-multi.json `
  --recipe-id lab-03-multi `
  --source-group lab-session-b `
  --stand distractor:training/annotations/synthesis/right-facing-template.json `
  --stand primary:training/annotations/synthesis/front-template.json

python -m training.synthesize generate `
  --recipe training/annotations/synthesis/lab-03-multi.json
```

Rerun `configure-scene` with a revised far-to-near stand list and scoped `--overwrite` to move,
reorder, or remove legacy instances.

### Archive C: fully manual image annotation

The original dataset loop placed photographs in `training/training_set/` or
`training/task2_training_set/`, created `.txt.todo` placeholders, and replaced each placeholder with
a manually reviewed YOLO `.txt` file in the mirrored annotation directory.

For example:

```text
training/training_set/session-3/frame-004.jpg
training/annotations/task1/session-3/frame-004.txt
```

Generate placeholders with:

**Bash (Linux/macOS):**

```bash
python -m training.create_placeholders --task task1
python -m training.create_placeholders --task task2
```

**PowerShell (Windows):**

```powershell
python -m training.create_placeholders --task task1
python -m training.create_placeholders --task task2
```

A `.txt.todo` file is intentionally invalid and must never be renamed without annotation review.
CVAT, Label Studio, or another tool may be used if its export is Ultralytics YOLO detection format
and follows the exact class order in the task registry.
