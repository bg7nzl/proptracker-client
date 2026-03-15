# FT8 Propagation Tracker — collector (grid cache, produce PropagationReport)
from __future__ import annotations

import time
from typing import Callable

from .bands import freq_to_band
from .ft8_parser import FT8MessageParser
from .grid_utils import truncate_grid, validate_grid
from .models import DecodeMessage, PropagationReport, QSOLoggedMessage, StatusMessage


class Collector:
    def __init__(
        self,
        on_report: Callable[[PropagationReport], None],
        on_band_change: Callable[[str | None], None] | None = None,
    ) -> None:
        self._on_report = on_report
        self._on_band_change = on_band_change
        self._my_call = ""
        self._my_grid = ""
        self._current_frequency = 0
        self._current_band: str | None = None
        self._grid_cache: dict[str, str] = {}
        self._today_start_ts = int(time.time()) // 86400 * 86400
        self._rx_today = 0
        self._tx_today = 0

    def on_status(self, msg: StatusMessage) -> None:
        self._my_call = (msg.de_call or "").strip()
        self._my_grid = truncate_grid(msg.de_grid or "")
        self._current_frequency = msg.frequency
        new_band = freq_to_band(msg.frequency) if msg.frequency else None
        if new_band != self._current_band:
            self._current_band = new_band
            if self._on_band_change:
                self._on_band_change(new_band)

    def on_decode(self, msg: DecodeMessage, timestamp_unix: int) -> None:
        if not self._my_grid or not self._current_frequency:
            return
        parsed = FT8MessageParser.parse(msg.message)
        if not parsed or not parsed.tx_call:
            return
        tx_call = parsed.tx_call.strip()
        if tx_call == self._my_call:
            return
        if parsed.grid:
            self._grid_cache[tx_call] = truncate_grid(parsed.grid)
            remote_grid = truncate_grid(parsed.grid)
        else:
            remote_grid = self._grid_cache.get(tx_call, "")
        if not remote_grid:
            return
        if not validate_grid(self._my_grid):
            return
        if self._my_grid == remote_grid:
            return
        self._rx_today += 1
        self._on_report(
            PropagationReport(
                type="rx",
                timestamp=timestamp_unix,
                frequency=self._current_frequency,
                reporter_grid=self._my_grid,
                remote_grid=remote_grid,
            )
        )

    def on_qso_logged(self, msg: QSOLoggedMessage) -> None:
        reporter_grid = truncate_grid(msg.my_grid or self._my_grid)
        remote_grid = truncate_grid(msg.dx_grid or "")
        if not remote_grid or not reporter_grid:
            return
        if reporter_grid == remote_grid:
            return
        self._tx_today += 1
        self._on_report(
            PropagationReport(
                type="tx",
                timestamp=msg.timestamp_off,
                frequency=msg.frequency,
                reporter_grid=reporter_grid,
                remote_grid=remote_grid,
            )
        )

    def get_stats(self) -> tuple[int, int]:
        return self._rx_today, self._tx_today
