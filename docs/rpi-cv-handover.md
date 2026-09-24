# RPi → CV handover: what Task 2's arrow reader needs from you

For Jerick, from the RPi side. `rpi/arrow.py`'s `TfliteArrowSource` is written and tested against
your `image-rec` architecture; this is the two-file drop-in it's waiting on.

## What to hand over

1. **`best_arrows.tflite`** — your INT8-exported arrow model
   (`image-rec/training/export_int8.py`).
2. **`arrow-labels.json`** — the class-order file matching that export. Either a JSON list
   (`["Up Arrow", "Down Arrow", "Right Arrow", "Left Arrow"]`, index = output class index) or a
   JSON object keyed `"0"`, `"1"`, ... Each label just needs "left" or "right" somewhere in the
   text (case-insensitive) — exact wording doesn't matter, only which two contain which word.

Drop them at `rpi/models/best_arrows.tflite` and `rpi/models/arrow-labels.json` (that folder is
git-ignored on purpose — copy them there directly, don't commit them). If they end up somewhere
else, tell us and we'll point `RPI_ARROW_MODEL_PATH` / `RPI_ARROW_LABELS_PATH` at it instead.

## The one real compatibility risk

The code expects the model's raw output tensor to be `[1, 4 + num_classes, N]` (or the transposed
`[1, N, 4 + num_classes]`) — a standard Ultralytics YOLOv8 export with **NMS off**. If your export
has NMS baked in (an end-to-end 6-column output), this won't parse correctly and will need a
one-line change on our side once we see the actual shape. Tell us which export mode you used, or
we'll find out the first time we load the real file.

## What happens once the files are there

`RPI_ARROW_SOURCE` already defaults to `tflite`. Point `RPI_VISION_URL` at your PC server (used
only to store a copy of every frame read, for the competition's raw-image requirement — the
arrow decision itself stays on the Pi) and it should just work. If it doesn't, `MSG,Arrow model
failed to load: ...` on the tablet will say why.
