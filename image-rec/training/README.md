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
| YOLO `.txt` annotations and `.txt.todo` placeholders | Source photographs |
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
|   `-- task2/                 mirrors Task 2 image paths
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

```powershell
python -m training.create_placeholders --task task1
python -m training.create_placeholders --task task2
```

Empty labels are rejected by default because each competition image is expected to contain a target.
If genuine negative/background images are added later, put them in a deliberately configured dataset
instead of weakening this safeguard without review.

## Training environment

Use Python 3.10 on the training PC. Install the accelerator-specific PyTorch build before the
remaining training packages. From `image-rec/`:

```powershell
py -3.10 -m venv .venv-training
.\.venv-training\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Choose the requirements profile that matches the PyTorch build installed in that environment. For
the assumed Radeon RX 9070 XT, select the supported ROCm PyTorch command for the host OS and Python
version from [AMD's ROCm PyTorch guide](https://rocm.docs.amd.com/projects/ai-ecosystem/en/latest/frameworks/pytorch/install.html),
then install the ROCm profile:

```powershell
python -m pip install -r requirements-training-rocm.txt
```

Verify the GPU environment before training:

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

```powershell
python -m training.validate --task task1
python -m training.validate --task task2
```

It rejects missing/TODO/empty annotations, malformed or out-of-frame boxes, invalid class indices,
undecodable images, duplicate image contents, and classes with no examples.

Preparation repeats validation and creates deterministic splits:

```powershell
python -m training.prepare --task task1
python -m training.prepare --task task2
```

The committed default is 70% train, 20% validation, and 10% test with seed `2079`. Before balancing
the remaining images, the splitter reserves distinct examples so every class is represented at least
once in **all three pools**. Consequently, a class needs at least three independently captured images.
The test split may grow beyond exactly 10% when that is necessary to satisfy class coverage.

Preparation creates `.generated/<task>/data.yaml` for Ultralytics and
`manifests/<task>-split.json` for replay. Review and commit the manifest whenever the approved image
or annotation set changes.

## Train the two models

These commands validate and prepare again before starting Ultralytics:

```powershell
python -m training.train --task task1
python -m training.train --task task2
```

Useful controlled overrides are available, and are written to each run's metadata:

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
- CUDA/ROCm/DirectML/MPS failures fall back only when the error is device-related.
- Ambiguous or stale multiple TFLite outputs stop export rather than publishing an arbitrary file.
- Weights, datasets, and generated workspaces are never committed by the supplied ignore rules.
