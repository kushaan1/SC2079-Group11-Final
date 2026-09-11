# Legacy synthesis workflows

[Back to model training](../README.md). Run commands from `image-rec/` in the training environment.

The workflows below are retained for reproducing or repairing older datasets. They are not part of
the current three-orientation automatic dataset loop.

### Archive A: replace a card directly in a photographed scene

This legacy mode keeps the photographed stand in its original environment and replaces its card in
place. Click each target or bull's-eye surface top-left, top-right, bottom-right, bottom-left.

```sh
python -m training.synthesize configure-in-scene --image training/synthesis/in-scene/hallway-01.jpg --output training/annotations/synthesis/hallway-01.json --recipe-id hallway-01 --source-group hallway-session-a --bullseyes 1

python -m training.synthesize generate --recipe training/annotations/synthesis/hallway-01.json
```

Use zero bull's-eyes only when no adjacent face is meaningfully visible.

### Archive B: manually compose stand instances

This legacy mode registers arbitrary RGBA templates and manually places an ordered list of stands.
Templates require genuine alpha transparency. Supply scene instances from farthest to nearest, with
exactly one `primary` and any remaining instances marked `distractor`.

```sh
python -m training.synthesize configure-template --image training/synthesis/stand-templates/right-facing.png --output training/annotations/synthesis/right-facing-template.json --bullseyes 1

python -m training.synthesize configure-scene --background training/synthesis/backgrounds/lab-03.jpg --output training/annotations/synthesis/lab-03-multi.json --recipe-id lab-03-multi --source-group lab-session-b --stand distractor:training/annotations/synthesis/right-facing-template.json --stand primary:training/annotations/synthesis/front-template.json

python -m training.synthesize generate --recipe training/annotations/synthesis/lab-03-multi.json
```

Rerun `configure-scene` with a revised far-to-near stand list and scoped `--overwrite` to move,
reorder, or remove legacy instances.

For real-image labels and Task 2 data, use [manual annotations](dataset.md#manual-annotations).
