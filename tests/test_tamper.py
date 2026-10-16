"""Tampering with the database file must make `verify` fail."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from decisiontrace.store import Store
from decisiontrace.synthetic import synthetic_decisions


def _raw(config: Any) -> sqlite3.Connection:
    conn = sqlite3.connect(config.db_path, isolation_level=None)
    conn.execute("DROP TRIGGER records_no_update")
    conn.execute("DROP TRIGGER records_no_delete")
    return conn


def _seeded(config: Any, n: int = 20) -> None:
    with Store.open(config) as s:
        s.append_many(synthetic_decisions(n))
        assert s.verify().ok


def _verify(config: Any) -> Any:
    with Store.open(config) as s:
        return s.verify()


def test_edit_one_field(config: Any) -> None:
    _seeded(config)
    conn = _raw(config)
    body = json.loads(conn.execute("SELECT body FROM records WHERE seq = 7").fetchone()[0])
    body["policies"][0]["result"] = "pass" if body["policies"][0]["result"] == "fail" else "fail"
    conn.execute(
        "UPDATE records SET body = ? WHERE seq = 7",
        (json.dumps(body, sort_keys=True, separators=(",", ":")),),
    )
    result = _verify(config)
    assert not result.ok
    assert any("seq 7" in p and "hash" in p for p in result.problems)


def test_edit_and_rehash_one_row(config: Any) -> None:
    """Recomputing the edited row's hash still breaks the next link."""
    from decisiontrace.store.chain import link_hash

    _seeded(config)
    conn = _raw(config)
    body, prev = conn.execute("SELECT body, prev_hash FROM records WHERE seq = 5").fetchone()
    body = body.replace("Customer issue", "Customer issuf")
    conn.execute(
        "UPDATE records SET body = ?, hash = ? WHERE seq = 5", (body, link_hash(prev, body))
    )
    result = _verify(config)
    assert not result.ok
    assert any("seq 6" in p and "chain broken" in p for p in result.problems)


def test_delete_middle_row(config: Any) -> None:
    _seeded(config)
    _raw(config).execute("DELETE FROM records WHERE seq = 10")
    result = _verify(config)
    assert not result.ok
    assert any("seq 11" in p for p in result.problems)


def test_truncate_tail(config: Any) -> None:
    _seeded(config)
    _raw(config).execute("DELETE FROM records WHERE seq > 15")
    result = _verify(config)
    assert not result.ok
    assert any("removed from the end" in p for p in result.problems)


def test_swap_indexed_column(config: Any) -> None:
    _seeded(config)
    _raw(config).execute("UPDATE records SET record_type = 'outcome' WHERE seq = 3")
    result = _verify(config)
    assert not result.ok
    assert any("indexed columns" in p for p in result.problems)


def test_untouched_store_verifies(config: Any) -> None:
    _seeded(config, 50)
    assert _verify(config).ok
