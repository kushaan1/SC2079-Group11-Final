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

Use Python 3.9 or newer on the host PC. The service reads configuration from the process
environment; it does not silently load `.env` files. Run the Bash or PowerShell setup below from
this directory.

### Bash (Linux/macOS)

Create the virtual environment and install the host dependencies:

```bash
python3 -m venv .venv-pc
. .venv-pc/bin/activate
python -m pip install -r requirements-pc.txt
```

Copy the trained YOLOv8 weights to `pc_server/models/best.pt`, then load the example configuration
into the current shell:

```bash
set -a
source config/pc.env.example
set +a
```

Start the development server with:

```bash
python -m pc_server.app
```

For a sustained run, use Waitress rather than Flask's development server:

```bash
waitress-serve --host=0.0.0.0 --port=4000 --call pc_server.app:create_app
```

Smoke test the machine-checkable request contract:

```bash
curl --fail -F "object_id=obstacle-1" -F "image=@sample.jpg" http://localhost:4000/detect
```

Every accepted frame is queued to `captures/raw/` and `captures/annotated/`. An annotation contains
only the arena obstacle ID and the chosen bounding box; it does not overwrite the verification image
with a predicted class label. At the end of a run, build the mandatory raw-image sheet with:

```bash
python -m pc_server.stitch --input captures/raw --output captures/stitched/task1.jpg
```

When several target cards are visible, the detector still reports all of them. The selected
`detection` is the nearest card by bounding-box height. Cards within
`VISION_NEAREST_HEIGHT_TOLERANCE` of the largest height are ranked by an OpenCV quadrilateral
frontality score so a head-on card wins; confidence is the final fallback. Training annotations must
therefore cover the complete printed card consistently, not only the black glyph. Bullseyes remain a
separate recovery class but never displace a valid target selection.

### PowerShell (Windows)

From this directory:

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

## Step-by-step deployment across devices

Deploy the same Git revision to the host PC and Raspberry Pi. Model files are ignored by Git, so
copy them separately. This directory contains the host detector and Raspberry Pi vision adapters;
the STM32 firmware and Android application are separate components that integrate through the
versioned protocols in [`../docs/protocols`](../docs/protocols).

### 1. Prepare the model artifacts on the host PC

1. Obtain or train the validated Task 1 YOLOv8 model and copy it to
   `image-rec/pc_server/models/best.pt`.
2. Export the validated Task 2 model as raw-output INT8 TFLite and publish it into
   `image-rec/rpi/models/`:

   ```bash
   cd image-rec
   python -m training.export_int8 \
     --weights training/runs/task2/yolov8n-arrows/weights/best.pt \
     --publish
   ```

   If the export was performed elsewhere, copy `best_arrows.tflite` and the matching
   `arrow-labels.json` into `rpi/models/` instead. The label order must match the model output
   indices exactly.
3. Keep the model checksum and export metadata with the run record. Do not commit either model
   binary.

### 2. Deploy and start the host PC service

1. Check out the same repository revision used for the Pi and complete [Task 1 host setup](#task-1-host-setup).
2. Load `config/pc.env.example`, replacing values as needed. `VISION_PC_HOST` must be reachable
   from the Pi; use `0.0.0.0` to listen on all host interfaces and allow TCP port `4000` through
   the host firewall on the private robot network.
3. Start the service and leave it running:

   ```bash
   cd image-rec
   . .venv-pc/bin/activate
   set -a
   source config/pc.env.example
   set +a
   waitress-serve --host=0.0.0.0 --port=4000 --call pc_server.app:create_app
   ```

4. Verify locally and record the host PC's LAN address. Both checks must return HTTP 200 with
   `status=ok` and `schema_version=1.0`:

   ```bash
   curl --fail http://127.0.0.1:4000/health
   curl --fail http://<host-pc-ip>:4000/health
   ```

### 3. Deploy the vision runtime to the Raspberry Pi

1. Copy the source at the same revision to the Pi. For example, from the host PC repository root:

   ```bash
   rsync -av \
     --exclude='.venv*' \
     --exclude='captures/' \
     --exclude='pc_server/models/' \
     --exclude='rpi/models/*.tflite' \
     image-rec/ pi@<rpi-host>:~/SC2079-Group11-Final/image-rec/
   scp image-rec/rpi/models/best_arrows.tflite \
     pi@<rpi-host>:~/SC2079-Group11-Final/image-rec/rpi/models/
   scp image-rec/rpi/models/arrow-labels.json \
     pi@<rpi-host>:~/SC2079-Group11-Final/image-rec/rpi/models/
   ```

   Alternatively, clone or pull the repository on the Pi and copy only the two model files with
   `scp`. Do not copy the PC `.pt` model to the Pi; the Pi uses `tflite-runtime` only.
2. On the Pi, follow [Raspberry Pi OS Buster setup](#raspberry-pi-os-buster-setup). From the
   deployed directory, load the defaults and override the host address:

   ```bash
   cd ~/SC2079-Group11-Final/image-rec
   . .venv-rpi/bin/activate
   set -a
   source config/rpi.env.example
   set +a
   export VISION_PC_DETECT_URL="http://<host-pc-ip>:4000/detect"
   ```

   The example file is only a template; the process must receive these variables explicitly when
   it is started. Override `VISION_SERIAL_PORT` if the STM32 appears at a different device path.
3. Verify network access to the host detector and that the exact TFLite model can be loaded by the
   Pi runtime:

   ```bash
   curl --fail http://<host-pc-ip>:4000/health
   python -c 'from rpi.inference import TFLiteYoloDetector; from vision.config import RPiConfig; c = RPiConfig.from_env(); TFLiteYoloDetector(c.tflite_model_path, c.tflite_labels_path, c.tflite_confidence_threshold, c.tflite_iou_threshold); print("TFLite model loaded")'
   ```

4. Connect the Pi Camera, check the USB/UART device, and keep the Pi on the same private network
   as the host PC. The camera must be the legacy `picamera` device supported by Raspberry Pi OS
   Buster.

### 4. Flash and verify the STM32 connection

1. Flash the STM32F407VET6 firmware using the STM32 team's normal build/programming workflow.
   The firmware is not part of this image-recognition directory.
2. Configure the firmware for the documented RPi–STM32 serial protocol:
   newline-delimited UTF-8 JSON, protocol version `1.0`, 115200 baud, 8 data bits, no parity, and
   one stop bit. The STM32 must acknowledge a command with the same `message_id` only after that
   command has completed; see [`stm-serial-v1.md`](../docs/protocols/stm-serial-v1.md).
3. Keep steering, speed, turning radii, and Task 2 S-curve calibration in the STM32 configuration.
   The vision runner sends only `capture_ready`, `execute_left_route`, or `execute_right_route`;
   it does not send uncalibrated motion values.
4. With the STM32 powered and connected, confirm that the configured serial device is visible on
   the Pi before starting a runner:

   ```bash
   ls -l "$VISION_SERIAL_PORT"
   ```

### 5. Install and connect the Android tablet

1. Build/install the Android application from the Android subsystem and grant its required
   Bluetooth permissions. The Android application is not included in this directory.
2. Pair the tablet with the Pi and connect as the RFCOMM client on the configured channel
   (`VISION_BLUETOOTH_CHANNEL`, `1` by default).
3. Make the app buffer until `\n`, parse version `1.0`, and route `status`, `detection`, `error`, and
   `ack` messages according to [`android-bluetooth-v1.md`](../docs/protocols/android-bluetooth-v1.md).
   It should show selective status/detection updates rather than a raw serial dump. The app or PC
   must also expose the stitched raw-image sheet required for Task 1; the current stitch command
   writes it on the host PC.

### 6. Run the links in dependency order

1. Start the host PC service and verify `/health` from the Pi.
2. Power the STM32 and confirm its serial device is visible.
3. Start the Android app's connection screen.
4. Start the appropriate Pi runner. Because `--android` calls `accept()` before capture, start
   the runner before completing the Android RFCOMM connection:

   ```bash
   cd ~/SC2079-Group11-Final/image-rec
   . .venv-rpi/bin/activate
   # Task 1 adapter smoke test for one known obstacle
   python test1_runner_rpi.py obstacle-1 --serial --android

   # Task 2 arrow/route adapter smoke test
   python test2_runner_rpi.py --serial --android
   ```

5. Check that Task 1 returns a versioned `target`, `bullseye`, or `no_detection` result, that the
   STM32 acknowledges the command, that Android receives the corresponding status, and that the
   host PC contains files under `captures/raw/` and `captures/annotated/`.
6. After the run, create the verification sheet on the host PC:

   ```bash
   cd image-rec
   . .venv-pc/bin/activate
   python -m pc_server.stitch --input captures/raw --output captures/stitched/task1.jpg
   ```

The runners are standalone adapter demonstrations, not the complete Task 1 planner or Task 2
competition state machine. Keep them as link and hardware smoke tests before handing control to the
full RPi/algorithm orchestrator.

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

### Bash (Linux/macOS)

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt Flask numpy opencv-python-headless
python -m pytest -q
```

### PowerShell (Windows)

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt Flask numpy opencv-python-headless
.\.venv\Scripts\python -m pytest -q
```

The tests cover class mapping, versioned result contracts, endpoint behavior, TFLite tensor parsing,
quantization, NMS, temporal arrow agreement, serial framing, protocol schemas, and Python 3.7 syntax.
Physical camera, model-accuracy, UART, Bluetooth, and end-to-end latency checks still require the
actual Pi, STM32, Android tablet, and trained weights.
