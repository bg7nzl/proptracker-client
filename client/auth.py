# FT8 Propagation Tracker — Phase 4 client auth token (standard library only)
from __future__ import annotations

import base64
import hashlib
import os
import struct
import time


def make_auth_token(api_key: str, body: bytes) -> str:
    """生成 FT8Auth token（56 字符 base64）。

    body: 即将发送的请求体原始字节（用于 payload_hash）。
    """
    key_hash = hashlib.sha256(api_key.encode("utf-8")).digest()[:4]
    timestamp = struct.pack(">Q", int(time.time()))
    random_bytes = os.urandom(4)
    payload_hash = hashlib.sha256(body).digest()[:8]
    nonce = timestamp + random_bytes + payload_hash
    proof = hashlib.sha256(nonce + api_key.encode("utf-8")).digest()[:16]
    return base64.b64encode(key_hash + nonce + proof).decode("ascii")
