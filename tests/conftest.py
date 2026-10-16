from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = sorted((ROOT / "schema" / "examples").glob("*.json"))


def load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


@pytest.fixture
def refund_example() -> dict[str, Any]:
    return load(ROOT / "schema" / "examples" / "01-refund-approved-with-vip-exception.json")


@pytest.fixture
def config(tmp_path: Path) -> Any:
    from decisiontrace.config import init_home
    from decisiontrace.store import Store

    cfg = init_home(tmp_path / "dt")
    Store.open(cfg).close()  # like `dt init`: config + database
    return cfg


@pytest.fixture
def store(config: Any) -> Any:
    from decisiontrace.store import Store

    with Store.open(config) as s:
        yield s


def example_records() -> list[dict[str, Any]]:
    """Decisions first, then the outcome/correction records that point at them."""
    records = [load(p) for p in EXAMPLES]
    return sorted(records, key=lambda r: r["record_type"] != "decision")
