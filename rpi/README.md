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
