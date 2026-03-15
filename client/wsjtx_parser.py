# FT8 Propagation Tracker — WSJT-X UDP binary parser
from __future__ import annotations

import struct
import time

from .config import WSJT_MAGIC
from .models import DecodeMessage, QSOLoggedMessage, StatusMessage


def _read_utf8(data: bytes, offset: int) -> tuple[str, int]:
    """Read Qt-style UTF-8 string: uint32 length (BE) then bytes. 0xFFFFFFFF = null."""
    if offset + 4 > len(data):
        return "", offset + 4
    (length,) = struct.unpack_from(">I", data, offset)
    offset += 4
    if length == 0xFFFFFFFF or length == 0:
        return "", offset
    if offset + length > len(data):
        return "", offset + length
    raw = data[offset : offset + length]
    offset += length
    try:
        return raw.decode("utf-8", errors="replace"), offset
    except Exception:
        return "", offset


def _qdatetime_to_unix(julian: int, ms_since_midnight: int) -> int:
    """Approximate QDateTime to Unix timestamp (UTC)."""
    if julian < 2440588:
        return int(time.time())
    days = julian - 2440588
    return days * 86400 + (ms_since_midnight // 1000)


class WsjtxParser:
    """Parse WSJT-X UDP packets. Big-endian, Qt-style strings."""

    @staticmethod
    def parse(data: bytes) -> StatusMessage | DecodeMessage | QSOLoggedMessage | None:
        if len(data) < 4:
            return None
        (magic,) = struct.unpack_from(">I", data, 0)
        if magic != WSJT_MAGIC:
            return None
        offset = 4
        if offset + 8 > len(data):
            return None
        (schema,) = struct.unpack_from(">I", data, offset)
        offset += 4
        (msg_type,) = struct.unpack_from(">I", data, offset)
        offset += 4
        id_str, offset = _read_utf8(data, offset)

        if msg_type == 1:
            return WsjtxParser._parse_status(data, offset, id_str)
        if msg_type == 2:
            return WsjtxParser._parse_decode(data, offset, id_str)
        if msg_type == 5:
            return WsjtxParser._parse_qso_logged(data, offset, id_str)
        return None

    @staticmethod
    def _parse_status(data: bytes, offset: int, id_str: str) -> StatusMessage | None:
        try:
            (freq,) = struct.unpack_from(">Q", data, offset)
            offset += 8
            mode, offset = _read_utf8(data, offset)
            dx_call, offset = _read_utf8(data, offset)
            report, offset = _read_utf8(data, offset)
            tx_mode, offset = _read_utf8(data, offset)
            if offset + 3 > len(data):
                return None
            tx_enabled = data[offset] != 0
            transmitting = data[offset + 1] != 0
            decoding = data[offset + 2] != 0
            offset += 3
            if offset + 8 > len(data):
                return None
            (rx_df,) = struct.unpack_from(">i", data, offset)
            offset += 4
            (tx_df,) = struct.unpack_from(">i", data, offset)
            offset += 4
            de_call, offset = _read_utf8(data, offset)
            de_grid, offset = _read_utf8(data, offset)
            dx_grid, offset = _read_utf8(data, offset)
            return StatusMessage(
                id=id_str,
                frequency=freq,
                mode=mode,
                de_call=(de_call or "").strip(),
                de_grid=(de_grid or "").strip(),
                dx_call=(dx_call or "").strip(),
                dx_grid=(dx_grid or "").strip(),
                transmitting=transmitting,
                decoding=decoding,
            )
        except (struct.error, IndexError):
            return None

    @staticmethod
    def _parse_decode(data: bytes, offset: int, id_str: str) -> DecodeMessage | None:
        try:
            if offset + 1 > len(data):
                return None
            is_new = data[offset] != 0
            offset += 1
            if offset + 4 > len(data):
                return None
            (time_ms,) = struct.unpack_from(">I", data, offset)
            offset += 4
            (snr,) = struct.unpack_from(">i", data, offset)
            offset += 4
            (dt,) = struct.unpack_from(">d", data, offset)
            offset += 8
            (df,) = struct.unpack_from(">I", data, offset)
            offset += 4
            mode, offset = _read_utf8(data, offset)
            message, offset = _read_utf8(data, offset)
            return DecodeMessage(
                id=id_str,
                is_new=is_new,
                time_ms=time_ms,
                snr=snr,
                dt=dt,
                df=df,
                mode=(mode or "").strip(),
                message=(message or "").strip(),
            )
        except (struct.error, IndexError):
            return None

    @staticmethod
    def _parse_qso_logged(data: bytes, offset: int, id_str: str) -> QSOLoggedMessage | None:
        try:
            if offset + 13 > len(data):
                return None
            (julian,) = struct.unpack_from(">q", data, offset)
            offset += 8
            (ms_since_midnight,) = struct.unpack_from(">I", data, offset)
            offset += 4
            (timespec,) = struct.unpack_from(">B", data, offset)
            offset += 1
            if timespec == 2 and offset + 4 <= len(data):
                offset += 4
            dx_call, offset = _read_utf8(data, offset)
            dx_grid, offset = _read_utf8(data, offset)
            if offset + 8 > len(data):
                return None
            (freq,) = struct.unpack_from(">Q", data, offset)
            offset += 8
            mode, offset = _read_utf8(data, offset)
            rpt_sent, offset = _read_utf8(data, offset)
            rpt_rcvd, offset = _read_utf8(data, offset)
            tx_power, offset = _read_utf8(data, offset)
            comments, offset = _read_utf8(data, offset)
            name, offset = _read_utf8(data, offset)
            if offset + 13 > len(data):
                return None
            offset += 8 + 4 + 1
            if offset + 4 <= len(data):
                (o,) = struct.unpack_from(">B", data, offset - 1)
                if o == 2:
                    offset += 4
            operator_call, offset = _read_utf8(data, offset)
            my_call, offset = _read_utf8(data, offset)
            my_grid, offset = _read_utf8(data, offset)
            exch_sent, offset = _read_utf8(data, offset)
            exch_rcvd, offset = _read_utf8(data, offset)
            ts_off = _qdatetime_to_unix(julian, ms_since_midnight)
            return QSOLoggedMessage(
                id=id_str,
                dx_call=(dx_call or "").strip(),
                dx_grid=(dx_grid or "").strip(),
                frequency=freq,
                my_call=(my_call or "").strip(),
                my_grid=(my_grid or "").strip(),
                timestamp_off=ts_off,
            )
        except (struct.error, IndexError):
            return None
