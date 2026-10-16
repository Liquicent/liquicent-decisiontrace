"""Exit test: 100k synthetic traces write in under a minute. Run with DT_BENCH=1."""

from __future__ import annotations

import os
import time
from typing import Any

import pytest

from decisiontrace.store import Store
from decisiontrace.synthetic import synthetic_decisions

pytestmark = pytest.mark.skipif(not os.environ.get("DT_BENCH"), reason="set DT_BENCH=1")


def test_100k_under_a_minute(config: Any) -> None:
    records = synthetic_decisions(100_000)
    with Store.open(config) as s:
        start = time.perf_counter()
        s.append_many(records)
        elapsed = time.perf_counter() - start
        print(f"\n100k appended in {elapsed:.1f}s")
        assert s.count() == 100_000
        assert s.verify().ok
    assert elapsed < 60
