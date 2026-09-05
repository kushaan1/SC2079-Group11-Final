# Model training

Train reproducible Ultralytics YOLOv8 detectors for the two competition tasks.

| | Task 1 | Task 2 |
|---|---|---|
| Classes | IDs 11-40 plus bull's-eye (ID 41) | Up, Down, Right, Left arrows |
| Image size | 640 px | 320 px |
| Deployment | PC server (`best.pt`) | Raspberry Pi (INT8 TFLite) |
| Configuration | [task1.json](configs/task1.json) | [task2.json](configs/task2.json) |

Follow **setup → data → validate and prepare → train → evaluate and export**.
All commands run from `image-rec/`. Shared command blocks work in PowerShell and Bash;
only environment activation and file copying need separate examples.

## 1. Set up

Use Python 3.10 for the pinned training stack. From the repository root:

**PowerShell:**

```powershell
Set-Location image-rec
py -3.10 -m venv .venv-training
.\.venv-training\Scripts\Activate.ps1
```

**Bash:**

```bash
cd image-rec
python3.10 -m venv .venv-training
source .venv-training/bin/activate
```

Install the profile appropriate to your environment:

| Environment | Installation |
|---|---|
| Standard profile (includes DirectML on Windows) | `python -m pip install -r requirements-training.txt` |
| Supported ROCm environment | Install the host-specific ROCm PyTorch build first, then `python -m pip install -r requirements-training-rocm.txt`. |

For accelerator setup, backend probes, and configuration options, see the
[environment guide](docs/environment.md). Choose that setup before installing packages;
the ROCm profile deliberately excludes DirectML.

## 2. Prepare data

Keep each task's images, labels, and class order separate:

| Task | Images | Mirrored YOLO annotations | Class order |
|---|---|---|---|
| Task 1 | `training/training_set/` | `training/annotations/task1/` | [task1.json](classes/task1.json) |
| Task 2 | `training/task2_training_set/` | `training/annotations/task2/` | [task2.json](classes/task2.json) |

**Task 1 synthetic data:** follow the [synthesis guide](docs/synthesis.md) to register stand
orientations, configure backgrounds, generate scenes, and visually audit masks and boxes.

**Task 2 or real Task 1 photos:** follow the [manual annotation guide](docs/dataset.md#manual-annotations).
Labels mirror the image's relative path and use the same stem with a `.txt` extension.
A `.txt.todo` placeholder is incomplete; replace it with reviewed labels before continuing.

Before splitting:

- Keep related captures and synthetic derivatives in the same `source_group`.
- Include every class in at least **three independent source groups** so train, validation,
  and test can each contain it. Never invent independence just to satisfy coverage.
- Follow the ordered class registry; changing its order changes existing labels' meaning.
- Vary backgrounds, lighting, and locations, and reserve independent real photos for acceptance.

See [dataset and provenance rules](docs/dataset.md) for metadata examples, label format,
and safe regeneration when a recipe or source group changes.

## 3. Validate and prepare

Run these commands for the task you intend to train, stopping if either fails:

```sh
python -m training.validate --task task1
python -m training.prepare --task task1
```

For Task 2, use `--task task2` in both commands. Validation must report **0 issue(s)**;
preparation must also pass split coverage. Missing, TODO, empty, malformed, duplicate,
or inconsistent data must be corrected before training.

Preparation writes:

- `training/.generated/task1/data.yaml` and the prepared images and labels;
- `training/manifests/task1-split.json` with assignments and checksums.

Task 2 writes its corresponding `task2` paths. Defaults are **70/20/10**, seed **2079**;
entire source groups stay together, so coverage can change the exact ratios. Review and
commit the manifest whenever approved data changes. Detailed validation rules, including
synthetic box tolerance, are in the [dataset reference](docs/dataset.md#validation-and-split-records).

## 4. Train

Run the command for your prepared task:

```sh
python -m training.train --task task1
```

```sh
python -m training.train --task task2
```

The wrapper validates and prepares again before training. Both configurations default to
100 epochs; Task 1 uses batch size 8 and Task 2 uses 16. For a short trial:

```sh
python -m training.train --task task1 --epochs 5 --batch-size 4
```

Automatic backend order is CUDA → ROCm → DirectML → MPS → CPU, using available devices.
Use `--backend directml` (or `cuda`, `rocm`, `mps`, `cpu`) to require a specific backend.
Device failures can trigger automatic fallback; dataset and configuration errors must be fixed.
See [options and run records](docs/environment.md#training-options-and-records).

The command prints the actual run directory. Its `weights/best.pt` is the selected checkpoint,
and `run-metadata.json` records the environment and data/configuration hashes. Default run names:

- Task 1: `training/runs/task1/yolov8n-targets/`
- Task 2: `training/runs/task2/yolov8n-arrows/`

Repeated runs may add a numeric suffix. **Use your actual run path in the commands below.**

## 5. Evaluate and export

Select the checkpoint using validation results, then evaluate the untouched test split:

```sh
yolo detect val model=training/runs/task1/yolov8n-targets/weights/best.pt data=training/.generated/task1/data.yaml split=test imgsz=640
```

```sh
yolo detect val model=training/runs/task2/yolov8n-arrows/weights/best.pt data=training/.generated/task2/data.yaml split=test imgsz=320
```

Review per-class errors and independent real photos before release. Synthetic metrics alone
are insufficient. Use validation and development photos for tuning; keep test and acceptance
sets held out. See [evaluation and deployment](docs/evaluation.md) for prediction commands,
nearest-target checks, pipeline tests, and the dataset improvement loop.

After Task 1 passes acceptance, copy the selected checkpoint to the PC runtime:

```powershell
Copy-Item training/runs/task1/yolov8n-targets/weights/best.pt pc_server/models/best.pt
```

In Bash, use `cp` in place of `Copy-Item`.

For Task 2, export and copy the selected model and labels into `rpi/models/`:

```sh
python -m training.export_int8 --weights training/runs/task2/yolov8n-arrows/weights/best.pt --publish
```

Omit `--publish` to export only to `training/exports/task2/`. The export uses 320×320 input,
batch size 1, INT8 calibration, and `nms=False`. Verify that it loads and invokes on the actual
Pi, then record checksum, tensors, quantization, and latency in
[calibration records](../../docs/calibration.md).

## 6. Troubleshooting

| Problem | Next step |
|---|---|
| Missing/TODO/empty labels or invalid boxes | Complete and review the [YOLO annotations](docs/dataset.md#manual-annotations); rerun validation. |
| A class cannot appear in every split | Collect independent groups containing it; see [source groups](docs/dataset.md#source-groups). |
| Duplicate data or stale scenes after recipe changes | Retire old image **and** annotation scene folders using the [regeneration procedure](docs/dataset.md#regenerating-changed-recipes). |
| Synthetic provenance mismatch | Check the recipe and labels; preserve [provenance validation](docs/dataset.md#validation-and-split-records). |
| Backend unavailable or training falls back to CPU | Check the installed PyTorch build and [backend probe](docs/environment.md), then try a short run. |
| Checkpoint missing or wrong model evaluated | Use the actual run directory printed by training, including its suffix. |
| Multiple TFLite candidates | Inspect and remove stale exports before retrying; output selection must be unambiguous. |

Track recipes, labels, provenance, class registries, configs, and manifests. Keep source photos,
generated datasets, runs, weights, and exports local; approved stand templates are explicit
tracked exceptions. Older synthesis modes remain in the [legacy guide](docs/legacy-synthesis.md).
