from __future__ import annotations

from pathlib import Path

import pytest

from decisiontrace.model import DecisionTrace, parse_record, to_json_dict
from decisiontrace.schema import schema_errors
from tests.conftest import EXAMPLES, load


def test_there_are_ten_decision_examples() -> None:
    kinds = [load(p)["record_type"] for p in EXAMPLES]
    assert kinds.count("decision") == 10
    assert {"outcome", "correction"} <= set(kinds)


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_example_matches_schema(path: Path) -> None:
    assert schema_errors(load(path)) == []


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_example_round_trips_through_model(path: Path) -> None:
    original = load(path)
    record = parse_record(original)
    dumped = to_json_dict(record)
    assert dumped == original
    assert schema_errors(dumped) == []
    assert parse_record(dumped) == record


def test_links_and_trace_ids_resolve() -> None:
    records = [load(p) for p in EXAMPLES]
    ids = {r["id"] for r in records}
    assert len(ids) == len(records), "example ids must be unique"
    for r in records:
        for link in r.get("links", []):
            assert link["target_id"] in ids
        if "trace_id" in r:
            assert r["trace_id"] in ids


def test_examples_store_no_reasoning() -> None:
    """CLAUDE.md #7: execution, not cognition."""
    for path in EXAMPLES:
        text = path.read_text(encoding="utf-8").lower()
        for word in ("thinking", "chain_of_thought", "reasoning"):
            assert word not in text, f"{path.name} mentions {word}"


def test_records_are_immutable(refund_example: dict[str, object]) -> None:
    record = parse_record(refund_example)
    assert isinstance(record, DecisionTrace)
    with pytest.raises(Exception, match="frozen"):
        record.intent = "changed"  # type: ignore[misc]
