from __future__ import annotations

import itertools
import sqlite3
from typing import Any

import pytest

from decisiontrace.ids import new_ulid
from decisiontrace.model import DecisionTrace, OutcomeRecord, to_json_dict
from decisiontrace.store import AmbiguousId, DuplicateRecord, Store, UnknownRecord
from decisiontrace.store.chain import GENESIS
from decisiontrace.synthetic import synthetic_decisions
from tests.conftest import EXAMPLES, example_records


def test_append_and_read_back(store: Store) -> None:
    results = store.append_many(example_records())
    assert len(results) == len(EXAMPLES)
    first = store.get(results[0].record.id)
    assert first.integrity is not None
    assert first.integrity.prev_hash == GENESIS
    stored = to_json_dict(first)
    stored.pop("integrity")
    assert stored == example_records()[0]


def test_chain_links_each_record_to_the_previous(store: Store) -> None:
    store.append_many(example_records())
    recs = list(store.records(newest_first=False))
    for prev, cur in itertools.pairwise(recs):
        assert prev.integrity and cur.integrity
        assert cur.integrity.prev_hash == prev.integrity.hash
    assert store.head() == (len(EXAMPLES), recs[-1].integrity.hash)  # type: ignore[union-attr]


def test_appends_across_sessions_continue_the_chain(config: Any) -> None:
    recs = synthetic_decisions(4)
    with Store.open(config) as s:
        s.append_many(recs[:2])
    with Store.open(config) as s:
        s.append_many(recs[2:])
        assert s.verify().ok
        assert s.count() == 4


def test_duplicate_id_rejected_and_batch_rolled_back(store: Store) -> None:
    recs = synthetic_decisions(3)
    store.append(recs[0])
    with pytest.raises(DuplicateRecord):
        store.append_many([recs[1], recs[0]])
    assert store.count() == 1
    assert store.verify().ok


def test_outcome_needs_an_existing_trace(store: Store) -> None:
    outcome = next(r for r in example_records() if r["record_type"] == "outcome")
    with pytest.raises(UnknownRecord):
        store.append(outcome)


def test_outcome_and_decision_in_same_batch(store: Store) -> None:
    store.append_many(example_records())
    code_edit = next(r for r in example_records() if r["decision_kind"] == "code.edit")
    related = store.related(code_edit["id"])
    assert [type(r) for r in related] == [OutcomeRecord]


def test_sql_cannot_update_or_delete(store: Store, config: Any) -> None:
    store.append_many(example_records())
    conn = sqlite3.connect(config.db_path)
    for sql in (
        "UPDATE records SET intent = 'x'",
        "DELETE FROM records",
        "UPDATE links SET type = 'x'",
        "DELETE FROM links",
    ):
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(sql)
    conn.close()


def test_prefix_lookup(store: Store) -> None:
    rec = synthetic_decisions(1)[0]
    store.append(rec)
    assert store.get(rec["id"][:8].lower()).id == rec["id"]
    with pytest.raises(UnknownRecord):
        store.get("ZZZZZZ")


def test_ambiguous_prefix(store: Store) -> None:
    store.append_many(synthetic_decisions(3))
    with pytest.raises(AmbiguousId):
        store.get("0")


def test_filters(store: Store) -> None:
    store.append_many(synthetic_decisions(10))
    kinds = {
        r.decision_kind
        for r in store.records(decision_kind="refund")
        if isinstance(r, DecisionTrace)
    }
    assert kinds == {"refund.approve"}
    assert len(list(store.records(limit=3))) == 3


def test_bodies_are_off_by_default(store: Store) -> None:
    rec = synthetic_decisions(1)[0]
    store.append(rec, bodies={"prompt": "full prompt text"})
    assert store.bodies(rec["id"]) == {}


def test_bodies_opt_in_redacted_and_erasable(tmp_path: Any) -> None:
    from decisiontrace.config import Config

    config = Config(home=tmp_path, store_bodies=True, salt=b"s")
    with Store.open(config) as s:
        rec = synthetic_decisions(1)[0]
        s.append(rec, bodies={"prompt": "use key sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAA please"})
        assert s.bodies(rec["id"]) == {"prompt": "use key [REDACTED:anthropic_key] please"}
        assert s.forget_bodies(rec["id"]) == 1
        assert s.bodies(rec["id"]) == {}
        assert s.verify().ok, "erasing a body must not break the chain"


def test_links_are_indexed(store: Store) -> None:
    store.append_many(example_records())
    child = next(r for r in example_records() if r["decision_kind"] == "code.search")
    assert (
        "delegation",
        next(r["id"] for r in example_records() if r["decision_kind"] == "research.delegate"),
    ) in store.links_to(child["id"])


def test_export_round_trip(store: Store, tmp_path: Any) -> None:
    import io
    import json

    store.append_many(example_records())
    buf = io.StringIO()
    assert store.export_jsonl(buf) == len(EXAMPLES)
    lines = [json.loads(line) for line in buf.getvalue().splitlines()]
    assert all("integrity" in line for line in lines)
    assert [line["id"] for line in lines] == [r["id"] for r in example_records()]


def test_new_records_get_valid_ids(store: Store) -> None:
    rec = {**synthetic_decisions(1)[0], "id": new_ulid()}
    assert store.append(rec).record.id == rec["id"]


def test_empty_store_verifies(store: Store) -> None:
    assert store.verify().ok


def test_index_is_not_rebuilt_on_every_open(config: Any) -> None:
    with Store.open(config) as s:
        s.append_many(synthetic_decisions(5))  # no file/commit refs
    with Store.open(config) as s:
        s._conn.execute("INSERT INTO search (record_id, text) VALUES ('marker', 'x')")
    with Store.open(config) as s:
        # a rebuild would have wiped the marker row; counts differ so it *should* rebuild here
        assert s._conn.execute("SELECT COUNT(*) FROM search").fetchone()[0] == 5
        s._conn.execute("UPDATE meta SET value = 'old' WHERE key = 'index_version'")
    with Store.open(config) as s:
        assert (
            s._conn.execute("SELECT value FROM meta WHERE key='index_version'").fetchone()[0] == "2"
        )
