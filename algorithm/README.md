# `algorithm/` — path planner and HTTP service

The algorithms subsystem. Plans a route that visits every obstacle, positions the robot to
photograph each image face, and emits motion instructions for the STM to execute.

**What the rest of the team needs from here:** one endpoint, `POST /pathfinding/`. Send an arena,
get back driving instructions. The contract is [`docs/protocols/algorithm-service.md`](../docs/protocols/algorithm-service.md)
— read that, not this file, if you are integrating.

Lineage and design decisions: [`PROVENANCE.md`](PROVENANCE.md).

---

## Setup

Needs **Python 3.11 or newer**. `python3` on a stock macOS is 3.9 and will fail with a
`SyntaxError` on `match` — check `python3 -V` before blaming anything else.

```sh
cd algorithm
python3.11 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

## Run

```sh
./.venv/bin/python app.py            # real planner
./.venv/bin/python app.py --stub     # canned responses, no planning  (see "Stub mode")
```

On startup it logs the URL to hand the RPi:

```
[INFO] Listening on 0.0.0.0:5000 (stub=no)
[INFO] RPi should POST to http://172.16.0.2:5000/pathfinding/
[INFO] Swagger UI: http://127.0.0.1:5000/openapi/swagger
```

Run it from *this* directory — `import config` and `from pathfinding...` are absolute imports that
need `algorithm/` to be the working directory.

### Host and port

Resolved in this order, first one wins:

| Source | Example |
|---|---|
| Command line | `python app.py --host 0.0.0.0 --port 5001` |
| Environment | `MDP_PORT=5001 python app.py` |
| `config.py` | `SERVER_HOST = "0.0.0.0"`, `SERVER_PORT = 5000` |

Two things not to get wrong on arena day:

- **Bind `0.0.0.0`, never `localhost`.** The RPi reaches this laptop over WiFi; a service on
  `127.0.0.1` is reachable only from the laptop itself. `0.0.0.0` is the default — don't "fix" it.
- **Never hardcode the laptop's IP.** The arena network (usually the RPi's hotspot) assigns it, so
  it changes between sessions. Read it off the startup log, or `ipconfig getifaddr en0`.

Port 5000 is a placeholder until the RPi owner confirms. Override with `MDP_PORT`, not an edit.

## Hit it with curl

```sh
curl -s -X POST http://127.0.0.1:5000/pathfinding/ \
  -H 'Content-Type: application/json' \
  -d '{
    "verbose": true,
    "robot": {"direction": "NORTH", "south_west": {"x": 0, "y": 0}, "north_east": {"x": 30, "y": 30}},
    "obstacles": [
      {"image_id": 11, "direction": "SOUTH", "south_west": {"x": 50,  "y": 90},  "north_east": {"x": 59,  "y": 99}},
      {"image_id": 12, "direction": "WEST",  "south_west": {"x": 120, "y": 60},  "north_east": {"x": 129, "y": 69}}
    ]
  }'
```

One segment per obstacle in visit order, each ending in `CAPTURE_IMAGE`, plus an `unreachable` list
of obstacles the plan skips. `image_id` must be 1–40 and identifies the obstacle, not the image — on
a real run it is the tablet's obstacle number (1–8), echoed back unchanged. Full field-by-field
description is in the protocol doc.

## Stub mode

```sh
python app.py --stub
```

Returns a schema-valid response with **no planning behind it** — one segment per obstacle, in the
order sent. It exists so the RPi and Android work can be tested end to end while the planner is
still being fixed.

- Stub responses carry the header **`X-MDP-Stub: true`**. Any test meant to exercise the real
  planner should assert that header is *absent*, so a forgotten `--stub` cannot pass for a working
  system.
- `path` and `unreachable` are always empty, even with `verbose: true`. Fabricated coordinates would
  let the tablet draw a route that looks plausible and is wrong, and a wrong picture is harder to
  debug than a missing one.

**Do not drive the robot from stub output, and do not measure timings against it.**

## Diagnostics

Both land in the process's working directory, and neither can fail a request:

| Artefact | What it is |
|---|---|
| `.replay/<timestamp>.json` | The raw body of every request received. Replay one with `curl -d @.replay/<file>` — being able to re-run the exact arena that failed at 2 am is worth more than it costs |
| `dump.txt` | ASCII picture of the last plan. `0` blocked, `1` free, `9` obstacle footprints, `2,3,4…` the cells of segment 1, 2, 3… North is up |

Paths are `config.REPLAY_DIR` and `config.DUMP_PATH`. Both are gitignored.

## Smoke test

```sh
./.venv/bin/python smoke.py     # 4 arenas, exits non-zero on any regression
```

Prints instruction streams and unreachable obstacles for four arenas with recorded baselines. It is
a **regression anchor, not an independent oracle** — the expected numbers were captured from this
planner, not from a known-good implementation. Its value is that a change which alters them becomes
visible instead of silent.

---

## Known limitations — read before trusting a plan

Real and current. None is a reason not to integrate; all are reasons not to believe a plan is
competition-ready.

1. **The planner cannot solve arenas at the competition's legal minimum obstacle spacing.** It
   reserves `footprint/2 + clearance` = `15 + 6` = **21 cm on every side** of an obstacle, so
   **42 cm of combined keep-out** between two of them — while the rules guarantee only **30 cm**.
   Obstacles in a line at legal spacing merge into an impassable wall and come back as
   `unreachable`. Measured: gaps of 30/35/40/41/42 cm give a zero-width corridor; 45 cm gives 3
   cells; 60 cm gives 18.

   The real chassis is ~18.6–18.8 cm wide and physically fits a 30 cm gap with ~11 cm to spare. It
   is the deliberately conservative 31 cm *planning* footprint that does not. The fix is to get
   `ROBOT_FOOTPRINT_CM + 2 × OBSTACLE_CLEARANCE_CM ≤ 28`; that decision is not yet made.

2. **Turning radii are not ours.** `config.TURN_RADIUS_CM` is `39/40/37/39` cm — the *prior-year*
   team's measurements on *their* car. The asymmetry between the four directions is real and large,
   and radius grows with speed. Every plan is only as true as these numbers. **This is the single
   highest-value thing the STM owner can hand over.**

3. **Standoff is a placeholder.** 25–30 cm, inherited. The course documents state the camera
   optimum three mutually inconsistent ways (~20 cm, a 25–30 cm band, and two disagreeing
   formulas in `AGENTS.md` §7.2). CV needs to pick one against the real lens.

4. **No visiting-order optimisation.** The route is greedy nearest-first, which does not satisfy
   checklist item **B.3** ("shortest-time Hamiltonian path"). Held–Karp over a precomputed
   all-pairs leg-cost matrix is the intended fix and is not built.

5. **No Dubins path implementation.** Quiz-assessed (`AGENTS.md` §7.4), not built.

6. **No simulator.** Checklist items **B.1, B.2 and B.3 all three** require one — each says the
   work must be *"shown on a simulator displaying a grid map of the movement area"*. This is the
   largest graded gap in the subsystem.

7. **No automated tests** beyond `smoke.py`.

8. **Latency is fine, so don't optimise it.** ~2.5 s for a 4-obstacle arena at 1 cm cells against a
   6-minute Task 1 budget. The A\* heuristic is written but never wired in, so the search is really
   Dijkstra — knowingly.

9. **Do not run the service under `python -O`.** The planner validates request geometry with bare
   `assert`s, which `-O` strips; the service maps them to clean 422s and cannot if they are gone.

## Layout

```
algorithm/
├── app.py                      ← entry point; --stub, host/port resolution
├── pathfinding_controller.py   ← the only module that knows about HTTP
├── config.py                   ← every tuneable number, with provenance comments
├── requirements.txt
├── PROVENANCE.md               ← lineage, the five fixes, design decisions
├── smoke.py                    ← 4-arena regression check
└── pathfinding/
    ├── report.py               ← UnreachableObstacle / UnreachableReason
    ├── search/{search,segment,straight,turn,instructions}.py
    └── world/{world,objective,primitives}.py
```

Two rules that hold throughout, per `AGENTS.md` §9.2 rule 1: **every tuneable number lives in
`config.py`** and nowhere else, and consumers read it **at call time** — never
`from config import X` at module level.
