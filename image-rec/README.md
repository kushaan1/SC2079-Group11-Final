# SC2079 computer vision

This directory is a standalone computer-vision subsystem with two decoupled deployments:

```text
Task 1: PiCamera -> RPi HTTP client -> host Flask -> Ultralytics .pt -> raw/annotated captures
Task 2: PiCamera -> local tflite-runtime -> YOLO post-processing -> N-of-M arrow agreement -> STM
```

The host and Pi share only the versioned objects in `vision/`. Model weights are intentionally
ignored by Git. The service does not depend on the algorithm, Android, RPi hub, or STM repositories
to run its unit tests.

## Layout

```text
image-rec/
|-- config/                     environment-variable examples
|-- training/                   annotation, split, training, and export pipeline
|-- pc_server/
|   |-- app.py                  Flask API on port 4000
|   |-- detector.py             thread-safe Ultralytics adapter
|   |-- storage.py              asynchronous raw/annotated image persistence
|   |-- stitch.py               Task 1 verification-sheet generator
|   `-- models/best.pt          supplied locally; never committed
|-- rpi/
|   |-- camera/buster_stream.py legacy threaded PiCamera capture
|   |-- comms/                   HTTP, JSON serial, and RFCOMM adapters
|   |-- inference/              TFLite preprocessing, YOLO parsing, NMS, consensus
|   `-- models/
|       |-- best_arrows.tflite  supplied locally; never committed
|       `-- arrow-labels.json   class order matching the exported model
|-- vision/                     class map, contracts, and configuration
|-- test1_runner_rpi.py
|-- test2_runner_rpi.py
`-- tests/
```

The complete dataset and model-training workflow is documented in
[`training/README.md`](training/README.md). Images and weights remain local; annotations, class
registries, task configuration, tests, and generated split manifests are versioned.

Cross-subsystem contracts live in [`../docs/protocols`](../docs/protocols). The Task 1 HTTP API is
defined by `image-recognition-openapi.yaml`; STM and Android messages are newline-delimited JSON
with schemas under `schemas/`.

## Task 1 host setup

Use Python 3.9 or newer on the host PC. From this directory:

```powershell
py -m venv .venv-pc
.\.venv-pc\Scripts\Activate.ps1
python -m pip install -r requirements-pc.txt
```

Copy the trained YOLOv8 weights to `pc_server/models/best.pt`. Export the variables from
`config/pc.env.example` with your preferred process manager; the code reads the operating-system
environment directly and does not silently load `.env` files. Start the development server with:

```powershell
python -m pc_server.app
```

For a sustained run, use Waitress rather than Flask's development server:

```powershell
waitress-serve --host=0.0.0.0 --port=4000 --call pc_server.app:create_app
```

Smoke test the machine-checkable request contract:

```powershell
curl.exe -F "object_id=obstacle-1" -F "image=@sample.jpg" http://localhost:4000/detect
```

Every accepted frame is queued to `captures/raw/` and `captures/annotated/`. An annotation contains
only the arena obstacle ID and the chosen bounding box; it does not overwrite the verification image
with a predicted class label. At the end of a run, build the mandatory raw-image sheet with:

```powershell
python -m pc_server.stitch --input captures/raw --output captures/stitched/task1.jpg
```

## Raspberry Pi OS Buster setup

The Pi code targets legacy 32-bit Raspberry Pi OS Buster and CPython 3.7. It deliberately uses
`picamera`, not `picamera2` or `libcamera`, and imports only `tflite_runtime.Interpreter` for local
inference. Install the Buster camera/OpenCV packages through apt, then create a virtual environment
that can see them:

```bash
sudo apt-get update
sudo apt-get install -y python3-opencv python3-picamera python3-venv
python3 -m venv --system-site-packages .venv-rpi
. .venv-rpi/bin/activate
python -m pip install --upgrade "pip<24.1"
python -m pip install -r requirements-rpi.txt
```

The requirements file uses Google's Coral wheel index because it provides a CPython 3.7 `armv7l`
wheel for `tflite-runtime` 2.5.0. Do not replace it with full TensorFlow, PyTorch, or Ultralytics on
the Pi. A newly exported TFLite model can use operators unavailable in the older runtime, so loading
and invoking the exact model on the competition Pi is a release gate.

Copy the quantized arrow model to `rpi/models/best_arrows.tflite`. Edit
`rpi/models/arrow-labels.json` so its list order exactly matches the model's output class indices.
The included starter assumes class 0 is `Left Arrow` and class 1 is `Right Arrow`.

Export values from `config/rpi.env.example`, especially the host PC's actual IP address. Then run:

```bash
# Task 1: capture and classify one known arena obstacle
python test1_runner_rpi.py obstacle-1 --serial --android

# Task 2: local inference; commit only after 3 agreeing frames in a window of 5
python test2_runner_rpi.py --serial --android
```

`--android` waits for an RFCOMM client before capture. Without `--serial` or `--android`, each runner
works as a narrower camera/inference demonstration. Task 2 sends only `execute_left_route` or
`execute_right_route`; steering angles, speeds, and S-curves belong in calibrated STM configuration.

## Supported TFLite output

`TFLiteYoloDetector` expects one NHWC image input and one raw YOLO detection output. It accepts
`[1, 4+C, N]`, `[1, N, 4+C]`, and the corresponding `5+C` objectness variants. Boxes must be
centre-X, centre-Y, width, height in model pixels or normalized coordinates. The adapter handles:

- RGB conversion and aspect-preserving letterboxing;
- floating-point, `uint8`, or `int8` tensors using TFLite quantization metadata;
- reversal of padding and scale into source-frame coordinates;
- confidence filtering and class-aware non-maximum suppression; and
- mapping to competition IDs 38/39 for Task 2.

Models exported with an embedded NMS/end-to-end six-column output need a separate parser and should
fail fast instead of being guessed. Confirm tensor shapes with the deployment model before a run.

## Configuration and failure behavior

All adjustable values are in `vision/config.py` and the two example environment files. Record camera
and confidence tuning in [`../docs/calibration.md`](../docs/calibration.md); do not edit constants into
runners.

| Condition | Defined behavior |
|---|---|
| Invalid or oversized Task 1 upload | HTTP 400 or 413; no inference command is emitted |
| Competition target seen | `status=target`, ID 11-40 |
| Bull's-eye seen | `status=bullseye`, `competition_id=null`; reverse/reposition recovery may run |
| No recognised object | `status=no_detection`; never guessed as a target |
| Task 2 confidence/consensus not met | Time out so the orchestrator can re-approach and recapture |
| Serial acknowledgement missing | Raise a timeout; do not assume motion completed |
| Unsupported contract version | Reject the message rather than interpreting it loosely |

## Tests

Host-side tests use fake models, serial devices, and HTTP dependencies, so no weights or hardware are
needed:

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt Flask numpy opencv-python-headless
.\.venv\Scripts\python -m pytest -q
```

The tests cover class mapping, versioned result contracts, endpoint behavior, TFLite tensor parsing,
quantization, NMS, temporal arrow agreement, serial framing, protocol schemas, and Python 3.7 syntax.
Physical camera, model-accuracy, UART, Bluetooth, and end-to-end latency checks still require the
actual Pi, STM32, Android tablet, and trained weights.
