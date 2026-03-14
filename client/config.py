# FT8 Propagation Tracker — client build-time configuration
from __future__ import annotations

import os

SERVER_ENDPOINT = os.environ.get(
    "FT8T_ENDPOINT",
    "http://18.182.219.47/api/v1/reports",
)
HEALTH_ENDPOINT = SERVER_ENDPOINT.rsplit("/reports", 1)[0] + "/health"
PROPAGATION_ENDPOINT = SERVER_ENDPOINT.rsplit("/v1/", 1)[0] + "/v2/propagation"
UDP_DEFAULT_PORT = 2237
UDP_DEFAULT_IP = "127.0.0.1"
REPORT_BATCH_SIZE = 50
REPORT_INTERVAL_SEC = 30
FETCH_INTERVAL_SEC = 180
CLIENT_VERSION = "0.3.0"
WSJT_MAGIC = 0xADBCCBDA
