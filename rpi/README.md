# rpi/ — the Raspberry Pi program

Bluetooth in from the tablet, serial out to the STM, HTTP to the planner and the
image server. Design: `docs/superpowers/specs/2026-09-22-rpi-task1-design-v2.md`
(Task 1) and `docs/superpowers/specs/2026-09-22-rpi-task2-design-v2.md` (Task 2).

## Develop (any OS)

```bash
python -m pip install -r rpi/requirements-dev.txt
python -m pytest rpi/tests -q
```

Run it on a laptop with no hardware at all:

```bash
python -m rpi --fake-stm --fake-camera
```

## Deploy (Raspberry Pi OS Buster, Python 3.7)

```bash
sudo apt-get install -y python3-picamera python3-venv
git clone <this repo> && cd SC2079-Group11-Final
python3 -m venv --system-site-packages .venv && . .venv/bin/activate
pip install -r rpi/requirements.txt
cp rpi/env.example rpi/.env   # then edit the two URLs
```

One-time setup. `sdptool add` (used by `bluetooth.sh`) only works when
`bluetoothd` runs in compatibility mode — without it the script fails with
"Could not open SDP session":

```bash
sudo sed -i 's|^ExecStart=.*bluetoothd$|& -C|' /lib/systemd/system/bluetooth.service
sudo systemctl daemon-reload && sudo systemctl restart bluetooth
```

Then pair the tablet once: `bluetoothctl` → `power on`, `discoverable on`,
`pairable on`, `agent on`, `default-agent`, pair from the tablet, `trust <MAC>`.

Each session, in two terminals:

```bash
bash rpi/bluetooth.sh                         # terminal 1: keeps /dev/rfcomm0 listening
set -a; . rpi/.env; set +a; python3 -m rpi    # terminal 2: the program
```

Flags: `--fake-stm` (no STM connected), `--fake-camera` (no camera), `--fake-arrows
left,right` (no image recognition: the Task 2 arrow reads are scripted, one
direction per obstacle, repeating for every run). The first two together let the
tablet, planner and image server be tested end to end on the Pi before the robot
is ready; all three make a laptop run the whole Task 2 sequence.

Logs: `RPI_LOG_FILE` (default `/home/pi/rpi.log`, rotating) and stdout.

## Bring-up on the Pi, in this order

Each step adds one real device. Do not skip ahead: a failure then has one cause.

1. **Tablet only** — `python3 -m rpi --fake-stm --fake-camera` with the planner
   running on the laptop. Press F on the tablet: the log shows `F`. Press
   IMAGE REC: the status panel shows `Planning...`, `Visiting n of n`, the robot
   marker steps through the route, and `Done`. If the image server is up too,
   `TARGET` lines appear from the fixture photo (whatever it recognises in a
   grey square — usually nothing, which is `B1: nothing recognised`).
2. **Camera** — drop `--fake-camera`. `MSG,B1: camera failed` means the camera
   itself: check `raspistill -o /tmp/t.jpg` works outside this program first.
3. **STM** — drop `--fake-stm`. The log's first lines must show `PING` and
   `PONG`. F/B/STOP from the tablet jog the car. IMAGE REC needs the STM's
   `BS <cm>` and the widened `FS` range (spec §3.2); until then the run stops
   at the first reverse with `Aborted at BS 10: ERR,UNKNOWN`, which is correct.
4. **Face search** — needs the tablet's `faceSearch` trigger.
5. **Task 2** — its own order, below.

The STM replies `ACK,<verb>` on receipt and `DONE,<verb>` when the motion ends;
that is the default (`RPI_STM_COMPLETION=DONE`). `ACK` is only for a firmware
whose ACK itself arrives at the end of the motion.

## Talking to the STM by hand

For calibration and for trying a new firmware command without the tablet:

```bash
python3 -m rpi.stm_console
```

Type commands as you would in CoolTerm — `FS 50`, `TL 90`, `PING`, `RANGE`,
`SEEK 30` — and the board's replies print as they arrive, with the time each
motion took. It uses the same driver as the runs (same line endings, the same
`ACK`→`DONE` wait and deadlines, `S` and re-`PING` on silence), so a command
that works here works in a run. `s` or Ctrl-C sends `S`; `quit` exits.

It needs the serial port to itself: stop the main program first
(`pkill -f '^python3 -m rpi'`). If it is still running, the console refuses to
start and says so. `--fake` runs the console against the fake STM on a laptop.

## Task 2 on the Pi, in this order

Design: `docs/superpowers/specs/2026-09-22-rpi-task2-design-v2.md`. The STM side is
proposed in `docs/rpi-stm-handover.md` §5 and not yet confirmed; until the STM
answers, `SEEK`/`ROUND`/`HOME`/`RANGE` are the plan's proposal, sent as written —
if the real firmware disagrees, the run stops at the first `Aborted at SEEK 30:
ERR,UNKNOWN`-style line, which is correct, not a bug.

1. **Sensor and seek by hand** — over CoolTerm, `RANGE` must answer `RANGE,<cm>`
   and `SEEK 30` must drive to 30 cm from a box and answer `DONE,SEEK,<cm>`.
2. **Rehearsal, no camera, no WiFi** — `python3 -m rpi --fake-camera --fake-arrows left,right`,
   then FASTEST on the tablet: the car seeks, rounds obstacle 1 on the left, seeks,
   rounds obstacle 2 on the right and comes home, narrated on the tablet. This is
   the STM team's loop for tuning the manoeuvres; change the two directions to
   rehearse the other paths. STOP is safe at any point: every run reads the
   script from the top.
3. **Real arrows against the laptop** — drop `--fake-arrows` and `--fake-camera`,
   with the image server up (`RPI_VISION_URL`) and an arrow printout in front of
   the car. `MSG,Vision server unreachable` at the start means the server, not
   the run. `Arrow 1: no vote, nudging back 10 cm` means the model saw nothing it
   was sure of; the run backs off and tries again for `RPI_ARROW_BUDGET_S`.
4. **On-Pi model** — `RPI_ARROW_SOURCE=tflite`, with `best_arrows.tflite` and
   `arrow-labels.json` (from the CV branch's `image-rec/training/export_int8.py`)
   copied into `rpi/models/`, and:

   ```bash
   sudo apt-get install -y python3-opencv
   pip install --extra-index-url https://google-coral.github.io/py-repo/ tflite_runtime==2.5.0
   ```

   (`python3-opencv` brings NumPy; the venv sees both through
   `--system-site-packages`.) `MSG,Arrow source not configured` means a file or
   the wheel is missing; `Arrow model failed to load: ...` names the reason.
   Whichever source decides the direction, every read frame is also POSTed to
   the PC server for storage (`RPI_VISION_URL`) — Task 2's raw-image-with-
   bounding-box requirement applies just as it does for Task 1.

Both arrow models must be trained with `fliplr: 0` — already the case in
`jerick-cv`'s `train.py` — and pass the left/right confusion run in the spec
(§3.2) before a real run: a model trained without that setting would mirror
half its left arrows into right arrows.

**Still open before this is competition-ready** (Task 2 spec §0, §9): whether
`ARROW_SOURCE` should default to `http` or `tflite` — Jerick's `image-rec`
architecture builds no PC-server path for Task 2 arrows at all — and the STM
team's confirmation of `RANGE`/`SEEK`/`ROUND`/`HOME`. Neither blocks the
rehearsal above; both matter before a real run.
