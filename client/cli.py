# FT8 Propagation Tracker — CLI (headless) entry
from __future__ import annotations

import signal
import time

from .config import SERVER_ENDPOINT
from .collector import Collector
from .http_reporter import HttpReporter
from .models import PropagationReport
from .propagation_fetcher import PropagationFetcher
from .udp_listener import UdpListener


def run_cli(
    port: int,
    log,
    bind_ip: str = "",
    multicast: bool = False,
) -> None:
    def on_report(r: PropagationReport) -> None:
        reporter.submit(r)
        log.info("Report %s %s %s <-> %s", r.type, r.frequency, r.reporter_grid, r.remote_grid)

    fetcher = PropagationFetcher(log)
    collector = Collector(on_report, on_band_change=fetcher.notify_band)
    reporter = HttpReporter()
    fetcher.start()
    udp = UdpListener(
        port,
        collector.on_status,
        lambda msg, ts: collector.on_decode(msg, ts),
        collector.on_qso_logged,
        log,
        bind_ip=bind_ip,
        multicast=multicast,
    )
    udp.start()
    log.info("CLI mode: UDP port %s, server %s", port, SERVER_ENDPOINT)

    def shutdown(signum=None, frame=None) -> None:
        log.info("Shutting down...")
        fetcher.stop()
        udp.stop()
        reporter.shutdown()

    signal.signal(signal.SIGINT, shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, shutdown)

    while udp.is_alive():
        udp.join(timeout=1.0)
