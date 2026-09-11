# Calibration record

Record measured values here before promoting a run-critical feature. Never replace an unknown value
with a convenient briefing or reference-team number. Keep the raw measurement log or video beside
the relevant checklist evidence.

## Computer vision baseline

| Date | Setting | Value | Conditions | Status / owner |
|---|---|---:|---|---|
| 2026-08-27 | Task 1 confidence floor | 0.60 | Software scaffold only; no trained model or arena images | **Uncalibrated** / assign |
| 2026-08-27 | Task 1 IoU threshold | 0.45 | Software scaffold only | **Uncalibrated** / assign |
| 2026-08-27 | Buster capture size | 640×480 | Starter configuration; Pi camera not measured | **Uncalibrated** / assign |
| 2026-08-27 | Buster frame rate | 20 fps | Starter configuration; end-to-end latency not measured | **Uncalibrated** / assign |
| 2026-08-27 | Task 2 model input | Read from TFLite tensor | Parser supports the model's declared NHWC size | Verify on exported model / assign |
| 2026-08-27 | Task 2 confidence floor | 0.75 | Conservative starter; no validation set scored | **Uncalibrated** / assign |
| 2026-08-27 | Task 2 temporal agreement | 3 of 5 frames | Conservative starter; latency not measured | **Uncalibrated** / assign |

## Required vision calibration run

For each exported model and competition-speed camera setup, record:

1. Git commit, dataset version, weights checksum, TFLite export command, and class-index order.
2. Pi model load success, input/output tensor names, shapes, dtypes, scales, and zero points.
3. Precision/recall and confusion matrix across every required target, with bull's-eyes separate.
4. Left/right false-decision rate over varied campus backgrounds, lighting, blur, and viewing angles.
5. End-to-end median, p95, and worst-case latency for capture, preprocess, inference, consensus, and
   command emission on the actual Pi.
6. Confidence and N-of-M selection rationale, including the number of arrow recaptures it causes.
7. Camera exposure, white balance, rotation, resolution, frame rate, lens position, and measured image
   size at the selected robot-to-obstacle standoff.

Turning radii, S-curve speeds, and standoff distance belong to the robot/algorithm calibration
sections when those subsystems are added. The computer-vision runners intentionally do not define
them.

## Model-training provenance

No model training or TFLite export had been executed when the training scaffold was added on
2026-08-27. For every accepted Task 1 and Task 2 checkpoint, attach or record:

| Field | Required value |
|---|---|
| Dataset identity | Committed split-manifest path and Git commit |
| Source integrity | Image and annotation SHA-256 checks passing against the manifest |
| Class contract | Class-registry path and SHA-256 |
| Training environment | `run-metadata.json` from the Ultralytics run |
| Validation results | Per-class precision, recall, confusion matrix, and background false positives |
| Deployment model | Weight/export SHA-256 and exact class-index order |
| Task 2 compatibility | Successful load/invoke with `tflite-runtime==2.5.0` on the actual Buster Pi |
| Task 2 performance | Median, p95, worst-case inference latency, and stable-arrow error rate |
