# FT8 Propagation Tracker — backward-compatible entry (delegates to package)
# Run: python src/client/ft8_tracker_client.py  or  python -m src.client.ft8_tracker_client
# PyInstaller uses this file as the script entry; pathex includes src so "client" package is found.
from __future__ import annotations

import os
import sys

# PyInstaller onefile + console=False 时 stdout/stderr 为 None，logging 等会报 'NoneType' has no attribute 'write'
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# When run as script (e.g. python src/client/ft8_tracker_client.py), ensure src is on path
_here = os.path.dirname(os.path.abspath(__file__))
_src = os.path.dirname(_here)
if _src not in sys.path:
    sys.path.insert(0, _src)

from client.main import main

if __name__ == "__main__":
    main()
