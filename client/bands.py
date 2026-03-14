# FT8 Propagation Tracker — band mapping (must match server bands.py)
from __future__ import annotations

BAND_RANGES: list[tuple[str, int, int]] = [
    ("160m", 1_800_000, 2_000_000),
    ("80m", 3_500_000, 4_000_000),
    ("60m", 5_250_000, 5_450_000),
    ("40m", 7_000_000, 7_300_000),
    ("30m", 10_100_000, 10_150_000),
    ("20m", 14_000_000, 14_350_000),
    ("17m", 18_068_000, 18_168_000),
    ("15m", 21_000_000, 21_450_000),
    ("12m", 24_890_000, 24_990_000),
    ("10m", 28_000_000, 29_700_000),
    ("6m", 50_000_000, 54_000_000),
    ("2m", 144_000_000, 148_000_000),
]

VALID_BANDS = [b[0] for b in BAND_RANGES]


def freq_to_band(freq_hz: int) -> str | None:
    """Map frequency (Hz) to band; None if out of range."""
    for name, lo, hi in BAND_RANGES:
        if lo <= freq_hz <= hi:
            return name
    return None
