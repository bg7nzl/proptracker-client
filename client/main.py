# FT8 Propagation Tracker — main entry (argparse → GUI or CLI)
from __future__ import annotations

import argparse
import logging

from .cli import run_cli
from .config import (
    UDP_DEFAULT_PORT,
    UDP_MULTICAST_IP,
    UDP_UNICAST_IP,
    set_server_endpoint,
)
from .gui import run_gui


def main() -> None:
    ap = argparse.ArgumentParser(description="FT8 Propagation Tracker client")
    ap.add_argument("--cli", action="store_true", help="No GUI, CLI mode")
    ap.add_argument(
        "--udp-port",
        type=int,
        default=None,
        metavar="PORT",
        help="UDP listen port (default 2237; required with --unicast/--multicast)",
    )
    ap.add_argument(
        "--udp-ip",
        default=None,
        metavar="IP",
        help="UDP bind address (default 127.0.0.1 unicast, 224.0.0.73 multicast); required with --unicast/--multicast",
    )
    ap.add_argument(
        "--unicast",
        action="store_true",
        help="Lock to unicast; requires --udp-ip and --udp-port (no mode toggle in GUI)",
    )
    ap.add_argument(
        "--multicast",
        action="store_true",
        help="Lock to multicast; requires --udp-ip and --udp-port (no mode toggle in GUI)",
    )
    ap.add_argument(
        "--endpoint",
        default=None,
        metavar="URL",
        help="Server base URL, e.g. http://localhost:5000 (overrides default and FT8T_ENDPOINT env var)",
    )
    ap.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING"])
    ap.add_argument(
        "--api-key",
        default=None,
        metavar="KEY",
        help="API Key for authenticated reporting (optional, 32-char hex from admin)",
    )
    args = ap.parse_args()

    if args.endpoint is not None:
        set_server_endpoint(args.endpoint)

    if args.api_key is not None:
        key = args.api_key.strip()
        if len(key) != 32 or not all(c in "0123456789abcdefABCDEF" for c in key):
            ap.error("--api-key must be a 32-character hex string")
        args.api_key = key

    # Explicit mode: user chose --unicast or --multicast → must provide both --udp-ip and --udp-port
    explicit_udp_mode = args.unicast or args.multicast
    if args.unicast and args.multicast:
        ap.error("cannot specify both --unicast and --multicast")
    if explicit_udp_mode and (args.udp_ip is None or args.udp_port is None):
        ap.error("when using --unicast or --multicast you must specify both --udp-ip and --udp-port")

    port = args.udp_port if args.udp_port is not None else UDP_DEFAULT_PORT
    multicast = args.multicast
    if explicit_udp_mode:
        bind_ip = args.udp_ip
    else:
        bind_ip = args.udp_ip if args.udp_ip is not None else (UDP_MULTICAST_IP if multicast else UDP_UNICAST_IP)
    other_bind_ip = UDP_UNICAST_IP if multicast else UDP_MULTICAST_IP

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger("ft8tracker")

    api_key = args.api_key
    if args.cli:
        run_cli(port, log, bind_ip=bind_ip, multicast=multicast, api_key=api_key)
    else:
        run_gui(
            port,
            log,
            bind_ip=bind_ip,
            other_bind_ip=None if explicit_udp_mode else other_bind_ip,
            multicast=multicast,
            udp_locked=explicit_udp_mode,
            api_key=api_key,
        )


if __name__ == "__main__":
    main()
