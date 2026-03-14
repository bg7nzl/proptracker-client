# FT8 Propagation Tracker — HTTP reporter (queue + thread)
from __future__ import annotations

import json
import logging
import queue
import threading
import time

from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from .config import (
    CLIENT_VERSION,
    HEALTH_ENDPOINT,
    REPORT_BATCH_SIZE,
    REPORT_INTERVAL_SEC,
    SERVER_ENDPOINT,
)
from .models import PropagationReport

HEALTH_CHECK_INTERVAL_SEC = 30


class HttpReporter:
    def __init__(self) -> None:
        self._queue: queue.Queue[PropagationReport] = queue.Queue()
        self._last_success_time: float | None = None
        self._pending_count = 0
        self._is_connected: bool | None = None
        self._last_health_check = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def submit(self, report: PropagationReport) -> None:
        self._queue.put(report)

    def _check_health(self) -> bool:
        try:
            req = Request(HEALTH_ENDPOINT, method="GET")
            with urlopen(req, timeout=8) as resp:
                return resp.status == 200
        except (URLError, HTTPError, OSError) as e:
            logging.debug("Health check failed: %s", e)
        return False

    def _worker(self) -> None:
        self._last_health_check = time.monotonic()
        if self._check_health():
            self._is_connected = True
        else:
            self._is_connected = False
        batch: list[PropagationReport] = []
        last_send = time.monotonic()
        backoff = 1.0
        while not self._stop.wait(timeout=min(1.0, REPORT_INTERVAL_SEC)):
            now = time.monotonic()
            if now - self._last_health_check >= HEALTH_CHECK_INTERVAL_SEC:
                self._last_health_check = now
                if self._check_health():
                    self._is_connected = True
                else:
                    self._is_connected = False
            while len(batch) < REPORT_BATCH_SIZE:
                try:
                    r = self._queue.get_nowait()
                    batch.append(r)
                except queue.Empty:
                    break
            if batch and (
                len(batch) >= REPORT_BATCH_SIZE or (now - last_send) >= REPORT_INTERVAL_SEC
            ):
                if self._send_batch(batch):
                    batch = []
                    last_send = now
                    backoff = 1.0
                    self._last_success_time = time.time()
                    self._is_connected = True
                else:
                    self._is_connected = False
                    backoff = min(backoff * 2, 300.0)
                    self._stop.wait(timeout=backoff)
            self._pending_count = self._queue.qsize() + len(batch)

        for r in batch:
            self._queue.put(r)

    def _send_batch(self, reports: list[PropagationReport]) -> bool:
        body = json.dumps(
            {"client_version": CLIENT_VERSION, "reports": [r.to_dict() for r in reports]}
        ).encode("utf-8")
        req = Request(
            SERVER_ENDPOINT,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=15) as resp:
                if resp.status == 200:
                    return True
        except (URLError, HTTPError, OSError) as e:
            logging.debug("Report POST failed: %s", e)
        return False

    @property
    def last_success_time(self) -> float | None:
        return self._last_success_time

    @property
    def pending_count(self) -> int:
        return self._pending_count

    @property
    def is_connected(self) -> bool | None:
        return self._is_connected

    def shutdown(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5.0)
