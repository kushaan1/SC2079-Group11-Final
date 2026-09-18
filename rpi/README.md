# rpi/ — the Raspberry Pi program

Bluetooth in from the tablet, serial out to the STM, HTTP to the planner and the
image server. Design: `docs/superpowers/specs/2026-09-17-rpi-task1-design.md`.

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

Flags: `--fake-stm` (no STM connected), `--fake-camera` (no camera). Both together
let the tablet, planner and image server be tested end to end on the Pi before the
robot is ready.

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
   `BW <cm>` and the widened `FW` range (spec §3.2); until then the run stops
   at the first reverse with `Aborted at BW 10: ERR,UNKNOWN`, which is correct.
4. **Face search** — needs the tablet's `faceSearch` trigger.

The STM replies `ACK,<verb>` on receipt and `DONE,<verb>` when the motion ends;
that is the default (`RPI_STM_COMPLETION=DONE`). `ACK` is only for a firmware
whose ACK itself arrives at the end of the motion.

## Talking to the STM by hand

For calibration and for trying a new firmware command without the tablet:

```bash
python3 -m rpi.stm_console
```

Type commands as you would in CoolTerm — `FW 50`, `TL 90`, `PING`, `RANGE`,
`SEEK 30` — and the board's replies print as they arrive, with the time each
motion took. It uses the same driver as the runs (same line endings, the same
`ACK`→`DONE` wait and deadlines, `S` and re-`PING` on silence), so a command
that works here works in a run. `s` or Ctrl-C sends `S`; `quit` exits.

It needs the serial port to itself: stop the main program first
(`pkill -f '^python3 -m rpi'`). If it is still running, the console refuses to
start and says so. `--fake` runs the console against the fake STM on a laptop.
