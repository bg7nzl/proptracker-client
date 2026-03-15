# FT8 Propagation Tracker — UDP listener thread
from __future__ import annotations

import logging
import socket
import threading
import time
from typing import Callable

from .models import DecodeMessage, QSOLoggedMessage, StatusMessage
from .wsjtx_parser import WsjtxParser


class UdpListener(threading.Thread):
    def __init__(
        self,
        port: int,
        on_status: Callable[[StatusMessage], None],
        on_decode: Callable[[DecodeMessage, int], None],
        on_qso_logged: Callable[[QSOLoggedMessage], None],
        logger: logging.Logger,
        bind_ip: str = "",
        multicast: bool = False,
    ) -> None:
        super().__init__(daemon=True)
        self._port = port
        self._bind_ip = bind_ip
        self._multicast = multicast
        self._on_status = on_status
        self._on_decode = on_decode
        self._on_qso_logged = on_qso_logged
        self._log = logger
        self._sock: socket.socket | None = None
        self._running = True
        self._last_message_time: float = 0
        self._instance_id: str = ""

    def run(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # SO_REUSEPORT allows multiple processes to bind same port (e.g. with GridTracker over multicast)
        if self._multicast and hasattr(socket, "SO_REUSEPORT"):
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        try:
            self._sock.bind(("", self._port))
        except OSError as e:
            self._log.error("UDP bind failed: %s", e)
            return
        if self._multicast:
            try:
                import struct as _st
                mreq = _st.pack("4sl", socket.inet_aton(self._bind_ip), socket.INADDR_ANY)
                self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                self._log.info("Joined multicast group %s", self._bind_ip)
            except OSError as e:
                self._log.error("Multicast join failed: %s", e)
                return
        self._log.info("UDP listening on port %s (bind=%s)", self._port, self._bind_ip or "0.0.0.0")
        while self._running and self._sock:
            try:
                data, _ = self._sock.recvfrom(4096)
                self._last_message_time = time.time()
                msg = WsjtxParser.parse(data)
                if isinstance(msg, StatusMessage):
                    self._instance_id = msg.id
                    self._on_status(msg)
                elif isinstance(msg, DecodeMessage):
                    ts = int(time.time())
                    self._on_decode(msg, ts)
                elif isinstance(msg, QSOLoggedMessage):
                    self._on_qso_logged(msg)
            except Exception as e:
                self._log.debug("UDP parse error: %s", e)
        if self._sock:
            self._sock.close()
            self._sock = None

    def stop(self) -> None:
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    @property
    def last_message_time(self) -> float:
        return self._last_message_time

    @property
    def instance_id(self) -> str:
        return self._instance_id
