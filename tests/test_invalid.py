"""Invalid records must be rejected by BOTH the schema and the models."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError

from decisiontrace.model import parse_record
from decisiontrace.schema import schema_errors

Mutation = Callable[[dict[str, Any]], None]


def _drop(key: str) -> Mutation:
    return lambda r: r.pop(key)


def _set(path: str, value: Any) -> Mutation:
    def apply(r: dict[str, Any]) -> None:
        *parents, last = path.split(".")
        node: Any = r
        for p in parents:
            node = node[int(p)] if p.isdigit() else node[p]
        if last.isdigit():
            node[int(last)] = value
        else:
            node[last] = value

    return apply


MUTATIONS: dict[str, Mutation] = {
    "missing id": _drop("id"),
    "missing intent": _drop("intent"),
    "missing actor_time": _drop("actor_time"),
    "empty intent": _set("intent", ""),
    "bad ulid": _set("id", "not-a-ulid"),
    "lowercase ulid": _set("id", "01m4zcmbm0ktcpx4fh08g1vsbh"),
    "wrong schema version": _set("schema_version", "9.9.9"),
    "unknown record type": _set("record_type", "thought"),
    "unknown top-level field": _set("reasoning", "chain of thought"),
    "unknown nested field": _set("actor_time.actor.email", "x@example.com"),
    "bad actor type": _set("actor_time.actor.type", "robot"),
    "naive timestamp": _set("actor_time.started_at", "2026-10-15T09:00:00"),
    "date only": _set("actor_time.started_at", "2026-10-15"),
    "bad policy result": _set("policies.0.result", "maybe"),
    "bad policy engine": _set("policies.0.engine", "regex"),
    "bad human event": _set("human_path.0.type", "liked"),
    "bad outcome status": _set("outcome", {"status": "great"}),
    "bad link type": _set("links", [{"type": "likes", "target_id": "01M4ZD6NJ0X3RVH2AQFXQMTRJ7"}]),
    "bad sha256": _set("context.inputs.0.hash", "md5:abc"),
    "bad label": _set("decision_kind", "Refund Approve"),
    "bad namespace": _set("namespace", "Acme Corp"),
    "duplicate capabilities": _set("capabilities", ["a.b", "a.b"]),
    "bad attribute key": _set("attributes", {"Priority": "high"}),
    "negative cost": _set("actor_time.cost.usd", -1),
    "intent too long": _set("intent", "x" * 501),
}


@pytest.mark.parametrize("name", MUTATIONS)
def test_rejected_by_schema_and_model(name: str, refund_example: dict[str, Any]) -> None:
    record = copy.deepcopy(refund_example)
    MUTATIONS[name](record)
    assert schema_errors(record), f"schema accepted: {name}"
    with pytest.raises(ValidationError):
        parse_record(record)


def test_correction_needs_valid_paths() -> None:
    base = {
        "record_type": "correction",
        "schema_version": "0.1.0",
        "id": "01M4ZJXRY0F93QFDXWHGMM3HSS",
        "namespace": "local",
        "trace_id": "01M4ZDRZG0H1T0NCG78SRRADYC",
        "reason": "typo",
        "corrected_by": {"type": "human", "id": "user:praveen"},
        "corrected_at": "2026-10-15T17:00:00Z",
    }
    for changes in ({}, {"Policies[0]": 1}, {"intent; drop table": "x"}):
        bad = {**base, "changes": changes}
        assert schema_errors(bad)
        with pytest.raises(ValidationError):
            parse_record(bad)


def test_schema_errors_point_at_the_field(refund_example: dict[str, Any]) -> None:
    record = copy.deepcopy(refund_example)
    record["policies"][0]["result"] = "maybe"
    errors = schema_errors(record)
    assert any(e.startswith("policies/0/result") for e in errors), errors
