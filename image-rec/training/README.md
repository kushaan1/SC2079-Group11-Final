# Model training

This directory contains the reproducible training pipeline for two separate Ultralytics YOLOv8
object detectors:

- **Task 1:** all target cards plus a distinct bull's-eye class, trained at 640 px;
- **Task 2:** a small arrow-only model, trained and exported at 320 px for local Pi inference.

The current class registries are marked provisional. Confirm the semester's complete target list
before producing a large annotation set, because changing class order changes the meaning of every
existing label.

## What Git stores

Git tracks everything needed to reproduce a run except the large or private binaries:

| Tracked | Ignored |
|---|---|
| YOLO labels, synthesis recipes/provenance, and `.txt.todo` placeholders | Source photographs and RGBA stand templates |
| Ordered class registries | Downloaded and trained `.pt` weights |
| Task hyperparameters and fixed random seed | Generated train/val/test workspace |
| Dataset validators and split algorithm | Ultralytics run directories and caches |
| Split manifests with image and label SHA-256 hashes | ONNX, TFLite, and other exported models |
| Exact top-level training package versions | Local export metadata |

A teammate can check out the repository, place the supplied images in the documented source folders,
run preparation, and reproduce the same split and training arguments. The committed manifest also
detects a wrong or modified image set by checksum.

## Dataset locations

```text
training/
|-- training_set/              Task 1 source images (ignored)
|-- task2_training_set/        Task 2 source images (ignored)
|-- annotations/
|   |-- task1/                 mirrors Task 1 image paths
|   |-- task2/                 mirrors Task 2 image paths
|   `-- synthesis/             versioned card, stand, and scene recipes
|-- synthesis/                 local base photos, backgrounds, cutouts, and patterns
|-- classes/                   ordered model classes and competition IDs
|-- configs/                   split, model, and export settings
|-- manifests/                 generated split/checksum records (tracked)
|-- .generated/                materialized Ultralytics datasets (ignored)
|-- runs/                      training outputs (ignored)
`-- exports/                   local INT8 exports and metadata (ignored)
```

Nested image directories are supported. The annotation directory must mirror the relative path of
each image. For example:

```text
training/training_set/session-3/frame-004.jpg
training/annotations/task1/session-3/frame-004.txt
```

## Annotation format

Use **YOLO object-detection annotations**, not classification folders. Each image has a same-stem
`.txt` file, and every visible object is one row:

```text
<class_index> <x_center> <y_center> <width> <height>
```

All four box values are normalized to the image width and height. Example: class 28 covering the
middle half of an image is:

```text
28 0.5 0.5 0.5 0.5
```

CVAT, Label Studio, or another annotation tool may be used as long as the export is Ultralytics/YOLO
detection format and its class order exactly matches the task's JSON registry. Annotate bull's-eyes
as their own Task 1 class; do not call them background. Task 2 currently includes up, down, right,
and left arrows so non-route arrows can be learned instead of confused with the two route decisions.

The nine existing Task 1 images have `.txt.todo` files. A TODO is intentionally not a valid label and
cannot silently turn an unannotated target into a negative image. After reviewing an image, create
the corresponding `.txt` and remove its `.txt.todo`. Generate TODOs for newly added images with:

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

Empty labels are rejected by default because each competition image is expected to contain a target.
If genuine negative/background images are added later, put them in a deliberately configured dataset
instead of weakening this safeguard without review.

## Generate synthetic Task 1 images

The synthesis pipeline separates the black glyph mask, fuzzing pattern, stand, and environment so
none becomes an accidental class shortcut. IDs 11–40 currently share a diagonal-stripe background.
Extract and visually inspect their reusable masks before generating a dataset:

**Bash (Linux/macOS):**

```bash
python -m training.synthesize build-masks
```

**PowerShell (Windows):**

```powershell
python -m training.synthesize build-masks
```

This writes ignored masks and `glyph-mask-audit.jpg` below `training/.generated/synthesis/`.
Bullseye ID 41 remains a fixed black-and-white marker.

### Default: three automatic stand orientations

Prepare exactly three tightly cropped transparent RGBA stand images: `front`, `left`, and `right`.
The photographed bullseye stays baked into the left/right cutouts; only the Number 1 card is
replaced. Register each template once, clicking the Number 1 card first and then any baked bullseye:

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

Create one recipe for each stand-free background. The command opens the background once: click a
representative far floor-contact point first, then a near floor-contact point. The points must be
separated vertically by at least 10% of the image height; keep the near point at least 2% above the
bottom edge so a slightly rolled stand remains inside the frame.

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

`generate` then creates exactly 30 images for that background. Each target ID is primary once;
front/left/right primaries are balanced ten times each; and stand counts are balanced between one,
two, and three. Orientations may repeat among distractors. The two clicked floor points calibrate a
perspective curve: a stand at the far point is 25% of image height and one at the near point is 65%.
Primary stands sample 45–65%; distractors sample 25–50%. Scale and ground position are no longer
sampled independently, and the primary is always strictly larger and rendered nearest. Translation,
at most three degrees of roll, and soft contact shadows remain enabled.

Exactly nine of the 30 images (30%) contain one laterally edge-cropped stand. The crop retains
75–90% of that stand and preferentially removes the side away from its target card. All other stands
remain completely inside the image. Every visible target and baked bullseye receives a full-card
YOLO box.

The calibration and placement values are copied into the recipe so they can be reviewed or tuned
without editing code. Recipes created before perspective calibration was introduced are rejected;
rerun `configure-auto` with its scoped `--overwrite` flag to perform the two clicks. Audit every
generated scene for floating or geometrically implausible stands.

The manual workflows below remain available for unusual scenes.

### Replace a card on a photographed stand

Place the photo under `training/synthesis/`, then register its target card and visible adjacent
bullseye cards. Click each surface top-left, top-right, bottom-right, then bottom-left.

**Bash (Linux/macOS):**

```bash
python -m training.synthesize configure-in-scene \
  --image training/synthesis/in-scene/hallway-01.jpg \
  --output training/annotations/synthesis/hallway-01.json \
  --recipe-id hallway-01 \
  --source-group hallway-session-a \
  --bullseyes 1
```

**PowerShell (Windows):**

```powershell
python -m training.synthesize configure-in-scene `
  --image training/synthesis/in-scene/hallway-01.jpg `
  --output training/annotations/synthesis/hallway-01.json `
  --recipe-id hallway-01 `
  --source-group hallway-session-a `
  --bullseyes 1
```

Use zero bullseyes only when no adjacent face is meaningfully visible. Register a visible side even
when the original photograph shows blank black material there.

### Compose several cutout stands into an environment

Stand templates must be tightly cropped RGBA PNGs with genuine transparency. Register their target
and visible bullseye surfaces once:

**Bash (Linux/macOS):**

```bash
python -m training.synthesize configure-template \
  --image training/synthesis/stand-templates/right-facing.png \
  --output training/annotations/synthesis/right-facing-template.json \
  --bullseyes 1
```

**PowerShell (Windows):**

```powershell
python -m training.synthesize configure-template `
  --image training/synthesis/stand-templates/right-facing.png `
  --output training/annotations/synthesis/right-facing-template.json `
  --bullseyes 1
```

Supply stands in far-to-near order. Exactly one must be `primary`; the rest are `distractor` stands.
The interactive windows register the destination quadrilateral for each tightly cropped template.

**Bash (Linux/macOS):**

```bash
python -m training.synthesize configure-scene \
  --background training/synthesis/backgrounds/lab-03.jpg \
  --output training/annotations/synthesis/lab-03-multi.json \
  --recipe-id lab-03-multi \
  --source-group lab-session-b \
  --stand distractor:training/annotations/synthesis/right-facing-template.json \
  --stand distractor:training/annotations/synthesis/left-facing-template.json \
  --stand primary:training/annotations/synthesis/front-template.json
```

**PowerShell (Windows):**

```powershell
python -m training.synthesize configure-scene `
  --background training/synthesis/backgrounds/lab-03.jpg `
  --output training/annotations/synthesis/lab-03-multi.json `
  --recipe-id lab-03-multi `
  --source-group lab-session-b `
  --stand distractor:training/annotations/synthesis/right-facing-template.json `
  --stand distractor:training/annotations/synthesis/left-facing-template.json `
  --stand primary:training/annotations/synthesis/front-template.json
```

The primary cycles through all 30 targets. Distractors receive deterministic rotating targets and
independent patterns. Every visible target and bullseye is labelled; nearer stands occlude earlier
ones according to the supplied order. To move, reorder, or remove stands, rerun the command with the
desired far-to-near `--stand` list and the scoped `--overwrite` flag.

Generate the variants and inspect their annotations:

**Bash (Linux/macOS):**

```bash
python -m training.synthesize generate \
  --recipe training/annotations/synthesis/lab-03-multi.json \
  --custom-patterns training/synthesis/custom-patterns

python -m training.synthesize audit \
  --images training/training_set/synthetic \
  --annotations training/annotations/task1/synthetic \
  --output training/.generated/synthesis/dataset-audit.jpg
```

**PowerShell (Windows):**

```powershell
python -m training.synthesize generate `
  --recipe training/annotations/synthesis/lab-03-multi.json `
  --custom-patterns training/synthesis/custom-patterns

python -m training.synthesize audit `
  --images training/training_set/synthetic `
  --annotations training/annotations/task1/synthetic `
  --output training/.generated/synthesis/dataset-audit.jpg
```

Built-in patterns include stripes, checks, dots, scales, diamonds, camouflage, marble, and weave.
Their palettes now sample substantially darker colours while enforcing a minimum background luma of
48 on the 0–255 scale against the black glyph. Custom files must be clean pattern-only images with
sufficient variation and no pixel below the same luma floor. Pattern assignment rotates
independently of class, and each same-stem `.meta.json` records the pattern, contrast floor, objects,
recipe hash, and `source_group`. Existing outputs require `--overwrite`.

### Base-photo requirements

- Prefer the mounted Pi camera at real robot height and standoff distance. Phone images are useful
  smoke tests but should not dominate training.
- Capture front, left-oblique, and right-oblique views under varied lighting, floors, corridors,
  people, and clutter.
- Stand-free backgrounds need plausible floor placement space and no existing competition cards.
  Avoid floating stands, impossible perspective, and intersecting geometry.
- Supply at least front, left-facing, right-facing, and blank-black RGBA templates with clean alpha
  edges. Include single- and multi-stand scenes at varied depths and partial occlusion.
- Start with 60–100 environments across at least 12 capture groups. Adjacent video frames are one
  group, not independent examples.
- Keep a separate real-photo acceptance set with printed fuzzed cards and bullseyes; synthetic test
  results alone do not measure the deployment gap.

## Training environment

Use Python 3.10 on the training PC. Install the accelerator-specific PyTorch build before the
remaining training packages. From `image-rec/`:

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

Choose the requirements profile that matches the PyTorch build installed in that environment. For
the assumed Radeon RX 9070 XT, select the supported ROCm PyTorch command for the host OS and Python
version from [AMD's ROCm PyTorch guide](https://rocm.docs.amd.com/projects/ai-ecosystem/en/latest/frameworks/pytorch/install.html),
then install the ROCm profile:

**Bash (Linux with ROCm):**

```bash
python -m pip install -r requirements-training-rocm.txt
```

**PowerShell (Windows):**

```powershell
python -m pip install -r requirements-training-rocm.txt
```

Verify the GPU environment before training:

**Bash (Linux CUDA/ROCm host):**

```bash
python -c 'import torch; print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0)); print(torch.version.hip)'
```

**PowerShell (Windows):**

```powershell
python -c "import torch; print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0)); print(torch.version.hip)"
```

The expected output is `True`, the RX 9070 XT device name, and a non-empty HIP version.

The ROCm build is exposed by PyTorch through `torch.cuda`; the trainer probes `torch.version.hip`
to distinguish it from CUDA, runs a real allocation/operator smoke test, and passes `cuda:0` to
Ultralytics. The automatic order is **CUDA → ROCm → DirectML → MPS → CPU**. The standard
`requirements-training.txt` profile retains the optional Windows `torch-directml` dependency for
DirectML fallback environments; do not install that profile into the ROCm environment. Ultralytics
does not document DirectML as a native trainer device, so DirectML is only advertised after its own
smoke test. Dataset, download, and configuration errors are not hidden by fallback.

Inspect selection without training by using the unit tests or importing `resolve_backends`. To force
a supported backend during a real run, pass `--backend rocm`, `--backend cuda`, or another backend
name. For the RX 9070 XT, `--backend rocm` is a useful smoke test before a long run.

## Validate and prepare

Validation must pass before splitting or training:

**Bash (Linux/macOS):**

```bash
python -m training.validate --task task1
python -m training.validate --task task2
```

**PowerShell (Windows):**

```powershell
python -m training.validate --task task1
python -m training.validate --task task2
```

It rejects missing/TODO/empty annotations, malformed or out-of-frame boxes, invalid class indices,
undecodable images, duplicate image contents, and classes with no examples.

Preparation repeats validation and creates deterministic splits:

**Bash (Linux/macOS):**

```bash
python -m training.prepare --task task1
python -m training.prepare --task task2
```

**PowerShell (Windows):**

```powershell
python -m training.prepare --task task1
python -m training.prepare --task task2
```

The committed default is 70% train, 20% validation, and 10% test with seed `2079`. Before balancing
the remaining images, the splitter reserves independent source groups so every class appears in
**all three pools**. A class therefore needs at least three groups. Every derivative carrying the
same `source_group` remains in one pool. The test split may grow beyond exactly 10% when required for
class coverage or group atomicity.

Preparation creates `.generated/<task>/data.yaml` for Ultralytics and
`manifests/<task>-split.json` for replay. Review and commit the manifest whenever the approved image
or annotation set changes.

## Train the two models

These commands validate and prepare again before starting Ultralytics:

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

Useful controlled overrides are available, and are written to each run's metadata:

**Bash (Linux/macOS):**

```bash
python -m training.train --task task2 --backend cpu --epochs 5 --batch-size 4
```

**PowerShell (Windows):**

```powershell
python -m training.train --task task2 --backend cpu --epochs 5 --batch-size 4
```

Default settings are in `configs/task1.json` and `configs/task2.json`; do not hardcode experiment
values into `train.py`. Every successful run writes `run-metadata.json` containing:

- the selected device and failed backend attempts;
- effective training arguments and seed;
- Python, OS, machine, and package versions; and
- hashes of the task config, class registry, and split manifest.

Task 1's best weights are normally copied manually from its run directory to
`pc_server/models/best.pt` after validation. Both locations are ignored by Git.

## Export Task 2 as full INT8 TFLite

After selecting Task 2's best checkpoint:

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

The export is CPU-based and requests:

- TFLite format with `int8=True`;
- the prepared dataset as representative calibration data;
- all calibration images (`fraction=1.0`);
- batch size 1 and 320×320 input; and
- `nms=False`, preserving raw output for `rpi/inference/tflite_detector.py`.

The local export, checksum, arguments, environment metadata, and labels are written under the ignored
`training/exports/task2/` directory. `--publish` copies `best_arrows.tflite` into the ignored
`rpi/models/` directory and rewrites the tracked `arrow-labels.json` from the exact training class
order.

An export produced by a current host library is not considered deployed until it loads and invokes
successfully under `tflite-runtime==2.5.0` on the actual Buster Pi. Record that result, tensor shapes,
dtypes, quantization scales, latency, and model checksum in `docs/calibration.md`.

## Failure behavior

- No training starts while validation or split coverage fails.
- Placeholder labels are never interpreted as empty/background images.
- Duplicate images cannot leak across train and test under different filenames.
- Synthetic derivatives and related captures cannot cross splits when they share a `source_group`.
- CUDA/ROCm/DirectML/MPS failures fall back only when the error is device-related.
- Ambiguous or stale multiple TFLite outputs stop export rather than publishing an arbitrary file.
- Weights, datasets, and generated workspaces are never committed by the supplied ignore rules.
