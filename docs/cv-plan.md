# CV model plan: synthetic dataset and training

Written 2026-09-04. Task 1 is week 8, Task 2 is week 9.

The plan is to train YOLO on a synthetic dataset built by compositing extracted symbol cards
onto real lab backgrounds, and to validate it on a small set of real photos that the model never
trains on.

Budget: about 22 hours of work, roughly 3 days. Training itself is about 1 hour of that.

## 1. Decisions taken up front

| Decision | Choice | Why |
|---|---|---|
| Model | `yolov8n.pt`, detection | The prior-year team used `yolov8n-seg`. We do not need masks. Detection trains faster and runs faster |
| Image size | 640 | Inference runs on the laptop, not the Pi, so there is no need to shrink it |
| Where to train | Kaggle, free T4, 30 GPU-hours a week | On CPU one run is 10 to 20 hours. On a T4 it is about 1 hour |
| Classes | 31 | IDs 11 to 40 from the briefing table, plus bull's-eye as class 31 |
| Training data | Synthetic only | Labels are free and exact, and the set can be regenerated when the lab changes |
| Validation data | Real photos only | A synthetic validation score does not predict arena performance. Blocked until the Pi camera is free, so see section 3 for the stand-in |

Class list, in this order, so the index maps cleanly:

| Index | ID | Symbol | Index | ID | Symbol |
|---|---|---|---|---|---|
| 0 to 8 | 11 to 19 | digits 1 to 9 | 19 | 30 | U |
| 9 | 20 | A | 20 | 31 | V |
| 10 | 21 | B | 21 | 32 | W |
| 11 | 22 | C | 22 | 33 | X |
| 12 | 23 | D | 23 | 34 | Y |
| 13 | 24 | E | 24 | 35 | Z |
| 14 | 25 | F | 25 | 36 | Up arrow |
| 15 | 26 | G | 26 | 37 | Down arrow |
| 16 | 27 | H | 27 | 38 | Right arrow |
| 17 | 28 | S | 28 | 39 | Left arrow |
| 18 | 29 | T | 29 | 40 | Stop |
| | | | 30 | none | Bull's-eye |

Bull's-eye is not in the ID table. It is its own class and must be reported separately, because
the recovery logic needs to tell "bull's-eye seen" apart from "nothing seen".

## 2. Directory layout

```
image-rec/
  cards/                 31 rectified PNGs with alpha, one per class
  backgrounds/
    clips/               raw lab videos
    frames/              sampled frames, deduplicated
    floorlines.json      frame name -> two floor-line points
    splits.json          frame name -> train or val
  real/                  the real validation set, hand labelled
    images/  labels/
  generated/
    images/  labels/
  generate.py            the compositor
  verify.py              the gates in section 6
  data.yaml
  runs/
```

Hyphen, not a space. The prior-year repo used `image rec/` with a space and every shell command
against it has to be quoted.

## 3. Phase 1: the validation set

The real validation set is the gate for everything else, so it normally comes first. The Pi
camera is not available yet, so it is split in two.

### 3a. Proxy validation, now (1 hour)

Enough to catch a catastrophic domain gap early. Not enough to trust.

1. The 6 photos of the actual test environment that already exist. Label them by hand. Six
   images is not a validation set, but it is the only thing available that has the real lighting
   in it, and it is what gate 5 in section 7 compares against.
2. The validation split of the public Roboflow dataset
   (`universe.roboflow.com/my-space-gprvy/yukto-s-c/dataset/61`). Different lab, different
   camera, but real photos with real sensor noise, blur and compression. A model trained on
   synthetic data that scores near zero on this is broken in a way that has nothing to do with
   our arena.

Treat both as smoke tests. Do not tune anything on six images.

### 3b. Real validation, the moment the camera is free (3 hours)

This is a hard gate before Task 1. Book it the day the RPi owner has the camera working.

1. Set the arena up the way it will be on assessment day. Same lights, same floor.
2. With the actual Pi camera on the actual robot, capture 100 to 150 frames at the standoff the
   planner produces. Vary the obstacle, the symbol, the lighting, the surrounding clutter.
3. Label them by hand. About 2 hours. There is no shortcut, and this is the only honest number
   the project will produce.
4. Put them in `real/`. **Never train on this set.** Not once, not "just to see".

If a Pi camera can be borrowed without the robot, do this earlier. The sensor is what matters,
not the chassis. Hold it at the camera's real height and standoff and it is good enough.

### 3c. It also settles which model ships

Two CV models are being built for this project. The real validation set is the thing that
decides which one goes into Task 1, and it decides it with a number instead of an argument.

Run both models on the same held-out real set, compare mAP50 and per-class recall, ship the
winner. This is also why the inference contract in section 10 should be agreed with the RPi
owner independently of either model: same request, same response, model file swappable. Then
the choice is a one-line change on the day, not a rewrite.

## 3d. Revised order, given the camera is blocked

| Order | Phase | Blocked by |
|---|---|---|
| 1 | 3a. Proxy validation | Nothing |
| 2 | Phase 2. Card extraction | Needs the 31 cards printed and any camera |
| 3 | Phase 3. Backgrounds | Needs lab access, not the robot |
| 4 | Phase 4. Compositor | Nothing. Pure code |
| 5 | Phase 5. Gates | Gate 5 uses the 6 real photos from 3a |
| 6 | Phase 6. Training | Nothing |
| 7 | **3b. Real validation** | **The Pi camera. Chase this weekly** |
| 8 | Phase 7. Iterate | 3b. This is where the work actually gets directed |
| 9 | Phase 8. Handoff | Agree the contract early, build it last |

Phases 2 to 6 all run without the camera, so nothing is idle. But note what this costs: until
3b exists, every number produced is a synthetic number, and synthetic numbers always look good.
Do not conclude the model works until it has been scored on real frames.

If the backgrounds have to be shot on a phone rather than the Pi camera, that is acceptable but
worth knowing: field of view and lens distortion will not match, which widens the domain gap
that 3b is there to measure.

## 4. Phase 2: card extraction

2 hours.

1. Photograph the 31 printed cards laid out on a grid.
2. Detect each card and crop it.
3. **Rectify each crop with a homography to a flat frontal square.** If the grid photo was taken
   at any angle, every card carries that perspective, and the compositor then warps it a second
   time. Rectifying first means the synthetic tilt is the only tilt.
4. Cut the symbol out to an alpha PNG. Keep the white card border, because the real obstacle
   shows the border too.
5. Eyeball all 31. They are the foundation of every generated image, so a bad one poisons a
   whole class.

## 5. Phase 3: backgrounds

2 hours.

1. Take videos in the lab at the camera's real height, ideally with the Pi camera itself. If a
   phone is used, the field of view and lens distortion will not match.
2. **Sample every 10th to 15th frame, not every frame.** Consecutive frames are near-identical.
   Extracting all of them inflates the set with duplicates and breaks the split in step 4.
3. Target 100 to 150 usable frames. That is plenty. 10,000 generated images from 120
   backgrounds is a normal ratio.
4. **Split by clip or location, not by frame.** If frame 412 goes to train and 413 to val, the
   split leaks and the val score is meaningless.
5. Floor lines: **click them, do not detect them.** Two clicks per frame in a small matplotlib
   script is about 10 minutes for 120 frames. A floor-line detector is 4 hours of code that will
   fail on the shiny patches and the cable trunking.
6. Vet the frames: drop the blurred ones, the ones with a person in shot, and any where the
   floor is not visible.

## 6. Phase 4: the compositor

5 hours. This is the main piece of code.

For each generated image: pick a background, place 1 to 3 obstacles on its floor line, give each
a random symbol, composite, then degrade the whole frame.

**Pose ranges.** These come from `algorithm/config.py`, so the synthetic distribution matches
what the planner will actually produce. That is the real advantage of doing this synthetically:
a photo shoot cannot target the deployment distribution this precisely.

| Parameter | Range | Source |
|---|---|---|
| Depth | 18 to 38 cm | `STANDOFF_MIN_CM` 25 to `STANDOFF_MAX_CM` 30, widened for margin |
| Lateral offset | plus or minus 12 cm | `LATERAL_TOLERANCE_CM` is 10 |
| Yaw | plus or minus 25 degrees | The robot does not always park square to the face |
| Roll | plus or minus 3 degrees | Chassis wobble |
| Obstacle size | 10 x 10 cm | `OBSTACLE_SIZE_CM` |
| Obstacles per image | 1 to 3 | Distractors are realistic, and see the labelling rule below |
| Symbol scale | derived from depth | Do not randomise scale independently, or the model learns a wrong size prior |

**Label every pasted symbol, including the far ones.** If three obstacles are pasted and only
the near one is labelled, the model is punished for correctly detecting the other two. That is
label noise aimed directly at the behaviour we want. Label all of them, and at inference pick
the largest or most central box.

**Degrade after compositing, never before.** A pasted PNG has a perfectly sharp alpha edge that
no real camera produces, and the model will learn "the object is the thing with the crisp
boundary". That cue does not exist at inference.

| Degradation | Range | Notes |
|---|---|---|
| Feather the paste mask | 1 to 2 px | Cheapest fix for the sharp-edge shortcut |
| Drop shadow under the panel | soft, short | Strong depth cue, and the floor line makes it easy |
| Motion blur | 0 to 3 px, directional | The capture happens just after the robot stops |
| Defocus blur | 0 to 2 px | |
| Gaussian noise | sigma 0 to 8 | |
| Brightness | 0.5 to 1.4 | Applied to the whole frame |
| Contrast | 0.7 to 1.3 | |
| White balance | mild shift | |
| JPEG | quality 55 to 92 | Save as JPEG at the quality the Pi produces. Free, and it removes a whole class of artifact |

**Randomise lighting, not card colour.** The real cards have a fixed appearance. Heavy colour
randomisation teaches invariance we do not need and spends model capacity on it. It also hurts
on the pairs that are already confusable.

Generate 8,000 to 12,000 images. Keep the class histogram flat.

## 7. Phase 5: verification gates

2 hours. All five must pass before the first training run. Skipping these is how a week
disappears into a model that was never going to work.

| # | Gate | Check |
|---|---|---|
| 1 | Boxes are correct | Draw boxes on 100 random generated images and look at every one. Each box tight on its symbol, correct class |
| 2 | Class balance | Histogram flat within about 10 percent |
| 3 | No split leak | No background frame, and no clip, appears in both train and val |
| 4 | No near-duplicates | Compare sampled frames pairwise. Anything above about 0.98 similarity, drop one |
| 5 | Realism | Put a synthetic image next to a real one at the same depth. If you can tell instantly which is which, the degradation is too weak |

Gate 1 and gate 5 are the ones that matter. The other three are cheap insurance.

## 8. Phase 6: training

1 hour wall clock on Kaggle.

```python
from ultralytics import YOLO

model = YOLO('yolov8n.pt')
model.train(
    data='data.yaml',
    epochs=60,
    imgsz=640,
    patience=20,
    fliplr=0.0,      # mandatory
    flipud=0.0,      # mandatory
    degrees=0.0,     # tilt is already in the compositor
    device=0,
)
```

`fliplr=0.0` and `flipud=0.0` are not optional. Ultralytics flips horizontally by default. A
horizontal flip turns a left arrow into a right arrow and corrupts most of the letters. The
prior-year script sets both to zero, and that is the one line to copy from it.

`degrees=0.0` because the compositor already varies yaw and roll with correct geometry.
Ultralytics rotation would rotate the box as an axis-aligned rectangle and loosen every label.

On Apple Silicon, `device='mps'` instead of CPU is 3 to 5 times faster, but Kaggle is still
faster and free.

## 9. Phase 7: iterate on the real number

4 hours, two or three runs.

| Metric | Target |
|---|---|
| Synthetic val mAP50 | above 0.95. This will be easy and means little |
| **Real val mAP50** | **above 0.85** |
| Real val per-class recall | above 0.8 for every class, not just on average |

Per-class recall matters more than the average here. One class at 0.3 recall means one obstacle
that never gets identified, and Task 1 scores per obstacle.

Watch these confusion pairs: 8 and B, 1 and 7, 5 and S, 2 and Z, U and V, G and 6, T and 7.
Arrows at high yaw are the other usual failure.

When real mAP is low:

| Symptom | Likely cause | Fix |
|---|---|---|
| Synthetic high, real low, across all classes | Domain gap | Strengthen the degradations. Check gate 5 again |
| One class bad | Bad card extraction, or that symbol is under-represented at high yaw | Re-extract the card, widen its pose sampling |
| Confuses a known pair | Not enough hard examples | Generate more of those two classes at small scale and high yaw |
| Good in the middle, bad at the edges of frame | Compositor never places obstacles near the frame edge | Widen the lateral placement |
| Misses distant obstacles | Only near obstacles were labelled | Fix the labelling rule in section 6 |

If real mAP stalls below 0.85 after three runs, add 200 to 300 real training images. Auto-label
them with the current model, correct the mistakes, and mix them in. Keep the real validation set
separate and untouched.

## 10. Phase 8: integration handoff

3 hours.

The RPi sends a frame, the service returns a result. Agree this shape with the RPi owner before
writing it, the same way the algorithm service contract was agreed:

```jsonc
// response
{
  "image_id": 11,        // 11 to 40, or null
  "confidence": 0.94,
  "bullseye": false      // true means a bull's-eye was seen, which is not "nothing seen"
}
```

Rules the service applies:

- Pick the largest box, or the most central one. Never just the highest confidence, because a
  confident detection of a distant obstacle beats a correct detection of the near one.
- Below the confidence threshold, return `image_id: null`.
- A bull's-eye is reported as `bullseye: true`, never as an ID. The recovery logic depends on
  telling it apart from "nothing seen".

Tune the confidence threshold on the real validation set, not on the synthetic one. The
prior-year code used 0.9, which is high. Pick the value that maximises real per-class recall
without producing false IDs.

Things to settle with the RPi owner:

1. Does inference run on the laptop or on the Pi? The prior-year team ran it on the laptop and
   the Pi sent frames. That is the right call: a Pi 4 CPU manages about 1 to 3 fps at 320.
2. What does the Pi do with `image_id: null`? Retry from a nudged pose, or move on?
3. Who owns the model file and who owns the inference server? Settle this now, not the night
   before Task 1.

## 11. Time budget

| Phase | Hours |
|---|---|
| 1a. Proxy validation | 1 |
| 1b. Real validation set | 3, blocked on the camera |
| 2. Card extraction | 2 |
| 3. Backgrounds | 2 |
| 4. Compositor | 5 |
| 5. Verification gates | 2 |
| 6. First training run | 1 |
| 7. Iterate | 4 |
| 8. Integration handoff | 3 |
| **Total** | **23** |

Of that, 19 hours can be done now. The 3 hours for the real validation set and part of the
iteration wait on the camera.

Building the generator costs more up front than photographing and labelling 3,000 images by
hand. It pays back the first time the set has to be regenerated, and it will be regenerated at
least twice: once when the lighting turns out different from expected, and once when a confusion
pair shows up in the real validation numbers.

## 12. What can be reused

From `SC2079/image rec/` in the reference repo:

- `trainer.py`, for the flip settings and the general shape. 8 lines.
- `serverCode.py`, for the inference service and the image stitching the checklist asks for.
- The public dataset at `universe.roboflow.com/my-space-gprvy/yukto-s-c/dataset/61`, useful as a
  sanity check that the training setup works before the synthetic set exists.
- The archived `.pt` files, for auto-labelling the real validation set as a first pass. Their
  classes should match, but verify the class order before trusting the output.
