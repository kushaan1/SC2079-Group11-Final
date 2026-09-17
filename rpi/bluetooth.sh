#!/bin/bash
# Serve SPP on RFCOMM channel 1 and keep /dev/rfcomm0 listening across disconnects.
# Pair the tablet first with bluetoothctl (see README.md). Run in its own terminal.
set -e
CHANNEL="${RPI_BT_CHANNEL:-1}"
sudo pkill -x rfcomm 2>/dev/null || true
sudo rfcomm release 0 2>/dev/null || true
sudo sdptool add --channel="$CHANNEL" SP
exec sudo rfcomm watch /dev/rfcomm0 "$CHANNEL"
