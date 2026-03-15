# FT8 Propagation Tracker — data structures
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class PropagationReport:
    type: str  # "rx" | "tx"
    timestamp: int
    frequency: int
    reporter_grid: str
    remote_grid: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StatusMessage:
    """WSJT-X UDP type 1."""
    id: str
    frequency: int
    mode: str
    de_call: str
    de_grid: str
    dx_call: str
    dx_grid: str
    transmitting: bool
    decoding: bool


@dataclass
class DecodeMessage:
    """WSJT-X UDP type 2."""
    id: str
    is_new: bool
    time_ms: int
    snr: int
    dt: float
    df: int
    mode: str
    message: str


@dataclass
class QSOLoggedMessage:
    """WSJT-X UDP type 5."""
    id: str
    dx_call: str
    dx_grid: str
    frequency: int
    my_call: str
    my_grid: str
    timestamp_off: int


@dataclass
class ParsedMessage:
    """FT8 message text parse result."""
    tx_call: str
    rx_call: str | None
    grid: str | None
    is_cq: bool
