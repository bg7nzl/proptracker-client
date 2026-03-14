# FT8 Propagation Tracker — main entry (argparse → GUI or CLI)
from __future__ import annotations

import argparse
import logging

from .cli import run_cli
from .config import CLIENT_VERSION, UDP_DEFAULT_IP, UDP_DEFAULT_PORT
from .gui import run_gui


def main() -> None:
    ap = argparse.ArgumentParser(description="FT8 Propagation Tracker client")
    ap.add_argument("--cli", action="store_true", help="No GUI, CLI mode")
    ap.add_argument("--udp-port", type=int, default=UDP_DEFAULT_PORT, help="UDP listen port")
    ap.add_argument(
        "--udp-ip",
        default=UDP_DEFAULT_IP,
        help="UDP bind address (multicast group if --multicast)",
    )
    ap.add_argument(
        "--multicast",
        action="store_true",
        help="Enable UDP multicast (use with --udp-ip 224.0.0.x)",
    )
    ap.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING"])
    args = ap.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger("ft8tracker")

    if args.cli:
        run_cli(args.udp_port, log, bind_ip=args.udp_ip, multicast=args.multicast)
    else:
        run_gui(args.udp_port, log, bind_ip=args.udp_ip, multicast=args.multicast)


if __name__ == "__main__":
    main()
