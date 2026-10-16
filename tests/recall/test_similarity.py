from __future__ import annotations

import copy
from typing import Any

import pytest

from decisiontrace.model import DecisionTrace, parse_record
from decisiontrace.recall.precedent import candidates, similar
from decisiontrace.recall.similarity import Weights, similarity
from decisiontrace.store import Store
from tests.conftest import example_records


def _dt(data: dict[str, Any]) -> DecisionTrace:
    rec = parse_record(data)
    assert isinstance(rec, DecisionTrace)
    return rec


@pytest.fixture
def refund(refund_example: dict[str, Any]) -> DecisionTrace:
    return _dt(refund_example)


def test_identical_decisions_score_one(refund: DecisionTrace) -> None:
    s = similarity(refund, refund)
    assert s.total == 1.0 and s.strength == "strong"


def test_components_in_range(refund: DecisionTrace) -> None:
    other = _dt(next(r for r in example_records() if r["decision_kind"] == "pr.merge"))
    s = similarity(refund, other)
    assert all(0.0 <= v <= 1.0 for v in s.components.values())
    assert s.strength == "none"


def test_policy_disagreement_lowers_p(refund_example: dict[str, Any]) -> None:
    a = _dt(refund_example)
    flipped = copy.deepcopy(refund_example)
    flipped["id"] = "01M4ZCMBM0KTCPX4FH08G1VSBJ"
    flipped["policies"][0]["result"] = "pass"
    flipped.pop("exceptions")
    s = similarity(a, _dt(flipped))
    assert s.components["P"] < 1.0
    assert s.total < 1.0


def test_age_gap_penalised(refund_example: dict[str, Any]) -> None:
    a = _dt(refund_example)
    later = copy.deepcopy(refund_example)
    later["id"] = "01M4ZCMBM0KTCPX4FH08G1VSBK"
    later["actor_time"]["started_at"] = "2027-10-15T09:00:00Z"
    s = similarity(a, _dt(later), Weights(lam=0.2))
    assert s.components["dt"] == pytest.approx(1.0)
    assert s.total == pytest.approx(0.8)


def test_weights_and_thresholds_from_config(config: Any) -> None:
    (config.home / "config.toml").write_text(
        (config.home / "config.toml").read_text()
        + "\n[recall]\nalpha = 0.5\nstrong = 0.9\nlambda = 0.0\n"
    )
    w = Weights.from_config(config.home)
    assert (w.alpha, w.strong, w.lam) == (0.5, 0.9, 0.0)


def test_no_policies_on_either_side_does_not_cap_score() -> None:
    edit = _dt(next(r for r in example_records() if r["decision_kind"] == "code.search"))
    assert not edit.policies
    assert similarity(edit, edit).total == 1.0


def test_candidate_filter_shared_policy_then_fallback(store: Store) -> None:
    store.append_many(example_records())
    refund = store.get("01M4ZCMB")
    assert isinstance(refund, DecisionTrace)
    # no other decision shares refund.max_auto_amount / evidence_required → refund family
    assert [c.decision_kind for c in candidates(store, refund)] == ["refund.deny"]
    shared = store.get("01M4ZFFX")  # denied push: shares permission rules with nothing else
    assert isinstance(shared, DecisionTrace)
    assert {c.decision_kind for c in candidates(store, shared)} <= {"tool.call"}
    edit = store.get("01M4ZEB9")  # Edit(src/**) policy: no other trace has it → code family
    assert isinstance(edit, DecisionTrace)
    assert {c.decision_kind for c in candidates(store, edit)} == {"code.search"}


def test_similar_ranks_closest_first(store: Store, refund_example: dict[str, Any]) -> None:
    store.append_many(example_records())
    twin = copy.deepcopy(refund_example)
    twin["id"] = "01M4ZKG2W0YHFV08F6VD6R01YW"
    twin["intent"] = "Refund $910 for order 7790 (damaged in transit)"
    twin["actor_time"]["started_at"] = "2026-10-15T11:00:00Z"
    store.append(twin)
    refund = store.get("01M4ZCMB")
    assert isinstance(refund, DecisionTrace)
    hits = similar(store, refund, limit=3)
    assert hits[0].trace.id == twin["id"]
    assert hits[0].strength == "strong"
