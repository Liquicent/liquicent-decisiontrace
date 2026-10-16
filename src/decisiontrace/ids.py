"""ULID identifiers: sortable by creation time, no coordination needed."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_DECODE = {c: i for i, c in enumerate(_ALPHABET)}


def new_ulid(timestamp_ms: int | None = None) -> str:
    """Return a new ULID (48-bit ms timestamp + 80 random bits, Crockford base32)."""
    ms = time.time_ns() // 1_000_000 if timestamp_ms is None else timestamp_ms
    if not 0 <= ms < 1 << 48:
        raise ValueError("timestamp out of ULID range")
    value = (ms << 80) | int.from_bytes(os.urandom(10), "big")
    chars = []
    for _ in range(26):
        chars.append(_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def ulid_time(ulid: str) -> datetime:
    """Return the creation time encoded in a ULID."""
    if len(ulid) != 26:
        raise ValueError("ULID must be 26 characters")
    value = 0
    for c in ulid:
        value = (value << 5) | _DECODE[c]
    return datetime.fromtimestamp((value >> 80) / 1000, tz=UTC)
