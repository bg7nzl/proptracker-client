# FT8 Propagation Tracker — FT8 message text parser
from __future__ import annotations

import re

from .models import ParsedMessage

GRID_IN_MSG_RE = re.compile(r"[A-Ra-r]{2}[0-9]{2}(?:[a-x]{2})?\b")
CALLSIGN_RE = re.compile(
    r"^[A-Z0-9]{1,3}[0-9][A-Z0-9]{0,4}[A-Z](?:/[A-Z0-9]+)?$", re.IGNORECASE
)


class FT8MessageParser:
    """Parse FT8/FT4 decode message text: CQ call grid | rx_call tx_call info."""

    @staticmethod
    def parse(message: str) -> ParsedMessage | None:
        msg = (message or "").strip()
        if not msg:
            return None
        parts = msg.split()
        if len(parts) < 2:
            return None

        if parts[0].upper() == "CQ":
            idx = 1
            while idx < len(parts) and not CALLSIGN_RE.match(parts[idx]):
                idx += 1
            if idx >= len(parts):
                return None
            tx_call = parts[idx]
            grid = None
            if idx + 1 < len(parts) and GRID_IN_MSG_RE.match(parts[-1]):
                grid = parts[-1]
            return ParsedMessage(tx_call=tx_call, rx_call=None, grid=grid, is_cq=True)

        if len(parts) >= 2:
            rx_call = parts[0]
            tx_call = parts[1]
            grid = None
            if len(parts) >= 3 and GRID_IN_MSG_RE.match(parts[-1]):
                grid = parts[-1]
            return ParsedMessage(tx_call=tx_call, rx_call=rx_call, grid=grid, is_cq=False)

        return None
