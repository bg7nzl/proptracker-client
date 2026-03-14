# FT8 Propagation Tracker — propagation data fetcher (Phase 2/3)
from __future__ import annotations

import json
import logging
import queue
import threading
from typing import Callable

from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from .config import CLIENT_VERSION, FETCH_INTERVAL_SEC, PROPAGATION_ENDPOINT


class PropagationFetcher:
    """Background fetch of propagation data. Caches per band; supports request_fetch and callback."""

    def __init__(
        self,
        log: logging.Logger,
        on_data_updated: Callable[[str], None] | None = None,
    ) -> None:
        self._log = log
        self._current_band: str | None = None
        self._lock = threading.Lock()
        self._latest: dict[str, dict] = {}
        self._running = False
        self._fetch_event = threading.Event()
        self._fetch_queue: queue.Queue[str] = queue.Queue()
        self._on_data_updated = on_data_updated
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, name="prop-fetch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._fetch_event.set()

    def notify_band(self, band: str | None) -> None:
        """Called when band changes; triggers immediate fetch."""
        if band and band != self._current_band:
            old = self._current_band
            self._current_band = band
            if old is not None:
                self._log.info("Band changed: %s -> %s, triggering fetch", old, band)
                self._fetch_event.set()
            else:
                self._current_band = band

    def request_fetch(self, band: str) -> None:
        """Request fetch for a specific band (e.g. when user clicks band in GUI)."""
        self._fetch_queue.put(band)
        self._fetch_event.set()

    def get_latest(self, band: str) -> dict | None:
        """Return latest propagation API response for band, or None."""
        with self._lock:
            return self._latest.get(band)

    def _run(self) -> None:
        while self._running:
            self._fetch_event.wait(timeout=FETCH_INTERVAL_SEC)
            self._fetch_event.clear()
            if not self._running:
                return
            band: str | None = None
            try:
                while True:
                    band = self._fetch_queue.get_nowait()
            except queue.Empty:
                pass
            if not band:
                band = self._current_band
            if not band:
                continue
            self._do_fetch(band)

    def _do_fetch(self, band: str) -> None:
        url = f"{PROPAGATION_ENDPOINT}?band={band}"
        try:
            req = Request(url, method="GET")
            req.add_header("User-Agent", f"FT8Tracker/{CLIENT_VERSION}")
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            with self._lock:
                self._latest[band] = data
            self._log.debug(
                "Fetched propagation for %s: %d reports",
                band,
                data.get("report_count", 0),
            )
            if self._on_data_updated:
                self._on_data_updated(band)
        except (URLError, HTTPError, OSError, ValueError) as e:
            self._log.debug("Propagation fetch failed for %s: %s", band, e)
