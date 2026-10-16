from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest

from decisiontrace.ids import new_ulid, ulid_time

PATTERN = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def test_format() -> None:
    assert PATTERN.match(new_ulid())


def test_time_round_trip() -> None:
    when = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
    ulid = new_ulid(int(when.timestamp() * 1000))
    assert ulid_time(ulid) == when


def test_sortable_by_time() -> None:
    ids = [new_ulid(t) for t in (1_000, 2_000, 3_000)]
    assert ids == sorted(ids)


def test_unique() -> None:
    assert len({new_ulid(5) for _ in range(10_000)}) == 10_000


def test_out_of_range() -> None:
    with pytest.raises(ValueError):
        new_ulid(-1)
    with pytest.raises(ValueError):
        new_ulid(1 << 48)
