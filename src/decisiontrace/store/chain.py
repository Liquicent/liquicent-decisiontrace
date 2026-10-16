"""Per-store hash chain: each record commits to the one before it."""

from __future__ import annotations

import hashlib
import json
from typing import Any

GENESIS = "sha256:" + "0" * 64


def canonical(record: dict[str, Any]) -> str:
    """Canonical JSON of a record, excluding its ``integrity`` block."""
    body = {k: v for k, v in record.items() if k != "integrity"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def link_hash(prev_hash: str, canonical_json: str) -> str:
    digest = hashlib.sha256()
    digest.update(prev_hash.encode("ascii"))
    digest.update(b"\n")
    digest.update(canonical_json.encode("utf-8"))
    return "sha256:" + digest.hexdigest()
