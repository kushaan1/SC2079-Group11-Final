# SC2079 — Multi-Disciplinary Design Project (Group 11)

NTU SC2079 MDP. A robotic system that autonomously explores a known arena, drives up to obstacles,
recognises the images on them, and talks to an Android tablet over Bluetooth.

Five subsystems: **STM32 firmware**, **Raspberry Pi** (central hub), **image recognition**,
**algorithms + simulator**, and an **Android app**.

## Status

The standalone computer-vision foundation is implemented in **`image-rec/`**. Task 1 uses a host-PC
Flask/Ultralytics service; Task 2 uses a Python 3.7-compatible TFLite pipeline on Raspberry Pi OS
Buster. Model weights and physical calibration are still required before hardware deployment.

## What's here

- **`AGENTS.md`** — the project brief. Architecture, arena spec, task rules, algorithms reference,
  repo conventions. Read this before writing any code.
- **`docs/`** — official course PDFs: MDP and algorithms briefings, the assessment checklist, RPi
  setup and image recognition guides, robot car layout, multithreading lab manuals, and a path
  planning reference.
- **`image-rec/`** — standalone computer-vision service, Buster camera/comms adapters, TFLite local
  inference, runners, tests, and setup instructions.

## Graded tasks

- **Task 1 — image recognition** (Week 8): visit every obstacle, recognise and report each image ID.
  6-minute timeout.
- **Task 2 — fastest car** (Week 9): start in a carpark, navigate two arrow-marked obstacles, return.

Full assessment breakdown and deadlines are in `AGENTS.md` §6.
