# Evaluation and deployment

[Back to model training](../README.md). Run commands from `image-rec/` in the training environment.

Examples below use the default run names. Substitute the actual run directory printed by
`training.train`, including any numeric suffix.

Testing has three layers: pipeline tests, held-out YOLO evaluation, and deployment-like real photos.

### Test the data and training code

Install development dependencies and run the complete test suite:

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

### Evaluate the untouched test splits

Evaluate only after selecting a checkpoint using validation results. Do not use test metrics to
choose epochs or tune hyperparameters.

```sh
yolo detect val model=training/runs/task1/yolov8s-targets/weights/best.pt data=training/.generated/task1/data.yaml split=test imgsz=640

yolo detect val model=training/runs/task2/yolov8n-arrows/weights/best.pt data=training/.generated/task2/data.yaml split=test imgsz=320
```

Inspect per-class precision, recall, confusion, and saved prediction images—not only aggregate mAP.
For Task 1, also verify that all visible stands are detected and that downstream selection chooses
the largest target box as the nearest target. When similarly sized detections are plausible, the
runtime may return the highest-confidence detection first and retain the next-highest candidate.

### Test on independent real photographs

Place independent, manually reviewed photographs in `training/evaluation/task1/`. They should include
physically printed fuzzed targets, front and oblique stands, one to three stands, bull's-eyes,
partial edge crops, darker patterns, varied depths, and locations not used as synthesis backgrounds.

The repository convenience script accepts any image folder, trained `.pt` checkpoint, and output
folder. From `image-rec/`, for example:

```powershell
..\.venv\Scripts\python.exe predict_images.py `
  --model training/runs/task1/yolov8s-targets/weights/best.pt `
  --source misc/test_real `
  --output training/predictions/test-real
```

It uses the Task 1 runtime defaults of `imgsz=640`, confidence `0.60`, and IoU `0.45`. It defaults to
CPU for portable offline checks; pass `--device 0` to request the first GPU. Override the other
settings with `--imgsz`, `--conf`, or `--iou`. The output folder contains annotated images and a
`labels/` subfolder with YOLO-format predictions and confidence values. Reusing an output folder
overwrites same-named results but does not delete unrelated or stale files.

**Bash (Linux/macOS):**

```bash
mkdir -p training/evaluation/task1
yolo detect predict \
  model=training/runs/task1/yolov8s-targets/weights/best.pt \
  source=training/evaluation/task1 \
  imgsz=640 \
  save=True save_txt=True save_conf=True
```

**PowerShell (Windows):**

```powershell
New-Item -ItemType Directory -Force training/evaluation/task1
yolo detect predict `
  model=training/runs/task1/yolov8s-targets/weights/best.pt `
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
cp training/runs/task1/yolov8s-targets/weights/best.pt pc_server/models/best.pt
```

**PowerShell (Windows):**

```powershell
Copy-Item training/runs/task1/yolov8s-targets/weights/best.pt pc_server/models/best.pt
```

Export the selected Task 2 checkpoint as full INT8 TFLite:

```sh
python -m training.export_int8 --weights training/runs/task2/yolov8n-arrows/weights/best.pt --publish
```

The export uses all prepared calibration images, batch size 1, 320×320 input, and `nms=False` for
`rpi/inference/tflite_detector.py`. `--publish` copies `best_arrows.tflite` into the ignored
`rpi/models/` directory and regenerates its tracked label file from the training class order.

An export is not deployed until it loads and invokes successfully under the target Pi runtime.
Record model checksum, tensor shapes, dtypes, quantization scales, and latency in
[docs/calibration.md](../../../docs/calibration.md).

### Release gates and failure behavior

- No training starts while annotation validation or split coverage fails.
- Placeholder annotations are never treated as empty/background images.
- Duplicate images, synthetic derivatives, and related captures cannot cross splits.
- A generated image must contain at least one visible labelled target or bull's-eye.
- Backend fallback occurs only for device failures, not dataset or configuration failures.
- Task 1 weights are not promoted until held-out and real-photo testing passes.
- Task 2 exports are not published when output selection is ambiguous or stale.
- Source images, generated workspaces, weights, and exports remain uncommitted.

## Dataset improvement loop

After each training run:

1. Use validation results and separate development photos to guide dataset improvements.
   Reserve the untouched test split and independent acceptance photos for the selected release.
2. Review false positives, false negatives, class confusion, and nearest-target mistakes.
3. Add new **source groups** that represent the failure conditions; do not copy test images into
   training or tune directly on the test set.
4. Regenerate only the affected recipes, audit the results, then rerun validation and preparation.
5. Commit the updated recipes, labels, provenance, and manifest before retraining.
6. Record the experiment and compare it against the previous checkpoint using the same acceptance
   set.
