# FT8 Propagation Tracker — client build-time configuration
from __future__ import annotations

import os

_DEFAULT_ENDPOINT = "http://18.182.219.47/api/v1/reports"

SERVER_ENDPOINT = os.environ.get("FT8T_ENDPOINT", _DEFAULT_ENDPOINT)
HEALTH_ENDPOINT = SERVER_ENDPOINT.rsplit("/reports", 1)[0] + "/health"
PROPAGATION_ENDPOINT = SERVER_ENDPOINT.rsplit("/v1/", 1)[0] + "/v2/propagation"


def set_server_endpoint(base_url: str) -> None:
    """Override server endpoints at runtime (--endpoint CLI flag or test harness).

    base_url: server base URL, e.g. "http://localhost:5000".
              Trailing slash is stripped. /api/v1/reports etc. are appended automatically.
    """
    import src.client.config as _self
    base = base_url.rstrip("/")
    _self.SERVER_ENDPOINT = f"{base}/api/v1/reports"
    _self.HEALTH_ENDPOINT = f"{base}/api/v1/health"
    _self.PROPAGATION_ENDPOINT = f"{base}/api/v2/propagation"

UDP_DEFAULT_PORT = 2237
UDP_DEFAULT_IP = "127.0.0.1"
UDP_UNICAST_IP = "127.0.0.1"
UDP_MULTICAST_IP = "224.0.0.73"
UDP_MULTICAST_DEFAULT = False
REPORT_BATCH_SIZE = 50
REPORT_INTERVAL_SEC = 30
FETCH_INTERVAL_SEC = 180
CLIENT_VERSION = "0.3.0"
WSJT_MAGIC = 0xADBCCBDA
