# Training environment and configuration

[Back to model training](../README.md). Run commands from `image-rec/` in the training environment.

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

```sh
python -m pip install -r requirements-training.txt
```

Verify a CUDA or ROCm device before a long run:

```sh
python -c "import torch; print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'No CUDA/ROCm device'); print(torch.version.hip)"
```

ROCm is exposed through `torch.cuda` and uses `cuda:0`; `torch.version.hip` distinguishes it from
CUDA. Automatic backend preference is **CUDA → ROCm → DirectML → MPS → CPU**, with a real tensor
operation used to probe each candidate. Dataset and configuration errors do not trigger device
fallback.

## Training options and records

Defaults live in [task1.json](../configs/task1.json) and [task2.json](../configs/task2.json).
Set experiment defaults there; do not hardcode them in `train.py`.

| CLI option | Purpose |
|---|---|
| `--task task1` or `--task task2` | Select the dataset and model configuration (required). |
| `--backend auto` | Probe configured backends in order (default). |
| `--backend cuda`, `rocm`, `directml`, `mps`, or `cpu` | Require one backend; no fallback to another. |
| `--epochs 5` | Override the epoch count for a short run. |
| `--batch-size 4` | Override the batch size. |
| `--image-size 640` | Override the training image size. |

A probe checks a tensor operation; a short training run still needs to succeed.

Every successful run saves `run-metadata.json` with the chosen device, backend probes and failures,
effective arguments and seed, environment versions, and hashes of the config, class registry,
and split manifest. Use the printed run directory to locate these records and `weights/best.pt`.
