#!/bin/bash
# Run GridCodec MicroPython tests on connected device (e.g. ESP32, Pyboard).
# Requires: mpremote (pip install mpremote, or: python3 -m venv .venv && .venv/bin/pip install mpremote)
# Device: default first serial port, or set MPREMOTE_DEVICE=/dev/ttyACM0
#
# If "failed to access /dev/ttyACM0 (it may be in use)":
#   - Close Thonny, minicom, screen, or other serial terminals using the port.
# If "Permission denied": sudo usermod -aG dialout $USER
# Then run: sg dialout -c "./run_on_device.sh"  (or log out and back in)

set -e
cd "$(dirname "$0")"
DEV="${MPREMOTE_DEVICE:-/dev/ttyACM0}"

if command -v mpremote >/dev/null 2>&1; then
    MP=mpremote
elif [ -x "/tmp/.venv_mp/bin/mpremote" ]; then
    MP=/tmp/.venv_mp/bin/mpremote
else
    echo "mpremote not found. Install with:"
    echo "  python3 -m venv .venv && .venv/bin/pip install mpremote"
    echo "  then run: .venv/bin/mpremote connect $DEV fs cp gridcodec.py : && .venv/bin/mpremote connect $DEV fs cp test_gridcodec.py : && .venv/bin/mpremote connect $DEV run test_gridcodec.py"
    exit 1
fi

echo "Copying gridcodec.py and test_gridcodec.py to device..."
$MP connect "$DEV" fs cp gridcodec.py :
$MP connect "$DEV" fs cp test_gridcodec.py :
echo "Running tests on device..."
$MP connect "$DEV" run test_gridcodec.py
