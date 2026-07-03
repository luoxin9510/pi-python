"""ID and timestamp helpers. uuid7 self-implemented (RFC 9562) — no third dep."""

import os
import secrets
import threading
import time
from datetime import datetime, timezone

_lock = threading.Lock()
_last_ms = -1
_seq = 0


def new_entry_id() -> str:
    return secrets.token_hex(4)


def new_session_id() -> str:
    global _last_ms, _seq
    with _lock:
        ms = time.time_ns() // 1_000_000
        if ms <= _last_ms:
            _seq += 1
        else:
            _last_ms, _seq = ms, 0
        # 12-bit rand_a 用作同毫秒单调计数器，保证排序稳定
        rand_a = _seq & 0x0FFF
        rand_b = int.from_bytes(os.urandom(8), "big") & 0x3FFF_FFFF_FFFF_FFFF
        value = (ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
        h = f"{value:032x}"
        return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def iso_now() -> str:
    now = datetime.now(timezone.utc)  # 只取一次，避免跨秒边界错乱
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
