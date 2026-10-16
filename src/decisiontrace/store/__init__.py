"""Local append-only store."""

from decisiontrace.store.sqlite import (
    AmbiguousId,
    AppendResult,
    DuplicateRecord,
    Store,
    StoreError,
    UnknownRecord,
    VerifyResult,
)

__all__ = [
    "AmbiguousId",
    "AppendResult",
    "DuplicateRecord",
    "Store",
    "StoreError",
    "UnknownRecord",
    "VerifyResult",
]
