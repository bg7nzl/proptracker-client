# FT8 Propagation Tracker — PSK Reporter fetcher (Phase 7)
#
# Single background thread cycles: out → in → call → out → in → call → ...
# On rate limit / failure: retry alternating 2 min / 5 min until success.
# After each success: wait 5 min before starting the next request.
# Caches are independent; old data kept until successfully refreshed.
from __future__ import annotations

import logging
import ssl
import threading
import time
import xml.etree.ElementTree as ET
from typing import Callable
from urllib.parse import quote

from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from . import config as _cfg
from .bands import freq_to_band

FLOW_START_SECONDS = -1800
REQUEST_TIMEOUT = 20
RETRY_DELAYS = [120, 300]  # alternating 2 min / 5 min
SUCCESS_COOLDOWN = 300     # 5 min after each successful fetch


def _default_ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context()


def _unverified_ssl_context() -> ssl.SSLContext:
    return ssl._create_unverified_context()


class PskReporterFetcher:
    """Single-thread sequential fetcher: out → in → call, with retry on rate limit."""

    def __init__(
        self,
        log: logging.Logger,
        get_grid: Callable[[], str | None],
        get_callsign: Callable[[], str | None],
    ) -> None:
        self._log = log
        self._get_grid = get_grid
        self._get_callsign = get_callsign
        self._lock = threading.Lock()
        # Independent caches: band -> set of 2-char field names
        self._out_cache: dict[str, set[str]] = {}
        self._in_cache: dict[str, set[str]] = {}
        self._heard_me_cache: dict[str, set[str]] = {}
        self._enabled = False
        self._ssl_warned = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        # Per-step status
        self._step_last_ok_time: dict[str, float] = {}  # step -> epoch of last success
        self._step_last_result: dict[str, bool] = {}     # step -> True=success False=fail
        self._current_step: str = ""
        self._next_step: str = ""       # which step is next in the queue
        self._next_step_time: float = 0  # epoch when _next_step will start

    def set_enabled(self, enabled: bool) -> None:
        was = self._enabled
        self._enabled = enabled
        if not enabled:
            self._stop_event.set()
            if was:
                with self._lock:
                    self._out_cache.clear()
                    self._in_cache.clear()
                    self._heard_me_cache.clear()

    def start(self) -> None:
        if not self._enabled:
            return
        self._stop_event.clear()
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(
                target=self._run, name="psk-fetch", daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def get_psk_data(self, band: str) -> tuple[set[str], set[str], set[str]]:
        """Return (in_only, out_only, both) for band, merged from independent out/in caches."""
        with self._lock:
            out_fields = set(self._out_cache.get(band, set()))
            in_fields = set(self._in_cache.get(band, set()))
        both = out_fields & in_fields
        return (in_fields - both, out_fields - both, both)

    def get_heard_me(self, band: str) -> set[str]:
        with self._lock:
            s = self._heard_me_cache.get(band)
        return set(s) if s else set()

    def get_status(self) -> dict[str, dict]:
        """Return per-step status for GUI display.

        Each step has: last_ok (epoch), ok (bool|None), active (bool),
        next_in (seconds until this step starts, >0 only if this is the next scheduled step).
        """
        now = time.time()
        result = {}
        with self._lock:
            next_step = self._next_step
            next_time = self._next_step_time
            for step in ("out", "in", "call"):
                last_ok = self._step_last_ok_time.get(step, 0)
                ok = self._step_last_result.get(step)
                active = (self._current_step == step)
                if step == next_step and next_time > 0 and not active:
                    next_in = max(0.0, next_time - now)
                else:
                    next_in = 0.0
                result[step] = {
                    "last_ok": last_ok,
                    "ok": ok,
                    "next_in": next_in,
                    "active": active,
                }
        return result

    # ── main loop ──────────────────────────────────────────────

    _STEPS = ["out", "in", "call"]

    def _run(self) -> None:
        """Cycle: out → in → call, forever."""
        idx = 0
        while self._enabled and not self._stop_event.is_set():
            step = self._STEPS[idx % len(self._STEPS)]
            next_step = self._STEPS[(idx + 1) % len(self._STEPS)]
            with self._lock:
                self._current_step = step
                self._next_step = ""
                self._next_step_time = 0
            ok = self._do_step(step)
            with self._lock:
                self._current_step = ""
            if ok:
                with self._lock:
                    self._step_last_ok_time[step] = time.time()
                    self._step_last_result[step] = True
                    self._next_step = next_step
                    self._next_step_time = time.time() + SUCCESS_COOLDOWN
                self._log.debug("PSK Reporter [%s] success, cooldown %ds", step, SUCCESS_COOLDOWN)
                self._stop_event.wait(timeout=SUCCESS_COOLDOWN)
            else:
                with self._lock:
                    self._step_last_result[step] = False
            idx += 1

    def _do_step(self, step: str) -> bool:
        """Execute one step with retry. Returns True on success, False if stopped/disabled."""
        retry_idx = 0
        while self._enabled and not self._stop_event.is_set():
            result = self._try_step(step)
            if result == "success":
                return True
            if result == "skip":
                return True  # no valid grid/call yet, treat as done
            # "retry" → rate limited or failed
            delay = RETRY_DELAYS[retry_idx % len(RETRY_DELAYS)]
            with self._lock:
                self._step_last_result[step] = False
                self._next_step = step
                self._next_step_time = time.time() + delay
            self._log.debug("PSK Reporter [%s] retry in %ds", step, delay)
            self._stop_event.wait(timeout=delay)
            if self._stop_event.is_set():
                return False
            retry_idx += 1
        return False

    def _try_step(self, step: str) -> str:
        """'success' | 'retry' | 'skip'"""
        field = self._valid_field()
        call = (self._get_callsign() or "").strip()

        if step == "out":
            if not field:
                return "skip"
            return self._fetch_out(field)
        elif step == "in":
            if not field:
                return "skip"
            return self._fetch_in(field)
        else:  # call
            if not call:
                return "skip"
            return self._fetch_heard_me(call)

    def _valid_field(self) -> str | None:
        grid = (self._get_grid() or "").strip().upper()
        if len(grid) < 2:
            return None
        f = grid[:2]
        if "A" <= f[0] <= "R" and "A" <= f[1] <= "R":
            return f
        return None

    # ── HTTP ───────────────────────────────────────────────────

    def _urlopen(self, url: str) -> bytes | None:
        ctx = _default_ssl_context()
        req = Request(url, method="GET")
        req.add_header("User-Agent", f"FT8Tracker/{_cfg.CLIENT_VERSION}")
        try:
            with urlopen(req, timeout=REQUEST_TIMEOUT, context=ctx) as resp:
                return resp.read()
        except ssl.SSLError as e:
            if not self._ssl_warned:
                self._ssl_warned = True
                self._log.warning("PSK Reporter SSL fallback: %s", e)
            try:
                ctx = _unverified_ssl_context()
                with urlopen(req, timeout=REQUEST_TIMEOUT, context=ctx) as resp:
                    return resp.read()
            except Exception as e2:
                self._log.debug("PSK Reporter fetch (unverified) failed: %s", e2)
                return None
        except HTTPError as e:
            if e.code == 503:
                self._log.warning("PSK Reporter 503")
            else:
                self._log.debug("PSK Reporter HTTP %s", e.code)
            return None
        except (URLError, OSError) as e:
            self._log.debug("PSK Reporter fetch failed: %s", e)
            return None

    def _is_rate_limited(self, body: bytes) -> bool:
        if not body or len(body) < 10:
            return False
        stripped = body.strip()
        return stripped.startswith(b"{") and b"message" in stripped

    def _parse_reports(self, body: bytes) -> list[dict] | None:
        """Parse XML → list of reports. Returns None if rate limited or parse failure (should retry)."""
        if self._is_rate_limited(body):
            self._log.warning("PSK Reporter rate limited")
            return None
        try:
            root = ET.fromstring(body)
        except ET.ParseError as e:
            self._log.warning("PSK Reporter XML parse failed: %s", e)
            return None
        reports = []
        for elem in root.iter():
            if elem.tag and "receptionReport" in elem.tag:
                loc_s = (elem.get("senderLocator") or elem.get("senderlocator") or "").strip()
                loc_r = (elem.get("receiverLocator") or elem.get("receiverlocator") or "").strip()
                freq_s = (
                    elem.get("frequency")
                    or elem.get("frequencyHz")
                    or elem.get("frequencyhz")
                    or ""
                )
                if not loc_s or not loc_r or not freq_s:
                    continue
                try:
                    freq = int(freq_s)
                except ValueError:
                    continue
                reports.append({
                    "senderLocator": loc_s,
                    "receiverLocator": loc_r,
                    "frequency": freq,
                })
        return reports

    @staticmethod
    def _valid_field_name(s: str) -> str | None:
        f = s[:2].upper() if len(s) >= 2 else ""
        if len(f) == 2 and "A" <= f[0] <= "R" and "A" <= f[1] <= "R":
            return f
        return None

    # ── individual fetches ─────────────────────────────────────

    def _fetch_out(self, field: str) -> str:
        """Fetch out (senderCallsign=field&modify=grid). 'success' or 'retry'."""
        url = (
            f"{_cfg.PSK_REPORTER_URL}"
            f"?rronly=1&noactive=1&flowStartSeconds={FLOW_START_SECONDS}"
            f"&senderCallsign={field}&modify=grid"
        )
        body = self._urlopen(url)
        if body is None:
            return "retry"
        reports = self._parse_reports(body)
        if reports is None:
            return "retry"
        band_out: dict[str, set[str]] = {}
        for r in reports:
            band = freq_to_band(r["frequency"])
            if band is None:
                continue
            rf = self._valid_field_name(r["receiverLocator"])
            if rf:
                band_out.setdefault(band, set()).add(rf)
        with self._lock:
            self._out_cache = band_out
        self._log.debug("PSK [out] %s: %d bands, %d fields",
                        field, len(band_out), sum(len(v) for v in band_out.values()))
        return "success"

    def _fetch_in(self, field: str) -> str:
        """Fetch in (receiverCallsign=field&modify=grid). 'success' or 'retry'."""
        url = (
            f"{_cfg.PSK_REPORTER_URL}"
            f"?rronly=1&noactive=1&flowStartSeconds={FLOW_START_SECONDS}"
            f"&receiverCallsign={field}&modify=grid"
        )
        body = self._urlopen(url)
        if body is None:
            return "retry"
        reports = self._parse_reports(body)
        if reports is None:
            return "retry"
        band_in: dict[str, set[str]] = {}
        for r in reports:
            band = freq_to_band(r["frequency"])
            if band is None:
                continue
            sf = self._valid_field_name(r["senderLocator"])
            if sf:
                band_in.setdefault(band, set()).add(sf)
        with self._lock:
            self._in_cache = band_in
        self._log.debug("PSK [in] %s: %d bands, %d fields",
                        field, len(band_in), sum(len(v) for v in band_in.values()))
        return "success"

    def _fetch_heard_me(self, callsign: str) -> str:
        """Fetch who-heard-me (senderCallsign=call exact). 'success' or 'retry'."""
        url = (
            f"{_cfg.PSK_REPORTER_URL}"
            f"?rronly=1&noactive=1&flowStartSeconds={FLOW_START_SECONDS}"
            f"&senderCallsign={quote(callsign)}"
        )
        body = self._urlopen(url)
        if body is None:
            return "retry"
        reports = self._parse_reports(body)
        if reports is None:
            return "retry"
        band_sets: dict[str, set[str]] = {}
        for r in reports:
            band = freq_to_band(r["frequency"])
            if band is None:
                continue
            rf = self._valid_field_name(r["receiverLocator"])
            if rf:
                band_sets.setdefault(band, set()).add(rf)
        with self._lock:
            self._heard_me_cache = band_sets
        self._log.debug("PSK [call] %s: %d bands", callsign[:8], len(band_sets))
        return "success"
